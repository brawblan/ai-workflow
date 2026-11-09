"""The `limits.session_context_tokens` key: the context guard hook that render adds (D115)."""
from __future__ import annotations

from typing import Any

DEFAULT = 150000  # the framework limit. A repo can only tighten it, or turn the guard off with 0.


def limit(config: dict[str, Any]) -> int:
    """Return the token limit of the guard. 0 means the guard is off."""
    value = (config.get("limits") or {}).get("session_context_tokens")
    return DEFAULT if value is None else value


def problems(config: dict[str, Any]) -> list[str]:
    """Return the problems of the `limits.session_context_tokens` value."""
    value = (config.get("limits") or {}).get("session_context_tokens")
    if value is None:
        return []
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return ["limits.session_context_tokens must be 0 or a whole number above 0."]
    if value > DEFAULT:
        return [f"limits.session_context_tokens is {value}, more than the limit {DEFAULT}. "
                "A later layer can only tighten it. Use 0 to turn the guard off."]
    return []


def off_ids(registry: list[dict[str, Any]], config: dict[str, Any]) -> set[str]:
    """Return the ids of the components that a limit of 0 turns off."""
    return {entry["id"] for entry in registry
            if entry.get("needs_context_guard") and not limit(config)}
