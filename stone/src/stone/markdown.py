"""Small Markdown helpers. No Markdown library: the checks need line numbers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml

# A link target is plain (no space) or in the CommonMark form <...>, which can hold spaces.
LINK = re.compile(r"\]\((?:<([^<>]+)>|([^)\s]+))\)")
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


def link_file(target: str) -> str:
    """Return the file part of a link target: no fragment, and no percent-encoding."""
    return unquote(target.split("#", 1)[0])


def relative_links(path: Path) -> list[tuple[int, str]]:
    """Return (line, target) for each relative link outside code blocks.

    The target is as written, without the <...> of the CommonMark form.
    """
    links: list[tuple[int, str]] = []
    in_code = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for match in LINK.finditer(line):
            target = match.group(1) or match.group(2)
            if target.startswith(("http://", "https://", "//", "#", "mailto:")) or "<" in target:
                continue
            links.append((number, target))
    return links


@dataclass
class Block:
    """A paragraph, a list item, or a table cell, with its line numbers."""

    kind: str  # "paragraph" | "procedure" | "list" | "table"
    start: int
    text: str = ""
    lines: list[int] = field(default_factory=list)  # line number of each character group
    offsets: list[int] = field(default_factory=list)

    def add(self, line_number: int, text: str) -> None:
        if self.text:
            self.text += " "
        self.offsets.append(len(self.text))
        self.lines.append(line_number)
        self.text += text

    def line_at(self, offset: int) -> int:
        result = self.start
        for start, line in zip(self.offsets, self.lines):
            if start <= offset:
                result = line
        return result


NUMBERED = re.compile(r"^\s*\d+\.\s+")
BULLET = re.compile(r"^\s*[-*+]\s+")
INLINE_CODE = re.compile(r"`[^`]*`")
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
URL = re.compile(r"https?://\S+")
QUOTE = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”")
HTML_COMMENT = re.compile(r"<!--.*?-->")


def clean(text: str) -> str:
    """Remove the parts that the writing rules do not apply to."""
    text = HTML_COMMENT.sub("", text)
    text = INLINE_CODE.sub("CODE", text)
    text = MD_LINK.sub(r"\1", text)
    text = URL.sub("URL", text)
    text = QUOTE.sub("QUOTE", text)  # quotes are out of scope (writing.md)
    return text.replace("**", "").replace("__", "")


def prose_blocks(text: str, ignore_marker: str = "<!-- ste-ignore -->") -> list[Block]:
    """Split Markdown into prose blocks. Skip frontmatter, code, headings, and ignored lines."""
    _, skip = split_frontmatter(text)
    blocks: list[Block] = []
    current: Block | None = None
    in_code = False

    def close() -> None:
        nonlocal current
        if current and current.text.strip():
            blocks.append(current)
        current = None

    for number, raw in enumerate(text.splitlines(), 1):
        if number <= skip:
            continue
        stripped = raw.strip()
        if stripped.startswith("```"):
            close()
            in_code = not in_code
            continue
        if in_code or ignore_marker in raw:
            close()
            continue
        if not stripped or stripped.startswith("#") or stripped.startswith("<!--"):
            close()
            continue
        if stripped.startswith("|"):
            close()
            if TABLE_SEPARATOR.match(stripped):
                continue
            for cell in stripped.strip("|").split("|"):
                if cell.strip():
                    block = Block("table", number)
                    block.add(number, clean(cell.strip()))
                    blocks.append(block)
            continue
        body = stripped.lstrip("> ").strip()
        if NUMBERED.match(raw) or BULLET.match(raw):
            close()
            kind = "procedure" if NUMBERED.match(raw) else "list"
            current = Block(kind, number)
            body = NUMBERED.sub("", BULLET.sub("", body))
        elif current is None:
            current = Block("paragraph", number)
        current.add(number, clean(body))
    close()
    return blocks
