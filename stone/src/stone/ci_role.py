"""A read-only CI copy of a role file, for the trigger workflows (D119).

A trigger job runs a role on event text that anyone can write. The harness process of that job holds
the plan key in its environment. A role with the shell can read that environment (D39). So the job
runs a copy of the role file with fixed read-only permissions, and not the role file itself.

The component list of an adapter sets `ci_role`:

- `target`: the path of the copy. It must hold `$role`.
- `steps`: the step cap of the copy (D38).
- `permissions`: the whole rule list of the copy. The first rule denies all actions.
- `forbidden`: the actions that no rule of the copy may allow.
- `note`: text for the end of the role body. It tells the role about the limits.
"""

from __future__ import annotations

import copy
from pathlib import PurePosixPath
from typing import Any

import yaml

from stone.markdown import split_frontmatter
from stone.triggers import TriggerError

DENY_ALL = {"action": "*", "resource": "*", "effect": "deny"}


class _Dumper(yaml.SafeDumper):
    """Indent a list under its key, as the role templates do."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)


def settings(registry_doc: dict[str, Any]) -> dict[str, Any] | None:
    """Return the checked `ci_role` settings of an adapter, or None if it has none."""
    value = registry_doc.get("ci_role")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TriggerError("ci_role in the component list must be a mapping.")
    target = value.get("target")
    if not isinstance(target, str) or "$role" not in target:
        raise TriggerError("ci_role.target must be a path that holds '$role'.")
    steps = value.get("steps")
    if not isinstance(steps, int) or isinstance(steps, bool) or steps < 1:
        raise TriggerError("ci_role.steps must be a whole number of 1 or more.")
    rules = value.get("permissions")
    if not isinstance(rules, list) or not all(
            isinstance(rule, dict) and {"action", "resource", "effect"} <= rule.keys()
            for rule in rules):
        raise TriggerError("ci_role.permissions must be a list of rules with action, resource, "
                           "and effect.")
    forbidden = value.get("forbidden")
    if not isinstance(forbidden, list) or not forbidden:
        raise TriggerError("ci_role.forbidden must be a list of actions.")
    return value


def agent_id(config: dict[str, Any], role: str) -> str:
    """Return the agent ID of the CI copy: the file name of the target, without its suffix."""
    return PurePosixPath(config["target"].replace("$role", role)).stem


def check_permissions(rules: list[dict[str, Any]], forbidden: list[str], role: str) -> None:
    """Refuse a rule list that gives the CI role a forbidden action, or that does not deny all first."""
    if not rules or {key: rules[0].get(key) for key in DENY_ALL} != DENY_ALL:
        raise TriggerError(f"The CI copy of the {role} must start with a rule that denies all "
                           "actions. Fix ci_role.permissions in the component list.")
    for rule in rules[1:]:
        action = rule.get("action")
        if rule.get("effect") != "deny" and (action in forbidden or action == "*"):
            raise TriggerError(
                f"The CI copy of the {role} would allow the action '{action}'. A CI role with "
                f"'{action}' can read the plan key or change the repo. Remove the rule from "
                "ci_role.permissions in the component list.")


def derive(config: dict[str, Any], role: str, text: str) -> tuple[str, str]:
    """Return the target path and the text of the CI copy of a rendered role file."""
    rules = copy.deepcopy(config["permissions"])
    check_permissions(rules, [str(item) for item in config["forbidden"]], role)
    front, lines = split_frontmatter(text)
    if not front:
        raise TriggerError(f"The role file of the {role} has no frontmatter, so render cannot "
                           "make its CI copy.")
    body = "".join(text.splitlines(keepends=True)[lines:])
    front["description"] = f"Read-only CI copy of the role. {front.get('description', '')}".strip()
    front["steps"] = config["steps"]
    front["permissions"] = rules
    head = yaml.dump(front, Dumper=_Dumper, sort_keys=False, width=10_000, allow_unicode=True,
                     default_flow_style=False)
    note = str(config.get("note") or "").strip()
    tail = f"\n## CI run\n\n{note}\n" if note else ""
    body = body if body.endswith("\n") else body + "\n"
    return config["target"].replace("$role", role), f"---\n{head}---\n{body}{tail}"
