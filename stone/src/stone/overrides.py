"""Profile overrides: `.cornerstone/profiles/<profile>.yaml` (layer 4, customization.md, #78)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FOLDER = Path(".cornerstone") / "profiles"
KEYS = ("extends", "mode", "drivers", "checks_add", "limits", "waivers")
LIMIT_KEYS = ("pr_changed_lines",)
DEFAULT_PR_LINES = 600  # D4, customization.md
DRIVERS = {"agent", "human", "pair", "checks"}
WAIVER_KINDS = ("gate", "check", "limit")
WAIVER_FIELDS = {"reason", "owner", "until"}
WAIVER_OPTIONAL = {"scope"}  # free text, for example patch-versions (D2)
WAIVABLE_GATES = {"G1", "G2", "G4"}  # no layer can remove G3 or G5 (gates.md)
# G3 always runs these, and K17 runs in each profile (writing.md). A waiver cannot remove them.
FIXED_CHECKS = ("K6", "K7", "K14", "K16", "K17")


@dataclass
class Override:
    """One override file. `data` is the parsed YAML; `error` is set if the file cannot be read."""
    path: Path
    profile: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def waivers(self) -> list[dict[str, Any]]:
        value = self.data.get("waivers") or []
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def load(root: Path) -> list[Override]:
    """Return the override files of the repo, in name order. A broken file has `error` set."""
    folder = root / FOLDER
    if not folder.is_dir():
        return []
    found: list[Override] = []
    for path in sorted(folder.glob("*.yaml")):
        override = Override(path, path.stem)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
            override.error = f"cannot read the file: {error}"
        else:
            if data is None:
                data = {}
            if isinstance(data, dict):
                override.data = data
            else:
                override.error = "the file must be a map"
        found.append(override)
    return found


def until(waiver: dict[str, Any]) -> dt.date | None:
    """Return the end date of a waiver, or None if it is not a date."""
    value = waiver.get("until")
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def active(waiver: dict[str, Any], today: dt.date) -> bool:
    """True if the waiver has a valid end date on or after today."""
    end = until(waiver)
    return end is not None and end >= today


def waived(override: Override, kind: str, today: dt.date) -> set[str]:
    """Return the gates, checks, or limits that an active waiver of the override covers."""
    return {str(waiver[kind]) for waiver in override.waivers()
            if kind in waiver and active(waiver, today)}


def base_limit(profile: dict[str, Any], repo_limit: Any, default: int) -> int:
    """Return the K7 limit before the override: the profile limit, or the repo limit if smaller."""
    own = (profile.get("limits") or {}).get("pr_changed_lines", default)
    return min(own, repo_limit) if isinstance(repo_limit, int) and repo_limit > 0 else own


def _waiver_problems(override: Override, profile: dict[str, Any] | None,
                     today: dt.date) -> list[str]:
    problems: list[str] = []
    raw = override.data.get("waivers")
    if raw is None:
        return problems
    if not isinstance(raw, list):
        return ["'waivers' must be a list."]
    checks = set(profile["checks"]) if profile else set()
    for number, waiver in enumerate(raw, 1):
        name = f"Waiver {number}"
        if not isinstance(waiver, dict):
            problems.append(f"{name} must be a map.")
            continue
        kinds = [kind for kind in WAIVER_KINDS if kind in waiver]
        if len(kinds) != 1:
            problems.append(f"{name} must have exactly one of gate, check, or limit.")
        unknown = sorted(set(waiver) - WAIVER_FIELDS - WAIVER_OPTIONAL - set(WAIVER_KINDS), key=str)
        if unknown:
            problems.append(f"{name} has the unknown key {unknown[0]!r}. Use gate, check, or "
                            "limit, and reason, owner, until, and scope.")
        for key in sorted(WAIVER_FIELDS - {"until"}):
            if not str(waiver.get(key) or "").strip():
                problems.append(f"{name} has no {key}. A waiver has a reason, an owner, and an "
                                "end date (rule 3).")
        end = until(waiver)
        if end is None:
            problems.append(f"{name} has no valid 'until' date. Use the form YYYY-MM-DD.")
        elif end < today:
            problems.append(f"{name} ended on {end.isoformat()}. Remove it, or set a new end "
                            "date with the owner.")
        gate, check, limit = waiver.get("gate"), waiver.get("check"), waiver.get("limit")
        if "gate" in waiver and gate not in WAIVABLE_GATES:
            problems.append(f"{name} removes {gate}. A waiver can remove only "
                            f"{', '.join(sorted(WAIVABLE_GATES))}. No waiver can remove G3 or G5.")
        if "check" in waiver:
            if check in FIXED_CHECKS:
                problems.append(f"{name} removes {check}. No waiver can remove "
                                f"{', '.join(FIXED_CHECKS)}.")
            elif profile and check not in checks:
                problems.append(f"{name} removes {check}, but the profile does not run it.")
        if "limit" in waiver and limit not in LIMIT_KEYS:
            problems.append(f"{name} loosens {limit!r}. Use one of {list(LIMIT_KEYS)}.")
    return problems


def problems(override: Override, config: dict[str, Any], profile: dict[str, Any] | None,
             check_ids: set[str], default_limit: int, today: dt.date) -> list[str]:
    """Return the problems of one override file. `profile` is the profile that it extends."""
    if override.error:
        return [f"The override {override.error}."]
    data = override.data
    found: list[str] = []
    for key in sorted(set(data) - set(KEYS), key=str):
        found.append(f"'{key}' is not a key. Use {', '.join(KEYS)}.")
    extends = data.get("extends")
    if extends != override.profile:
        found.append(f"'extends' must be '{override.profile}', the name of the file.")
    if override.profile not in (config.get("profiles") or []):
        found.append(f"The profile '{override.profile}' is not in 'profiles' of the repo config. "
                     "Add it, or remove the file.")
    if profile is None:
        return found + [f"The profile '{override.profile}' does not exist."]
    if "mode" in data and data["mode"] not in (config.get("modes_allowed") or []):
        found.append(f"The mode '{data['mode']}' is not in 'modes_allowed' of the repo config.")
    drivers = data.get("drivers")
    if drivers is not None and not isinstance(drivers, dict):
        found.append("'drivers' must be a map of a stage to a driver.")
    for stage, driver in (drivers.items() if isinstance(drivers, dict) else []):
        if stage not in profile["stages"]:
            found.append(f"The stage '{stage}' in 'drivers' is not a stage of the profile.")
        if driver not in DRIVERS or (driver == "checks") != (stage == "verify"):
            found.append(f"The driver '{driver}' of '{stage}' is not valid. Use agent, human, "
                         "or pair. Only verify uses checks.")
    added = data.get("checks_add")
    if added is not None and not isinstance(added, list):
        found.append("'checks_add' must be a list of check IDs.")
    for check in (added if isinstance(added, list) else []):
        if check not in check_ids:
            found.append(f"The check '{check}' in 'checks_add' is not in checks.md.")
    found += _limit_problems(override, config, profile, default_limit, today)
    return found + _waiver_problems(override, profile, today)


def _limit_problems(override: Override, config: dict[str, Any], profile: dict[str, Any],
                    default_limit: int, today: dt.date) -> list[str]:
    limits = override.data.get("limits")
    if limits is None:
        return []
    if not isinstance(limits, dict):
        return ["'limits' must be a map."]
    found = [f"'limits.{key}' is not a key. Use {', '.join(LIMIT_KEYS)}."
             for key in sorted(set(limits) - set(LIMIT_KEYS), key=str)]
    value = limits.get("pr_changed_lines")
    if value is None:
        return found
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return found + ["'limits.pr_changed_lines' must be a whole number above 0."]
    repo = (config.get("limits") or {}).get("pr_changed_lines")
    base = base_limit(profile, repo, default_limit)
    if value > base and "pr_changed_lines" not in waived(override, "limit", today):
        found.append(f"'limits.pr_changed_lines' is {value}, more than the limit {base}. A looser "
                     "limit needs an active waiver with 'limit: pr_changed_lines' (rule 3).")
    return found
