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

import yaml

from stone import eval_rates

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


# Cron names: mon=1 ... sat=6, sun=0. The rates file counts mon=0 ... sun=6.
DAY_NAMES = {name: (index + 1) % 7 for index, name in enumerate(eval_rates.WEEKDAYS)}
MONTH_NAMES = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def _cron_value(text: str, names: dict[str, int] | None) -> int:
    return names[text] if names and text in names else int(text)


def _cron_bounds(base: str, step: str, low: int, high: int,
                 names: dict[str, int] | None) -> tuple[int, int] | None:
    """Return the first and last value of a cron range, or None if the range is not plain cron."""
    if base == "*":
        return low, high
    first, _, last = base.partition("-")
    try:
        start = _cron_value(first, names)
        end = _cron_value(last, names) if last else (high if step else start)
    except ValueError:
        return None
    return (start, end) if low <= start <= end <= high else None


def _cron_item(item: str, low: int, high: int, names: dict[str, int] | None) -> range | None:
    """Return the values of one comma item of a cron field, or None if it is not plain cron."""
    base, _, step = item.partition("/")
    if step and (not step.isdigit() or int(step) < 1):
        return None
    bounds = _cron_bounds(base, step, low, high, names)
    return range(bounds[0], bounds[1] + 1, int(step) if step else 1) if bounds else None


def _cron_field(text: str, low: int, high: int, names: dict[str, int] | None = None) -> set[int] | None:
    """Return the values that one cron field gives, or None if the field is not plain cron."""
    found: set[int] = set()
    for item in text.lower().split(","):
        values = _cron_item(item, low, high, names)
        if values is None:
            return None
        found.update(values)
    return found


def fire_times(cron_line: str) -> set[tuple[int, int]] | None:
    """Return the (weekday, hour) pairs at which a cron line can fire, in UTC. Monday is 0.

    The day of the month and the month must be plain cron, but they do not narrow the result. So the
    result can have more pairs than the real fire times. A line that this function cannot read
    gives None.
    """
    fields = cron_line.split()
    if len(fields) != 5:
        return None
    hours = _cron_field(fields[1], 0, 23)
    days = _cron_field(fields[4], 0, 7, DAY_NAMES)
    others = (_cron_field(fields[0], 0, 59), _cron_field(fields[2], 1, 31),
              _cron_field(fields[3], 1, 12, MONTH_NAMES))
    if hours is None or days is None or None in others:
        return None
    # cron: 0 and 7 are Sunday, 1 is Monday. The rates file: 0 is Monday.
    weekdays = {(day - 1) % 7 for day in days}
    return {(day, hour) for day in weekdays for hour in hours}


def _peak_entry(model: str, rates: dict[str, Any] | None) -> dict[str, Any]:
    """Return the rates entry of a model, without its #variant suffix, or an empty mapping."""
    return ((rates or {}).get("models") or {}).get(model.partition("#")[0]) or {}


def peak_times(cron_line: str, model: str, rates: dict[str, Any] | None) -> list[str]:
    """Return the fire times of a cron line that are in a peak window of the model, as 'mon 06:00 UTC'."""
    windows = (_peak_entry(model, rates).get("peak") or {}).get("windows") or []
    times = fire_times(cron_line) or set()
    return [f"{eval_rates.WEEKDAYS[day]} {hour:02d}:00 UTC" for day, hour in sorted(times)
            if any(eval_rates.WEEKDAYS[day] in window["weekdays"] and hour in window["hours"]
                   for window in windows)]


def peak_notice(cron_line: str, model: str, rates: dict[str, Any] | None) -> str:
    """Return the text for the workflow comment: a warning, or the result of the peak check (item 8)."""
    if rates is None:
        return "Peak check: the adapter has no token rates, so render did not check the peak windows."
    if not _peak_entry(model, rates).get("peak"):
        return f"Peak check: the model {model} has no peak window in the rates file."
    if fire_times(cron_line) is None:
        return (f"Peak check: render cannot read the cron line '{cron_line}', so it did not check "
                f"the peak windows of {model}.")
    peaks = peak_times(cron_line, model, rates)
    if not peaks:
        return f"Peak check: no fire time of '{cron_line}' is in a peak window of {model}."
    shown = ", ".join(peaks[:3]) + (f", and {len(peaks) - 3} more" if len(peaks) > 3 else "")
    return (f"WARNING: the schedule '{cron_line}' can run in a peak window of {model} ({shown}). "
            "Peak runs cost more. Change the schedule, or the model.")


def load_rates(harness: Path) -> dict[str, Any] | None:
    """Return the token rates that the adapter names in its eval.yaml, or None if it has none."""
    try:
        run = yaml.safe_load((harness / "eval.yaml").read_text(encoding="utf-8")) or {}
        name = run.get("rates") if isinstance(run, dict) else None
        return eval_rates.load(eval_rates.path(harness / "eval.yaml", harness, name)) if name else None
    except (OSError, yaml.YAMLError, eval_rates.RatesError) as error:
        raise TriggerError(f"The peak check cannot read the token rates of the adapter: {error}") from None
