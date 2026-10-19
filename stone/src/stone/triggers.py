"""Trigger workflows: one CI workflow for each profile trigger that is not `command` (D31).

The adapter has one component entry with a `trigger` field for each trigger type that it supports.
Render makes one component from that entry for each selected profile with that trigger type.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEDULES = {"daily": "0 6 * * *", "weekly": "0 6 * * 1", "monthly": "0 6 1 * *"}
CRON = re.compile(r"^[0-9A-Za-z*/,-]+( [0-9A-Za-z*/,-]+){4}$")
LABEL = re.compile(r"^[A-Za-z0-9._:/-]+$")
EXPRESSION = "${{"  # the CI starts an expression here, also in a prompt
# A Markdown link with a relative target. A target with a scheme (https:) or a # is kept.
RELATIVE_LINK = re.compile(r"\[([^\]]+)\]\((?![A-Za-z][A-Za-z0-9+.-]*:|#|/)[^)]*\)")
# The shaper interviews a human in a session. A label run has no human (D41).
READINESS_CHECK = """\
The label asks for a readiness check. No human is in this job, so nobody can answer a question.
1. Read the ticket in the event data.
2. Check the ticket against the Definition of Ready fields of your role.
3. Do not interview anyone. Do not ask a question. Do not start another role.
4. In the `report`, list each missing field, one on each line.
5. If no field is missing, write in the `report` that the ticket is ready."""


class TriggerError(Exception):
    """A profile trigger is not valid for render."""


@dataclass
class Trigger:
    profile: dict[str, Any]
    text: str  # as in the profile, for example "label:agent-ready"
    key: str  # label | schedule | ci:<event>: the `trigger` field of the adapter entry
    value: str


def parse(text: str) -> tuple[str, str]:
    """Return the trigger type and its value: "ci:issue-opened" -> ("ci:issue-opened", ...)."""
    if text.startswith("ci:"):
        return text, text[3:]
    key, _, value = text.partition(":")
    return key, value


def profile_triggers(profiles: list[dict[str, Any]]) -> list[Trigger]:
    """Return each trigger of the selected profiles that is not `command`."""
    found = []
    for profile in profiles:
        for text in profile.get("triggers", []):
            key, value = parse(str(text))
            if key != "command":
                found.append(Trigger(profile, str(text), key, value))
    return found


def supported(triggers: list[Trigger], keys: set[str]) -> list[Trigger]:
    """Return the triggers that the adapter has a template for. Log the others."""
    kept = []
    for trigger in triggers:
        if trigger.key in keys:
            kept.append(trigger)
        else:
            print(f"skipped trigger {trigger.text} of profile {trigger.profile['id']}: "
                  "the adapter has no template for it", file=sys.stderr)
    return kept


def cron(value: str) -> str:
    if value in SCHEDULES:
        return SCHEDULES[value]
    if CRON.match(value):
        return value
    raise TriggerError(f"'schedule:{value}' is not daily, weekly, monthly, or a cron line "
                       "with 5 fields. Fix the profile trigger.")


def flow_steps(framework: Path, profile_id: str) -> str:
    """Return the text of the "## Flow" section of a profile: the steps and any notes."""
    text = (framework / "profiles" / f"{profile_id}.md").read_text(encoding="utf-8")
    match = re.search(r"^## Flow\n(.*?)(?=^## )", text, re.M | re.S)
    if not match:
        raise TriggerError(f"The profile {profile_id} has no '## Flow' section. Add it.")
    steps = RELATIVE_LINK.sub(r"\1", match.group(1).strip())
    if EXPRESSION in steps:
        raise TriggerError(f"The flow of {profile_id} has '{EXPRESSION}'. The CI reads it as an "
                           "expression. Remove it.")
    return steps


def prompt_steps(framework: Path, trigger: Trigger) -> str:
    """Return the steps for the prompt. A label run of the shaper only reports (D41)."""
    if trigger.key == "label" and trigger.profile["roles"][0] == "shaper":
        return READINESS_CHECK
    return flow_steps(framework, trigger.profile["id"])


def values(trigger: Trigger, triggers: list[Trigger],
           role_models: dict[str, str]) -> dict[str, str]:
    """Return the template values for one trigger workflow."""
    profile = trigger.profile
    role = profile["roles"][0]
    result = {"profile": profile["id"], "profile_name": profile["name"], "role": role,
              "model": role_models.get(role, ""), "trigger": trigger.text,
              "trigger_label": "", "select_label": "", "cron": ""}
    if trigger.key == "label":
        if not LABEL.match(trigger.value):
            raise TriggerError(f"The label in '{trigger.text}' of {profile['id']} is not valid. "
                               "Use letters, digits, and . _ : / - only.")
        shared = [other for other in triggers
                  if other.key == "label" and other.value == trigger.value]
        result["trigger_label"] = trigger.value
        # A shared label needs a second label that selects the profile. Else the label itself.
        result["select_label"] = f"profile:{profile['id']}" if len(shared) > 1 else trigger.value
    if trigger.key == "schedule":
        result["cron"] = cron(trigger.value)
    return result


def insert_block(template: str, name: str, block: str) -> str:
    """Replace each line that holds only `$name` with the block, at the indent of that line."""
    def indent(match: re.Match[str]) -> str:
        return "\n".join(match.group(1) + line if line else ""
                         for line in block.rstrip("\n").splitlines())
    return re.sub(rf"^([ \t]*)\${name}[ \t]*$", indent, template, flags=re.M)


def check_targets(targets: list[tuple[str, str]]) -> None:
    """Fail if two triggers write the same file, for example two labels in one profile."""
    seen: dict[str, str] = {}
    for trigger_text, target in targets:
        if target in seen:
            raise TriggerError(f"The triggers {seen[target]} and {trigger_text} write the same "
                               f"file {target}. Keep one trigger of each type in a profile.")
        seen[target] = trigger_text
