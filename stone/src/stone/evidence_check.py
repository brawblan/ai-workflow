"""K14: fail if a required PR section is missing or empty (framework/checks.md, P11)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from stone.findings import Finding

CHECK = "K14"
DEFAULT_SECTIONS = ["Evidence", "Decision log", "Review findings", "Confidence"]
PLACEHOLDERS = {"todo", "tbd", "none", "n/a", "na", "-", "...", "…"}
ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
BOLD_HEADING = re.compile(r"^\s*(?:\*\*|__)([^*_]+?)(?:\*\*|__)\s*:?\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
COMMENT = re.compile(r"<!--.*?-->", re.S)
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}")
LIST_MARKER = re.compile(r"^(?:[-*+]|\d+[.)])(?:\s+|$)")
BOLD_LEVEL = 7  # a bold line is a heading below each ATX level


@dataclass(frozen=True)
class Heading:
    line: int  # 1-based
    level: int
    name: str


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().strip("*_").rstrip(":").strip()).lower()


def headings(lines: list[str]) -> list[Heading]:
    """Return the ATX headings and the bold-only lines, outside fenced code blocks."""
    found: list[Heading] = []
    fence: str | None = None
    for number, line in enumerate(lines, 1):
        marker = FENCE.match(line)
        if marker:
            fence = None if fence == marker.group(1) else fence or marker.group(1)
            continue
        if fence:
            continue
        atx = ATX_HEADING.match(line)
        if atx:
            found.append(Heading(number, len(atx.group(1)), _normalize(atx.group(2))))
            continue
        bold = BOLD_HEADING.match(line)
        if bold:
            found.append(Heading(number, BOLD_LEVEL, _normalize(bold.group(1))))
    return found


def section_body(lines: list[str], heading: Heading, all_headings: list[Heading],
                 required: set[str]) -> str:
    """Return the text from the heading to the next heading of the same or a higher level,
    or to the next required section heading of any level or style."""
    end = len(lines)
    for other in all_headings:
        if other.line > heading.line and (other.level <= heading.level or other.name in required):
            end = other.line - 1
            break
    return "\n".join(lines[heading.line:end])


def is_empty(body: str) -> bool:
    """True if the body has no text, or only a placeholder, after comments and table headers."""
    rows = [LIST_MARKER.sub("", row.strip()) for row in COMMENT.sub("", body).splitlines()]
    rows = [row for row in rows if row]
    kept: list[str] = []
    for index, row in enumerate(rows):
        if TABLE_SEPARATOR.match(row):
            continue
        following = rows[index + 1] if index + 1 < len(rows) else ""
        if "|" in row and TABLE_SEPARATOR.match(following):
            continue  # a table header row is not content
        kept.append(row)
    text = " ".join(kept).strip()
    return not text or text.strip("*_`.: ").lower() in PLACEHOLDERS | {""}


def check_text(text: str, path: str, sections: list[str] | None = None) -> list[Finding]:
    """Return a K14 finding for each required section that is missing or empty."""
    lines = text.splitlines()
    found = headings(lines)
    sections = sections or DEFAULT_SECTIONS
    required = {_normalize(section) for section in sections}
    findings: list[Finding] = []
    for section in sections:
        matches = [h for h in found if h.name == _normalize(section)]
        if not matches:
            findings.append(Finding(path, 1, CHECK,
                                    f"The PR body has no '{section}' section. Add a heading "
                                    f"'## {section}' and fill it. If it does not apply, write "
                                    "'None' and the reason."))
            continue
        if all(is_empty(section_body(lines, h, found, required)) for h in matches):
            findings.append(Finding(path, matches[0].line, CHECK,
                                    f"The '{section}' section is empty or has only a "
                                    "placeholder. Fill it. If it does not apply, write 'None' "
                                    "and the reason."))
    return findings
