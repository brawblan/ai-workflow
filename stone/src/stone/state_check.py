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
# A line that defines a name for the allowed moves: a table, a map, or a function. A call, a CSS
# "transition:" property, and a hook such as useTransition do not count.
TABLE = re.compile(
    r"(?im)^\s*(?:(?:export|const|let|var|def|function|async|static|readonly|private|public)\s+)*"
    r"(?P<name>\w*(?:transition|next_?states?|allowed_?(?:next|moves))\w*)\s*[:=(<]")
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


def _members_py(lines: list[str], index: int, indent: str) -> tuple[int, int]:
    """Return (member count, last line index). Only the first member indent counts."""
    count, end, member_indent = 0, index, None
    for number in range(index + 1, len(lines)):
        line = lines[number]
        if line.strip() and not line.startswith((indent + " ", indent + "\t")):
            break
        found = MEMBER.match(line)
        if found and member_indent in (None, len(line) - len(line.lstrip())):
            member_indent = len(line) - len(line.lstrip())
            count, end = count + 1, number
    return count, end


def _members_ts_enum(lines: list[str], index: int) -> tuple[int, int]:
    body = "\n".join(lines[index:index + 200])
    body = re.sub(r"//[^\n]*|/\*.*?\*/", "", body, flags=re.DOTALL)
    start, end = body.find("{"), body.find("}")
    if start < 0 or end < start:
        return 0, index
    items = [item for item in body[start + 1:end].split(",") if item.strip()]
    return len(items), index + body[:end].count("\n")


def _members_ts_union(lines: list[str], index: int) -> tuple[int, int]:
    """Count the string literals of a union. An object type or the next statement does not count."""
    body, end = [lines[index].split("=", 1)[1]], index
    if body[0].strip().startswith("{"):
        return 0, index
    for number in range(index + 1, min(index + 30, len(lines))):
        if ";" in body[-1] or not (lines[number].lstrip().startswith("|") or body[-1].rstrip().endswith("|") or not body[-1].strip()):
            break
        body.append(lines[number])
        end = number
    return len(LITERAL.findall("\n".join(body))), end


def state_types(text: str) -> list[tuple[int, int, str, int]]:
    """Return (first line, last line, name, member count) for each state type in the text."""
    lines = text.splitlines()
    found = []
    for index, line in enumerate(lines):
        py, ts_enum, union = PY_ENUM.match(line), TS_ENUM.match(line), TS_UNION.match(line)
        if py:
            count, end = _members_py(lines, index, py.group("indent"))
            found.append((index + 1, end + 1, py.group("name"), count))
        elif ts_enum:
            count, end = _members_ts_enum(lines, index)
            found.append((index + 1, end + 1, ts_enum.group("name"), count))
        elif union:
            count, end = _members_ts_union(lines, index)
            found.append((index + 1, end + 1, union.group("name"), count))
    return found


def has_table(text: str) -> bool:
    return any(not found.group("name").lower().startswith(("use", "start")) and found.group("name").lower() != "transition"
               for found in TABLE.finditer(text))


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
    types = [(first, name, count) for first, last, name, count in state_types(text)
             if count >= MIN_STATES and (new is None or new.intersection(range(first, last + 1)))]
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
