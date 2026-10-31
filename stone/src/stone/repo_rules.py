"""Checks for rules that this repo states in prose (P6, D78, D79): action pins, version bump, and
event text in `run`.

These checks are for the repo of the framework. `stone render` does not write them for a target repo.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from stone.findings import Finding

PIN_CHECK = "R1"
BUMP_CHECK = "R2"
ENV_CHECK = "R3"
WORKFLOWS = ".github/workflows"
TEMPLATES = "framework/adapters/*/templates/workflows"
SKILLS = "plugins/cornerstone/skills/"
PLUGIN_FILE = "plugins/cornerstone/.claude-plugin/plugin.json"

_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<value>[^#\n]*?)\s*(?:#.*)?$")
_ACTION_PIN = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
_IMAGE_PIN = re.compile(r"^docker://\S+@sha256:[0-9a-f]{64}$")
_RUN = re.compile(r"^(?P<indent>\s*(?:-\s+)?)run:(?:\s+(?P<value>.*?))?\s*$")
_BLOCK = re.compile(r"^[|>][+-]?[0-9]?(?:\s+#.*)?$")
_EVENT_TEXT = re.compile(r"\$\{\{[^}]*?\b(?P<name>github\.(?:event\.[\w.*-]+|head_ref))")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def is_pinned(value: str) -> bool:
    """A local action, an image with a digest, or an action at a full commit SHA passes."""
    if value.startswith("./"):
        return True
    return bool(_ACTION_PIN.match(value) or _IMAGE_PIN.match(value))


def check_pins(root: Path) -> list[Finding]:
    """R1: each `uses:` in a workflow file must be pinned to a full commit SHA."""
    findings: list[Finding] = []
    folder = root / WORKFLOWS
    files = sorted(p for pattern in ("*.yml", "*.yaml") for p in folder.glob(pattern))
    for path in files:
        rel = path.relative_to(root).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = _USES.match(line)
            if not match:
                continue
            value = _unquote(match.group("value"))
            if value and not is_pinned(value):
                findings.append(Finding(
                    rel, number, PIN_CHECK,
                    f"'uses: {value}' is not pinned to a commit. Replace the tag or branch with "
                    "the 40-character commit SHA, and keep the tag in a comment."))
    return findings


def _workflow_files(root: Path, folders: tuple[str, ...]) -> list[Path]:
    paths = {p for folder in folders for pattern in ("*.yml", "*.yaml")
             for p in root.glob(f"{folder}/**/{pattern}")}
    return sorted(paths)


def run_lines(text: str) -> list[tuple[int, str]]:
    """Return (line number, text) for each line of a `run` value. A pattern, not a YAML parser.

    An inline value gives one line. A block (`|` or `>`) gives each next line that is blank or
    indented more than the `run:` key. A `run:` with no value is a mapping key (for example a job
    named `run`), so it gives no line.
    """
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        match = _RUN.match(lines[index])
        index += 1
        if not match or not match.group("value"):
            continue
        value = match.group("value")
        if not _BLOCK.match(value):
            found.append((index, value))
            continue
        key_indent = len(match.group("indent"))
        while index < len(lines):
            line = lines[index]
            if line.strip() and len(line) - len(line.lstrip()) <= key_indent:
                break
            index += 1
            found.append((index, line))
    return found


def check_event_text(root: Path, folders: tuple[str, ...] = (WORKFLOWS, TEMPLATES)) -> list[Finding]:
    """R3: a `run` value must not hold `${{ github.event.* }}` or `${{ github.head_ref }}`."""
    findings: list[Finding] = []
    for path in _workflow_files(root, folders):
        rel = path.relative_to(root).as_posix()
        for number, line in run_lines(path.read_text(encoding="utf-8")):
            for match in _EVENT_TEXT.finditer(line):
                findings.append(Finding(
                    rel, number, ENV_CHECK,
                    f"'{match.group('name')}' is inline in 'run'. Event text can hold shell "
                    "code. Give it to the step in 'env', and use the variable in 'run'."))
    return findings


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout


def _version(text: str) -> str | None:
    try:
        value = json.loads(text).get("version")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def check_version_bump(root: Path, base: str, skills: str = SKILLS,
                       plugin_file: str = PLUGIN_FILE) -> list[Finding]:
    """R2: a change under `skills` needs a new `version` in `plugin_file`.

    The diff starts at the merge base of `base` and HEAD, and ends at HEAD. In CI, the result is
    the same as `git diff base...HEAD`.
    """
    merge_base = _git(root, "merge-base", base, "HEAD").strip()
    names = _git(root, "diff", "--name-only", merge_base, "HEAD", "--", skills).splitlines()
    if not names:
        return []
    old = _git_show(root, merge_base, plugin_file)
    new = _git_show(root, "HEAD", plugin_file)
    if new is None and old is not None:
        return []  # The plugin file left this tree (a rename or a removal). No version to bump.
    if new is None or _version(new) is None:
        return [Finding(plugin_file, 1, BUMP_CHECK,
                        "The file is missing or has no string 'version'. Add one, because a "
                        "skill changed.")]
    if old is not None and _version(old) == _version(new):
        return [Finding(plugin_file, 1, BUMP_CHECK,
                        f"{len(names)} file(s) under {skills} changed (first: {names[0]}), but "
                        f"'version' is still {_version(new)}. Increase 'version'.")]
    return []


def _git_show(root: Path, rev: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True,
                            text=True)
    return result.stdout if result.returncode == 0 else None


def run(root: Path, base: str | None, skills: str = SKILLS,
        plugin_file: str = PLUGIN_FILE) -> list[Finding]:
    findings = check_pins(root) + check_event_text(root)
    if base:
        findings += check_version_bump(root, base, skills, plugin_file)
    return findings
