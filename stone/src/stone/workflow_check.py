"""K24: report an unpinned tool in a CI workflow (D93)."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from stone import evidence_check
from stone.findings import Finding

CHECK = "K24"
WORKFLOWS = ".github/workflows/"
WAIVER = "waiver (k24)"
SHA = re.compile(r"^[0-9a-fA-F]{40}$")
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*[\"']?(?P<ref>[^\s\"'#]+)")
ENV_VALUE = re.compile(r"^\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*):\s*[\"']?(?P<value>[^\s\"'#]+)")
VARIABLE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
FETCH = r"(?:curl|wget)"
SHELL = r"(?:\S*/)?(?:ba|z|da|k)?sh|python\d*|node|perl|ruby"
RUN_DOWNLOAD = re.compile(
    rf"\b{FETCH}\b[^\n]*\|\s*(?:sudo(?:\s+-\S+)*\s+)?(?:env\s+)?(?:{SHELL})\b"
    rf"|[$<]\(\s*{FETCH}\b", re.IGNORECASE)
# Each form installs or runs a tool. The group "tool" names the rule that tests its arguments.
COMMAND = re.compile(
    r"(?:^|[\s;&|(\"'/])(?P<tool>(?:python\d*(?:\.\d+)?\s+-m\s+)?pip(?:3(?:\.\d+)?)?[\"']?(?:\s+-\S+)*\s+install"
    r"|uv\s+pip\s+install|pipx\s+install|npx|pnpm\s+dlx|yarn\s+dlx|bunx"
    r"|npm(?:\s+-\S+)*\s+(?:install|i|add)|pnpm\s+(?:add|install|i)|yarn\s+global\s+add|go\s+install)"
    r"(?=\s|$)(?P<args>[^\n;&|]*)")
PIP_VALUE_OPTIONS = {"-r", "--requirement", "-c", "--constraint", "-i", "--index-url",
                     "--extra-index-url", "-f", "--find-links", "-t", "--target", "--prefix",
                     "--root", "--only-binary", "--no-binary", "--platform", "--python-version",
                     "--implementation", "--abi", "--cache-dir", "--src", "--trusted-host",
                     "--upgrade-strategy", "-C", "--config-settings", "--python", "-p"}
GO_VALUE_OPTIONS = {"-tags", "-ldflags", "-gcflags", "-o", "-mod", "-modfile", "-p", "-pkgdir"}
REDIRECT = re.compile(r"^\d*(?:>>?|<|&>)")
NODE_VERSION = re.compile(r"^\d+\.\d+\.\d+")
GO_VERSION = re.compile(r"^v\d+\.\d+\.\d+")
ARCHIVE = (".whl", ".tar.gz", ".zip")
LOCAL = (".", "/", "~")


def _words(args: str) -> list[str]:
    args = re.split(r"(?:^|\s)#", args, maxsplit=1)[0]  # a shell comment; a '#' in a URL stays
    try:
        words = shlex.split(args)
    except ValueError:
        words = args.split()
    kept, skip = [], False
    for word in words:
        redirect = REDIRECT.match(word)
        if skip or redirect:
            skip = bool(redirect) and word == redirect.group(0)  # '> file' has the target apart
            continue
        kept.append(word)
    return kept


def _resolve(text: str, env: dict[str, str]) -> str:
    """Replace each $NAME or ${NAME} that an env key in the file sets."""
    return VARIABLE.sub(lambda match: env.get(match.group(1), match.group(0)), text)


def _pinned_url(token: str) -> bool:
    """A URL is pinned by a commit SHA after '@' or by a sha256 hash after '#'."""
    url = token.split(" @ ", 1)[-1]
    ref = url.split("#", 1)[0].rsplit("@", 1)
    return ("://" in ref[0] and len(ref) == 2 and bool(SHA.match(ref[1]))) or "sha256=" in url.partition("#")[2]


def _pip(words: list[str], env: dict[str, str]) -> list[str]:
    if "--require-hashes" in words:
        return []  # pip refuses each package that has no exact version and hash
    unpinned, skip = [], False
    for word in words:
        if skip:
            skip = False
            continue
        if word in PIP_VALUE_OPTIONS:
            skip = True
            continue
        word = _resolve(word, env)
        if word.startswith("-") and word not in ("-e", "--editable"):
            continue
        if (word in ("-e", "--editable") or word.startswith(LOCAL) or "$" in word
                or ("/" in word and "://" not in word and "@" not in word) or word.endswith(ARCHIVE)):
            continue  # a local path, or a value that the check cannot read
        if "://" in word:
            if not _pinned_url(word):
                unpinned.append(word)
        elif "==" not in word:
            unpinned.append(word)
    return unpinned


def _node_version(word: str) -> bool:
    name, at, version = word[1:].rpartition("@") if word.startswith("@") else word.rpartition("@")
    return bool(at and name and NODE_VERSION.match(version))


def _node(tool: str, words: list[str]) -> list[str]:
    runner = tool in ("npx", "pnpm dlx", "yarn dlx", "bunx")
    if not runner and not ({"-g", "--global"} & set(words + tool.split()) or tool == "yarn global add"):
        return []  # a project install takes the versions from the lockfile
    packages, take = [], False
    for word in words:
        if take:
            packages.append(word)
            take = False
        elif word in ("-p", "--package"):
            take = True
        elif not word.startswith("-"):
            if runner and packages:
                break  # after -p, the first word is the command to run
            packages.append(word)
            if runner:
                break  # a runner runs the first package; the rest are its arguments
    return [word for word in packages if not word.startswith(LOCAL) and not _node_version(word)]


def _go(words: list[str]) -> list[str]:
    unpinned, skip = [], False
    for word in words:
        if skip or word in GO_VALUE_OPTIONS:
            skip = not skip and word in GO_VALUE_OPTIONS
            continue
        if word.startswith(("-",) + LOCAL):
            continue
        _, at, version = word.rpartition("@")
        if not at or not (GO_VERSION.match(version) or SHA.match(version)):
            unpinned.append(word)
    return unpinned


def line_findings(line: str, env: dict[str, str]) -> list[str]:
    """Return a message for each unpinned tool in one logical line of a workflow."""
    if line.lstrip().startswith("#") or re.match(r"^\s*(?:-\s+)?name:", line):
        return []
    messages = []
    uses = USES.match(line)
    if uses:
        ref = uses.group("ref")
        if ref.startswith("docker://"):
            if "@sha256:" not in ref:
                messages.append(f"The image '{ref}' has no digest. Pin it with @sha256:<digest>.")
        elif not ref.startswith("./") and not SHA.match(ref.rpartition("@")[2]):
            messages.append(f"The action '{ref}' is not pinned to a commit. Pin it to a "
                            "40-character commit SHA, with the tag in a comment.")
        return messages
    if RUN_DOWNLOAD.search(line):
        messages.append("A download runs in a shell. Download a pinned file, check its hash, "
                        "then run it.")
    line = re.sub(r"\$\{\{.*?\}\}", "$EXPR", line)  # a value that the check cannot read
    for match in COMMAND.finditer(line):
        tool = " ".join(match.group("tool").replace('"', "").replace("'", "").split())
        words = _words(match.group("args"))
        if tool.endswith("install") and "pip" in tool:
            unpinned = _pip(words, env)
            how = "an exact version (==), a commit SHA, or --require-hashes"
        elif tool == "go install":
            unpinned = _go(words)
            how = "a version (@vX.Y.Z) or a commit SHA"
        else:
            unpinned = _node(tool, words)
            how = "an exact version (@X.Y.Z)"
        for name in unpinned:
            messages.append(f"'{tool}' gets '{name}' with no pinned version. Give {how}.")
    return messages


def logical_lines(text: str) -> list[tuple[int, str]]:
    """Return (first line number, text) for each line. A '\\', '|', or '&&' at the end joins the next."""
    lines, start, parts = [], 0, []
    for number, line in enumerate(text.splitlines(), start=1):
        start = start or number
        if line.rstrip().endswith("\\"):
            parts.append(line.rstrip()[:-1])
            continue
        if line.rstrip().endswith(("|", "&&", "||")) and not re.search(r":\s*[|>][-+]?\s*$", line):
            parts.append(line.rstrip())  # the shell reads the next line as part of it
            continue
        lines.append((start, " ".join(parts + [line])))
        start, parts = 0, []
    if parts:
        lines.append((start, " ".join(parts)))
    return lines


def file_findings(path: str, text: str) -> list[Finding]:
    env = {}
    for line in text.splitlines():
        match = ENV_VALUE.match(line)
        if match:
            env[match.group("name")] = match.group("value")
    return [Finding(path, number, CHECK, message)
            for number, line in logical_lines(text) for message in line_findings(line, env)]


def is_workflow(path: str) -> bool:
    return path.startswith(WORKFLOWS) and path.endswith((".yml", ".yaml"))


def workflow_files(root: Path, base: str | None) -> list[str]:
    """Return the workflow files that the PR adds or changes, or each one if base is None."""
    if base is None:
        args = ["ls-files", "-z", "--", WORKFLOWS]
    else:
        args = ["diff", "-z", "--name-only", "--diff-filter=AMR", f"{base}...HEAD", "--", WORKFLOWS]
    run = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip() or f"git {args[0]} failed")
    return sorted(path for path in run.stdout.split("\0") if is_workflow(path))


def has_waiver(body: str) -> bool:
    """True if a heading with "waiver (K24)" has text under it."""
    lines = body.replace("\r\n", "\n").splitlines()
    found = evidence_check.headings(lines)
    return any(WAIVER in heading.name and not evidence_check.is_empty(
        evidence_check.section_body(lines, heading, found, set())) for heading in found)


def check(root: Path, base: str | None, body: str) -> list[Finding]:
    """Return a K24 finding for each unpinned tool. A waiver makes each one a warning."""
    findings = []
    for path in workflow_files(root, base):
        file = root / path
        if file.is_file():
            findings += file_findings(path, file.read_text(encoding="utf-8", errors="replace"))
    if has_waiver(body):
        findings = [Finding(f.path, f.line, f.check, f.message, "warning") for f in findings]
    return findings
