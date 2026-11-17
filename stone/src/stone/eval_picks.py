"""An economy pick and a quality pick of a model for each role (#305, D120).

The rule reads the model matrix of `stone eval --summary ... --by model`. It does not change the
role models of a profile. A human changes `defaults.role_models` at G4, in a PR of its own.

- Economy: the lowest cost for each passing run. A model counts only if its pass rate is not lower
  than the baseline by more than 1 standard error of the difference.
- Quality: the highest pass rate, among the models whose cost for each passing run is not higher
  than the limit. The limit is the optional `quality_cost_ceiling` of the model profile (D125). If
  the profile has no ceiling, the limit is the cost of the baseline. If two are equal, the lower
  cost wins.

The baseline of a role is its role model in the model profile. If no model meets a rule, the pick
is the baseline. A pick needs 3 trials or more for each scenario of the baseline and of the pick.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import eval_matrix, eval_metrics

MIN_TRIALS = 3
ROLE_PREFIX = "role."
KINDS = ("economy", "quality")
CEILING_KEY = "quality_cost_ceiling"
PICK_KEYS = ("model", "pass_rate", "cost_per_pass", "trials", "eval_version", "date", "review")
EPSILON = 1e-9  # a pass rate or a cost that differs by less is equal


class PicksError(Exception):
    """The model profile for the baseline cannot be read."""


@dataclass
class Candidate:
    """One model of one role, with the numbers that the two rules use."""

    model: str
    pass_rate: float
    error: float  # the standard error of the pass rate
    cost: float | None  # the cost for each passing run
    trials: int  # the fewest runs of one scenario
    baseline: bool = False
    scenarios: dict[str, int] | None = None  # the runs of each scenario


# The baseline ------------------------------------------------------------------------------


def load_baselines(path: Path) -> tuple[str, dict[str, str]]:
    """Return the harness and the role models of a model profile file."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise PicksError(f"cannot read the model profile {path} ({error}).") from None
    roles = _role_models(data)
    if not roles:
        raise PicksError(f"{path} has no defaults.role_models.")
    return str(data.get("harness") or ""), {str(k): str(v) for k, v in roles.items() if v}


def load_ceiling(path: Path) -> float | None:
    """The `quality_cost_ceiling` of a model profile file, or None if it has none (D125)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise PicksError(f"cannot read the model profile {path} ({error}).") from None
    value = data.get(CEILING_KEY) if isinstance(data, dict) else None
    if value is None:
        return None
    if not (_number(value) and value >= 0):
        raise PicksError(f"{path}: {CEILING_KEY} must be a number of 0 or more.")
    return float(value)


def _role_models(data: Any) -> dict[str, Any]:
    """The `defaults.role_models` of a loaded model profile, or an empty mapping."""
    defaults = data.get("defaults") if isinstance(data, dict) else None
    roles = defaults.get("role_models") if isinstance(defaults, dict) else None
    return roles if isinstance(roles, dict) else {}


# The two rules -----------------------------------------------------------------------------


def _cost(candidate: Candidate) -> float:
    return math.inf if candidate.cost is None else candidate.cost


def economy(candidates: list[Candidate], base: Candidate) -> Candidate:
    """The lowest cost among the models whose pass rate is near the baseline."""
    near = [c for c in candidates if c.cost is not None
            and c.pass_rate >= base.pass_rate - math.hypot(c.error, base.error) - EPSILON]
    return min(near, key=lambda c: (_cost(c), -c.pass_rate, c.model), default=base)


def quality(candidates: list[Candidate], base: Candidate, ceiling: float | None = None) -> Candidate:
    """The highest pass rate among the models that cost no more than the limit. The limit is the
    ceiling, if there is one, and if not, the cost of the baseline."""
    if ceiling is not None:
        cheap = [c for c in candidates if c.cost is not None and c.cost <= ceiling + EPSILON]
        return min(cheap, key=lambda c: (-round(c.pass_rate, 9), _cost(c), c.model), default=base)
    # A baseline that passes no run costs "infinity" for each passing run. A baseline with no rate
    # has an unknown cost, so no other model can be compared with it.
    limit = math.inf if base.cost is None and base.pass_rate == 0 else base.cost
    if limit is None:
        return base
    cheap = [c for c in candidates if c.cost is not None and c.cost <= limit + EPSILON]
    return min(cheap, key=lambda c: (-round(c.pass_rate, 9), _cost(c), c.model), default=base)


# The matrix --------------------------------------------------------------------------------


def scenario_counts(runs: list[Any]) -> dict[tuple[str, str], dict[str, int]]:
    """The runs of each scenario, for each component and model. The base variant is left out."""
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for run in runs:
        if run.variant not in eval_metrics.BASE_NAMES:
            key = (getattr(run, "component", "") or "unknown", eval_matrix.model_label(run))
            found = counts.setdefault(key, {})
            found[run.scenario] = found.get(run.scenario, 0) + 1
    return counts


def trial_counts(runs: list[Any]) -> dict[tuple[str, str], int]:
    """The fewest runs of one scenario, for each component and model."""
    return {key: min(found.values()) for key, found in scenario_counts(runs).items()}


def _candidate(row: dict[str, Any], trials: int) -> Candidate:
    rate = row["pass_rate"] or {"mean": 0.0, "se": None}
    return Candidate(row["model"], rate["mean"], rate["se"] or 0.0, row["cost_per_pass"], trials)


def _in_harness(model: str, harness: str) -> bool:
    """A model of another harness cannot go in the role models of this profile. An old run has no
    harness in its label, so it stays."""
    return not harness or ":" not in model or model.startswith(f"{harness}:")


def _is_baseline(model: str, harness: str, baseline: str) -> bool:
    return model in (baseline, f"{harness}:{baseline}")


def _entry(candidate: Candidate) -> dict[str, Any]:
    return {"model": candidate.model, "pass_rate": candidate.pass_rate,
            "cost_per_pass": candidate.cost, "trials": candidate.trials,
            "baseline": candidate.baseline}


def _count_baseline_scenarios(base: Candidate, found: list[Candidate]) -> None:
    """Count the trials of each model on the scenarios of the baseline. A scenario that a model
    did not run counts 0, so the pass rates of all models come from the same scenarios."""
    for candidate in found:
        if base.scenarios and candidate.scenarios is not None:
            candidate.trials = min(candidate.scenarios.get(s, 0) for s in base.scenarios)


def _role_entry(role: str, baseline: str, found: list[Candidate],
                ceiling: float | None = None) -> dict[str, Any]:
    """The picks of one role. `found` holds each model that has rows for the role."""
    entry: dict[str, Any] = {"role": role, "baseline": baseline, "economy": None, "quality": None,
                             "skipped": [], "reason": ""}
    base = next((c for c in found if c.baseline), None)
    if base is None:
        entry["reason"] = f"no run of the baseline model {baseline}."
    elif base.trials < MIN_TRIALS:
        entry["reason"] = (f"the baseline has {base.trials} trial(s) for a scenario. "
                           f"A pick needs {MIN_TRIALS} or more.")
    else:
        _count_baseline_scenarios(base, found)
        enough = [c for c in found if c.trials >= MIN_TRIALS]
        entry["skipped"] = [c.model for c in found if c.trials < MIN_TRIALS]
        entry["economy"], entry["quality"] = (_entry(economy(enough, base)),
                                              _entry(quality(enough, base, ceiling)))
    return entry


def picks(runs: list[Any], harness: str, baselines: dict[str, str],
          ceiling: float | None = None) -> list[dict[str, Any]]:
    """One entry for each role that the runs cover: its baseline, its two picks, and a reason if
    the entry has no pick. `baselines` maps each role to its role model in the model profile."""
    counts = scenario_counts(runs)
    roles: dict[str, list[Candidate]] = {}
    for row in eval_matrix.rows(runs):
        if not row["component"].startswith(ROLE_PREFIX):
            continue
        role = row["component"][len(ROLE_PREFIX):]
        roles.setdefault(role, [])
        if _in_harness(row["model"], harness):
            found = counts.get((row["component"], row["model"]), {})
            candidate = _candidate(row, min(found.values(), default=0))
            candidate.scenarios = found
            candidate.baseline = _is_baseline(row["model"], harness, baselines.get(role, ""))
            roles[role].append(candidate)
    return [_role_entry(role, baselines[role], found, ceiling) if role in baselines
            else {"role": role, "baseline": "", "economy": None, "quality": None, "skipped": [],
                  "reason": "the model profile has no role model for this role."}
            for role, found in roles.items()]


# The output --------------------------------------------------------------------------------


def marks(found: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    """The text of the Pick column of the matrix table, for each component and model."""
    words: dict[tuple[str, str], list[str]] = {}
    for entry in found:
        component = ROLE_PREFIX + entry["role"]
        for kind in KINDS:
            if entry[kind]:
                words.setdefault((component, entry[kind]["model"]), []).append(kind)
        for pick in (entry["economy"], entry["quality"]):
            if pick and pick["baseline"]:
                words.setdefault((component, pick["model"]), []).append("baseline")
    return {key: ", ".join(dict.fromkeys(value)) for key, value in words.items()}


def _cell(pick: dict[str, Any] | None) -> str:
    if not pick:
        return eval_matrix.MISSING
    cost = eval_matrix.MISSING if pick["cost_per_pass"] is None else f"{pick['cost_per_pass']:.4f}"
    return f"{pick['model']} ({pick['pass_rate']:.2f}, {cost})"


def _note(entry: dict[str, Any]) -> str:
    notes = [entry["reason"]] if entry["reason"] else []
    if entry["skipped"]:
        notes.append(f"Fewer than {MIN_TRIALS} trials, so not counted: {', '.join(entry['skipped'])}.")
    return " ".join(notes)


def text(found: list[dict[str, Any]]) -> str:
    """The Markdown table of the picks. Each pick shows (pass rate, cost for each passing run)."""
    head = ["Role", "Baseline", "Economy", "Quality", "Note"]
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    for entry in found:
        cells = [entry["role"], entry["baseline"] or eval_matrix.MISSING, _cell(entry["economy"]),
                 _cell(entry["quality"]), _note(entry)]
        lines.append("| " + " | ".join(cells) + " |")
    note = (f"A pick needs {MIN_TRIALS} trials or more for each scenario. If no model meets a "
            "rule, the pick is the baseline. These picks change no role model: a human changes "
            "`defaults.role_models` at G4.")
    return "\n".join(["", "Picks:", "", *lines, "", note]) + "\n"


# The check of a model profile --------------------------------------------------------------


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _result_problems(pick: dict[str, Any]) -> list[str]:
    """The problems of the model and the numbers of one pick."""
    found = []
    if not (isinstance(pick["model"], str) and pick["model"]):
        found.append("'model' must be a model ID.")
    if not (_number(pick["pass_rate"]) and 0 <= pick["pass_rate"] <= 1):
        found.append("'pass_rate' must be a number from 0 to 1.")
    cost = pick["cost_per_pass"]
    if cost is not None and not (_number(cost) and cost >= 0):
        found.append("'cost_per_pass' must be a number of 0 or more, or null if no rate is known.")
    return found


def _source_problems(pick: dict[str, Any]) -> list[str]:
    """The problems of the trials and the eval version of one pick."""
    found = []
    if not (isinstance(pick["trials"], int) and not isinstance(pick["trials"], bool)
            and pick["trials"] >= MIN_TRIALS):
        found.append(f"'trials' must be a whole number of {MIN_TRIALS} or more.")
    if not (isinstance(pick["eval_version"], str) and pick["eval_version"]):
        found.append("'eval_version' must be the version that ran the eval, as text.")
    return found


def _is_date(value: Any) -> bool:
    """A date, not a timestamp. YAML loads `2027-05-01T00:00:00` as a datetime."""
    return isinstance(value, dt.date) and not isinstance(value, dt.datetime)


def _date_problems(pick: dict[str, Any]) -> list[str]:
    found = [f"'{key}' must be a date, as YYYY-MM-DD." for key in ("date", "review")
             if not _is_date(pick[key])]
    if not found and pick["review"] <= pick["date"]:
        found.append("'review' must be later than 'date'.")
    return found


def pick_problems(pick: Any) -> list[str]:
    """The problems of one pick. An empty list means the pick is valid."""
    if not isinstance(pick, dict):
        return [f"must be a mapping with {', '.join(PICK_KEYS)}."]
    missing = [key for key in PICK_KEYS if key not in pick]
    if missing:
        return [f"has no {', '.join(missing)}."]
    return _result_problems(pick) + _source_problems(pick) + _date_problems(pick)


def _role_problems(role: str, block: Any, roles: dict[str, Any]) -> list[str]:
    where = f"recommendations.{role}"
    if role not in roles:
        return [f"{where}: the role has no role model in defaults.role_models."]
    if not isinstance(block, dict) or set(block) != set(KINDS):
        return [f"{where} must have the two keys {', '.join(KINDS)}."]
    return [f"{where}.{kind} {problem}" for kind in KINDS for problem in pick_problems(block[kind])]


def problems(data: Any) -> list[str]:
    """The problems of the `recommendations` block of a loaded model profile. No block gives none."""
    if not isinstance(data, dict):
        return []
    found = []
    ceiling = data.get(CEILING_KEY)
    if ceiling is not None and not (_number(ceiling) and ceiling >= 0):
        found.append(f"{CEILING_KEY} must be a number of 0 or more (USD for each passing run).")
    if "recommendations" not in data:
        return found
    block = data["recommendations"]
    if not isinstance(block, dict):
        return found + ["recommendations must map each role to its economy pick and quality pick."]
    roles = _role_models(data)
    return found + [problem for role, value in block.items()
            for problem in _role_problems(str(role), value, roles)]


# The freshness of the picks (#306, D124) ----------------------------------------------------


def _pick_stale(where: str, pick: dict[str, Any], listed: set[str], today: dt.date) -> list[str]:
    """The warnings for one valid pick."""
    found = []
    if pick["review"] < today:
        found.append(f"{where} is past its review date {pick['review']}. "
                     "Run the matrix for this role.")
    if pick["model"] not in listed:
        found.append(f"{where} names {pick['model']}, which is not in the models of "
                     "this profile. Run the matrix for this role, or update models.")
    return found


def stale_problems(data: Any, today: dt.date) -> list[str]:
    """The warnings for the picks of a loaded model profile. A pick is stale if its review date
    has passed, or if its model is not in the `models` of the profile. A pick that
    `problems` rejects is skipped: `stone check` already fails on it."""
    if not isinstance(data, dict) or not isinstance(data.get("recommendations"), dict):
        return []
    models = data.get("models")
    listed = {str(m) for m in models} if isinstance(models, list) else set()
    found = []
    for role, block in data["recommendations"].items():
        picks = block if isinstance(block, dict) else {}
        for kind in KINDS:
            if kind in picks and not pick_problems(picks[kind]):
                found += _pick_stale(f"recommendations.{role}.{kind}", picks[kind], listed, today)
    return found
