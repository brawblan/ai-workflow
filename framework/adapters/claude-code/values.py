"""Template values that belong to the Claude Code adapter."""

from __future__ import annotations

from typing import Any


def values(config: dict[str, Any]) -> dict[str, str]:
    """Return the shaper tools for the ticket source. File tickets also need file edits."""
    section = config.get("tickets")
    section = section if isinstance(section, dict) else {}
    file_ticket = section.get("source") == "file" and bool(section.get("path"))
    tools = ("Read, Grep, Glob, Bash, Write, Edit, StructuredOutput" if file_ticket
             else "Read, Grep, Glob, Bash, StructuredOutput")
    return {"shaper_tools": tools}
