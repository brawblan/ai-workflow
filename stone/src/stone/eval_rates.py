"""Token rates for a harness that reports no cost (issue #315).

An adapter `eval.yaml` can name a rates file with the `rates` key. The file gives the USD rate for
each 1M tokens of each model, and optional peak rates with their UTC windows. `stone eval` then
estimates the cost of a run from its token counts, and warns before a run in a peak window.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml

KINDS = ("input", "output", "cache_read", "cache_write")
TOKENS = {"input": ("input_tokens",), "output": ("output_tokens", "reasoning_tokens"),
          "cache_read": ("cache_read_tokens",), "cache_write": ("cache_write_tokens",)}
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # the index is date.weekday()


class RatesError(Exception):
    """The rates file is missing or not valid."""


def path(run_config: Path, harness: Path, name: str) -> Path:
    """Return the rates file, from the run config folder first, then the adapter folder."""
    for folder in (run_config.parent, harness):
        if (folder / name).is_file():
            return folder / name
    raise RatesError(f"{run_config}: the rates file '{name}' does not exist.")


def load(file: Path) -> dict[str, Any]:
    """Read and validate a rates file. Raise RatesError on a problem."""
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise RatesError(f"{file}: cannot read the rates file ({error}).") from None
    found = problems(data)
    if found:
        raise RatesError(f"{file}: {found[0]}")
    return data


def _rate_problems(rates: Any, where: str) -> list[str]:
    if not isinstance(rates, dict):
        return [f"{where} must be a mapping with {', '.join(KINDS)}."]
    return [f"{where}.{kind} must be a number of 0 or more." for kind in KINDS
            if not _amount(rates.get(kind))]


def _amount(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _window_problems(window: Any, where: str) -> list[str]:
    if not isinstance(window, dict):
        return [f"{where} must be a mapping with hours and weekdays."]
    found = []
    hours, days = window.get("hours"), window.get("weekdays")
    if not isinstance(hours, list) or not hours or any(
            not isinstance(h, int) or isinstance(h, bool) or not 0 <= h <= 23 for h in hours):
        found.append(f"{where}.hours must be a list of UTC hours from 0 to 23.")
    if not isinstance(days, list) or not days or any(d not in WEEKDAYS for d in days):
        found.append(f"{where}.weekdays must be a list of {', '.join(WEEKDAYS)}.")
    return found


def _model_problems(model: str, entry: Any) -> list[str]:
    where = f"models.{model}"
    if not isinstance(entry, dict):
        return [f"{where} must be a mapping with rates."]
    found = _rate_problems(entry.get("rates"), f"{where}.rates")
    peak = entry.get("peak")
    if peak is None:
        return found
    if not isinstance(peak, dict) or not isinstance(peak.get("windows"), list) or not peak["windows"]:
        return [*found, f"{where}.peak must have rates and a list of windows."]
    found += _rate_problems(peak.get("rates"), f"{where}.peak.rates")
    for index, window in enumerate(peak["windows"]):
        found += _window_problems(window, f"{where}.peak.windows[{index}]")
    return found


def problems(data: Any) -> list[str]:
    """Return each problem of a loaded rates file. An empty list means the file is valid."""
    if not isinstance(data, dict):
        return ["the rates file must be a mapping with source, read, and models."]
    found = []
    if not str(data.get("source") or "").startswith("https://"):
        found.append("'source' must be the https URL of the rates.")
    if not isinstance(data.get("read"), dt.date):
        found.append("'read' must be the date when the rates were read, as YYYY-MM-DD.")
    models = data.get("models")
    if not isinstance(models, dict) or not models:
        return [*found, "'models' must map each model ID to its rates."]
    for model, entry in models.items():
        found += _model_problems(str(model), entry)
    return found


def _in_window(window: dict[str, Any], moment: dt.datetime) -> bool:
    return WEEKDAYS[moment.weekday()] in window["weekdays"] and moment.hour in window["hours"]


def peak_window(entry: dict[str, Any], moment: dt.datetime) -> dict[str, Any] | None:
    """Return the peak window that holds the UTC moment, or None."""
    windows = (entry.get("peak") or {}).get("windows") or []
    return next((w for w in windows if _in_window(w, moment)), None)


def estimate(usage: dict[str, Any], entry: dict[str, Any],
             started: dt.datetime) -> tuple[float, str]:
    """Return the cost in USD of the token counts, and the period: 'peak' or 'off-peak'.

    Reasoning tokens use the output rate. The start of the run selects the period.
    """
    period = "peak" if peak_window(entry, started) else "off-peak"
    rates = entry["peak"]["rates"] if period == "peak" else entry["rates"]
    cost = sum(rates[kind] * sum(int(usage.get(key) or 0) for key in keys)
               for kind, keys in TOKENS.items()) / 1_000_000
    return cost, period


def apply(usage: dict[str, Any], data: dict[str, Any], model: str, started: dt.datetime) -> None:
    """Set the cost of a run from the rates when the harness cost is missing or 0.

    A harness cost above 0 stays. If the model has no rates, a cost of 0 is removed, so the
    tables show "—" and not 0.
    """
    if float(usage.get("cost_usd") or 0) > 0:
        usage["cost_source"] = "harness"
        return
    entry = (data.get("models") or {}).get(model)
    if entry is None:
        usage.pop("cost_usd", None)
        return
    usage["cost_usd"], usage["rate_period"] = estimate(usage, entry, started)
    usage["cost_source"] = "rates"


def _factor(entry: dict[str, Any]) -> float:
    base, peak = entry["rates"], entry["peak"]["rates"]
    ratios = [peak[kind] / base[kind] for kind in KINDS if base[kind] > 0]
    return max(ratios, default=1.0)


def _window_end(window: dict[str, Any], moment: dt.datetime) -> int:
    hour = moment.hour
    while hour + 1 in window["hours"]:
        hour += 1
    return (hour + 1) % 24


def warning(model: str, data: dict[str, Any], moment: dt.datetime) -> str:
    """Return a warning if the model is in a peak window at the UTC moment, else ''."""
    entry = (data.get("models") or {}).get(model)
    window = peak_window(entry, moment) if entry else None
    if window is None:
        return ""
    return (f"stone eval: warning: '{model}' is in a peak window now. Its peak rates are up to "
            f"{_factor(entry):g} times the off-peak rates. The window ends at "
            f"{_window_end(window, moment):02d}:00 UTC.")


def note(data: dict[str, Any], runs: list[Any], file: str) -> str:
    """Return one line for the result file if a run cost is an estimate, else ''."""
    estimated = [r for r in runs if r.usage.get("cost_source") == "rates"]
    if not estimated:
        return ""
    peak = sum(r.usage.get("rate_period") == "peak" for r in estimated)
    return (f"Cost: an estimate from the token rates in `{file}`, read {data['read']}. It is not "
            f"the billed cost. {len(estimated)} of {len(runs)} runs used the rates, "
            f"{peak} at the peak rate.")
