"""K25: report a new state type that has no transition table (D120)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from stone import evidence_check
from stone.findings import Finding

CHECK = "K25"
WAIVER = "waiver (k25)"
MIN_STATES = 3  # two states are a flag, not a machine
SUFFIX = r"\w*(?:State|Status|Phase|Stage)"
PY_ENUM = re.compile(rf"^(?P<indent>\s*)class\s+(?P<name>{SUFFIX})\s*\([^)]*(?:Enum|Flag)\b[^)]*\)\s*:")
TS_ENUM = re.compile(rf"^\s*(?:export\s+)?(?:declare\s+)?(?:const\s+)?enum\s+(?P<name>{SUFFIX})\b")
TS_UNION = re.compile(rf"^\s*(?:export\s+)?type\s+(?P<name>{SUFFIX})\s*=")
LITERAL = re.compile(r"""(["'])[^"'\n]+\1""")
MEMBER = re.compile(r"^\s*[A-Za-z_]\w*\s*=")
# A name that holds the allowed moves. A CSS "transition:" or "transition-delay" does not count.
TABLE = re.compile(
    r"(?i)(?<![-\w])(?:\w*transitions?\w*(?![-\w])(?!\s*:\s*[\"'`\d])|next_?states?|allowed_?(?:next|moves)\w*)")
SOURCE = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts")
SKIP_PARTS = {"node_modules", "vendor", "dist", "build", "__pycache__", "tests", "test", "__tests__"}
SKIP_NAMES = re.compile(r"(?:^test_.*\.py$|_test\.py$|\.(?:test|spec)\.[mc]?[jt]sx?$)")
HUNK = re.compile(r"^@@ -\S+ \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")


def is_source(path: str) -> bool:
    parts = path.split("/")
    return (path.endswith(SOURCE) and not SKIP_NAMES.search(parts[-1])
            and not SKIP_PARTS.intersection(parts[:-1]))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _members_py(lines: list[str], index: int, indent: str) -> int:
    count = 0
    for line in lines[index + 1:]:
        if line.strip() and not line.startswith(indent + " ") and not line.startswith(indent + "\t"):
            break
        count += bool(MEMBER.match(line))
    return count


def _members_ts_enum(lines: list[str], index: int) -> int:
    body = "\n".join(lines[index:index + 200])
    body = re.sub(r"//[^\n]*|/\*.*?\*/", "", body, flags=re.DOTALL)
    start, end = body.find("{"), body.find("}")
    if start < 0 or end < start:
        return 0
    return len([item for item in body[start + 1:end].split(",") if item.strip()])


def _members_ts_union(lines: list[str], index: int) -> int:
    body = []
    for line in lines[index:index + 30]:
        body.append(line)
        if ";" in line or (len(body) > 1 and line.strip() and not line.lstrip().startswith("|")):
            break
    return len(LITERAL.findall("\n".join(body)))


def state_types(text: str) -> list[tuple[int, str, int]]:
    """Return (line number, name, member count) for each state type that the text declares."""
    lines = text.splitlines()
    found = []
    for index, line in enumerate(lines):
        py, ts_enum, union = PY_ENUM.match(line), TS_ENUM.match(line), TS_UNION.match(line)
        if py:
            found.append((index + 1, py.group("name"), _members_py(lines, index, py.group("indent"))))
        elif ts_enum:
            found.append((index + 1, ts_enum.group("name"), _members_ts_enum(lines, index)))
        elif union:
            found.append((index + 1, union.group("name"), _members_ts_union(lines, index)))
    return found


def has_table(text: str) -> bool:
    return bool(TABLE.search(text))


def added_lines(root: Path, base: str, path: str) -> set[int]:
    """Return the line numbers that the PR adds to a file."""
    run = _git(root, "diff", "-U0", f"{base}...HEAD", "--", path)
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip() or f"git diff {base}...HEAD failed")
    added: set[int] = set()
    for line in run.stdout.splitlines():
        match = HUNK.match(line)
        if match:
            start, count = int(match.group("start")), int(match.group("count") or 1)
            added.update(range(start, start + count))
    return added


def source_files(root: Path, base: str | None) -> list[str]:
    """Return the source files that the PR adds or changes, or each one if base is None."""
    if base is None:
        args = ["ls-files", "-z"]
    else:
        args = ["diff", "-z", "--name-only", "--diff-filter=AMR", f"{base}...HEAD"]
    run = _git(root, *args)
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip() or f"git {args[0]} failed")
    return sorted(path for path in run.stdout.split("\0") if is_source(path))


def _folder_has_table(root: Path, path: str, own_text: str) -> bool:
    """True if the file or a source file in the same folder names a transition table."""
    if has_table(own_text):
        return True
    folder = (root / path).parent
    siblings = [file for file in folder.iterdir() if file.is_file() and is_source(
        file.relative_to(root).as_posix())] if folder.is_dir() else []
    return any(has_table(file.read_text(encoding="utf-8", errors="replace")) for file in siblings)


def file_findings(root: Path, path: str, base: str | None) -> list[Finding]:
    file = root / path
    if not file.is_file():
        return []
    text = file.read_text(encoding="utf-8", errors="replace")
    new = added_lines(root, base, path) if base is not None else None
    types = [item for item in state_types(text)
             if item[2] >= MIN_STATES and (new is None or item[0] in new)]
    if not types or _folder_has_table(root, path, text):
        return []
    return [Finding(path, number, CHECK,
                    f"The state type '{name}' has {count} states and no transition table in this "
                    "file or its folder. Add one named table or function that lists each allowed "
                    "transition (for example 'TRANSITIONS'). Or add a 'Waiver (K25)' section to "
                    "the PR body.")
            for number, name, count in types]


def has_waiver(body: str) -> bool:
    """True if a heading with "waiver (K25)" has text under it."""
    lines = body.replace("\r\n", "\n").splitlines()
    found = evidence_check.headings(lines)
    return any(WAIVER in heading.name and not evidence_check.is_empty(
        evidence_check.section_body(lines, heading, found, set())) for heading in found)


def check(root: Path, base: str | None, body: str) -> list[Finding]:
    """Return a K25 finding for each state type with no table. A waiver makes each a warning."""
    findings = []
    for path in source_files(root, base):
        findings += file_findings(root, path, base)
    if has_waiver(body):
        findings = [Finding(f.path, f.line, f.check, f.message, "warning") for f in findings]
    return findings
