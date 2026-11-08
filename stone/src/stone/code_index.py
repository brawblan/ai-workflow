"""The `code_index` key: the code index rule, permission, and build hook that render adds (D111)."""
from __future__ import annotations

import re
from typing import Any

DEFAULT = {
    "command": "stone-index",
    "rule": ("- If `stone-index` is on PATH, ask the code index before you search or read code. "
             "Then read only the lines that it gives.\n"
             "- Use `stone-index find <name>`, `stone-index refs <path or module>`, "
             "`stone-index outline <path>`, or `stone-index search \"<words>\"`."),
    "build": "stone-index build",
}
MAX_RULE_LINES = 3  # P4: the rule goes in each role file that reads code
COMMAND = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
FORMS = ("Use stone-index, none, or a map with command, rule, and optional build.")


def settings(config: dict[str, Any]) -> dict[str, str] | None:
    """Return the command, rule, and build of the index, or None if the repo opts out."""
    value = config.get("code_index", "stone-index")
    if value == "none":
        return None
    if not isinstance(value, dict):
        return dict(DEFAULT)
    command = str(value["command"])
    return {"command": command, "rule": str(value["rule"]).strip(),
            "build": str(value.get("build") or f"{command} build")}


def _guard(command: str) -> str:
    return f"If `{command}` is on PATH"


def problems(config: dict[str, Any]) -> list[str]:
    """Return the problems of the `code_index` value."""
    value = config.get("code_index", "stone-index")
    if value in ("stone-index", "none"):
        return []
    if not isinstance(value, dict) or set(value) - {"command", "rule", "build"} \
            or not {"command", "rule"} <= set(value):
        return [f"The code_index value is not valid. {FORMS}"]
    found = []
    command, rule, build = value["command"], value["rule"], value.get("build", "")
    if not isinstance(command, str) or not COMMAND.fullmatch(command):
        found.append("code_index.command is not valid. Use one command name with no spaces "
                     "and no shell characters.")
    lines = rule.strip().splitlines() if isinstance(rule, str) else []
    if not lines or len(lines) > MAX_RULE_LINES:
        found.append(f"code_index.rule is not valid. Use 1 to {MAX_RULE_LINES} lines (P4).")
    elif isinstance(command, str) and not lines[0].lstrip("-* ").startswith(_guard(command)):
        found.append(f"code_index.rule must start with the guard \"{_guard(command)}\".")
    if not isinstance(build, str) or "\n" in build:
        found.append("code_index.build is not valid. Use one command line.")
    return found


def role_block(config: dict[str, Any]) -> str:
    """Return the rule section of a role file that reads code, or "" if the repo opts out."""
    index = settings(config)
    return f"## Code index\n\n{index['rule']}\n" if index else ""
