"""Small Markdown helpers. No Markdown library: the checks need line numbers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

LINK = re.compile(r"\]\(([^)\s]+)\)")
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}")


def split_frontmatter(text: str) -> tuple[dict[str, Any], int]:
    """Return the YAML frontmatter and the number of lines that it uses."""
    if not text.startswith("---\n"):
        return {}, 0
    end = text.find("\n---", 4)
    if end == -1:
        return {}, 0
    data = yaml.safe_load(text[4:end]) or {}
    return data, text[: end + 4].count("\n") + 1


def table_rows(text: str) -> list[list[str]]:
    """Return the cells of each table row, without the separator rows."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        if line.lstrip().startswith("|") and not TABLE_SEPARATOR.match(line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def relative_links(path: Path) -> list[tuple[int, str]]:
    """Return (line, target) for each relative link outside code blocks."""
    links: list[tuple[int, str]] = []
    in_code = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for match in LINK.finditer(line):
            target = match.group(1)
            if target.startswith(("http://", "https://", "#", "mailto:")) or "<" in target:
                continue
            links.append((number, target))
    return links
