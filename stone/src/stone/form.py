"""The text form of the generated files (#224).

`stone render` writes YAML and Markdown that a formatter with its default options accepts, so a
repo check such as `prettier --check .` passes on them. The drift check ignores a change of form
only, so a format on save does not cause drift.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

import yaml

SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


class _Dumper(yaml.SafeDumper):
    """Indent each list under its key. A value that needs quotes gets '"', or "'" if it has a '"'."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)

    def choose_scalar_style(self) -> str:
        style = super().choose_scalar_style()
        value = self.event.value
        if style == "'" and '"' not in value:
            return '"'
        return style


def dump_yaml(data: Any) -> str:
    """Return YAML text with no line folds: a long value stays on one line."""
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1 << 30)


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def table(rows: list[list[str]]) -> list[str]:
    """Return the lines of a Markdown table. The first row is the header. Each column is aligned."""
    widths = [max(3, *(_width(row[column]) for row in rows)) for column in range(len(rows[0]))]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cell + " " * (width - _width(cell))
                                 for cell, width in zip(cells, widths)) + " |"
    return [line(rows[0]), line(["-" * width for width in widths]), *map(line, rows[1:])]


def _typed(data: Any) -> Any:
    """Return the data with the type of each value, so that 0 and false are not equal."""
    if isinstance(data, dict):
        return {key: _typed(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_typed(value) for value in data]
    return (type(data).__name__, data)


def _markdown_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        indent = raw[:len(raw) - len(raw.lstrip())]
        line = indent + " ".join(raw.split())
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            line = "|".join("---" if SEPARATOR_CELL.match(cell) else cell for cell in cells)
        if line:
            lines.append(line)
    return lines


def same_form(path: str, first: str, second: str) -> bool:
    """Return True if the two texts of a file differ in form only (whitespace, quotes, indent)."""
    if first == second:
        return True
    try:
        if path.endswith((".yaml", ".yml")):
            return _typed(yaml.safe_load(first)) == _typed(yaml.safe_load(second))
        if path.endswith(".json"):
            return _typed(json.loads(first)) == _typed(json.loads(second))
    except (yaml.YAMLError, ValueError):
        return False
    if path.endswith(".md"):
        return _markdown_lines(first) == _markdown_lines(second)
    return False
