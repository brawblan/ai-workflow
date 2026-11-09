"""Template values that belong to the OpenCode adapter."""

from __future__ import annotations

import json
from typing import Any


def values(config: dict[str, Any]) -> dict[str, str]:
    """Return the shaper permissions for the ticket source as inline JSON."""
    section = config.get("tickets")
    section = section if isinstance(section, dict) else {}
    file_ticket = section.get("source") == "file" and bool(section.get("path"))
    actions = ["read", "grep", "glob", "shell"]
    if file_ticket:
        actions.append("edit")
    rules = [{"action": "*", "resource": "*", "effect": "deny"}]
    rules += [{"action": action, "resource": "*", "effect": "allow"} for action in actions]
    return {"shaper_permissions": json.dumps(rules)}
