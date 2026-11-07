"""Cost and token metrics for the `stone eval` result (#271).

The tables read `Run.usage`. A key that a run does not have shows as "—", never as 0.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

MISSING = "—"
BASE_NAMES = ("without", "none")
# (column title, usage key, decimals) for the table of each scenario and variant.
COLUMNS = (("Cost", "cost_usd", 4), ("Turns", "turns", 1), ("Tool calls", "tool_calls", 1),
           ("Tool bytes", "tool_bytes", 0), ("Tokens in", "input_tokens", 0),
           ("Cache read", "cache_read_tokens", 0), ("Tokens out", "output_tokens", 0))


def _result_size(content: Any) -> int:
    """The bytes of one tool result: a string, or a list of text blocks."""
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    if isinstance(content, list):
        return sum(_result_size(block.get("text", "")) for block in content
                   if isinstance(block, dict))
    return 0


def _blocks(line: str) -> list[dict[str, Any]]:
    """The content blocks of one transcript line, or an empty list."""
    try:
        message = json.loads(line).get("message")
    except (json.JSONDecodeError, AttributeError):
        return []
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def transcript_stats(path: Path) -> tuple[int, int] | None:
    """Return (tool calls, bytes of tool results) from a stream-json transcript.
    Return None if the file is missing, so the run gets no value, not 0."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    calls = size = 0
    for line in text.splitlines():
        for block in _blocks(line):
            if block.get("type") == "tool_use":
                calls += 1
            elif block.get("type") == "tool_result":
                size += _result_size(block.get("content"))
    return calls, size


def _values(runs: list[Any], key: str) -> list[float]:
    return [r.usage[key] for r in runs
            if isinstance(r.usage.get(key), (int, float)) and not isinstance(r.usage[key], bool)]


def mean(runs: list[Any], key: str, digits: int = 0) -> str:
    values = _values(runs, key)
    return f"{sum(values) / len(values):.{digits}f}" if values else MISSING


def mean_and_error(values: list[float]) -> tuple[float, float] | None:
    """The mean and the standard error. The error is 0 for one value."""
    if not values:
        return None
    average = sum(values) / len(values)
    if len(values) < 2:
        return average, 0.0
    variance = sum((v - average) ** 2 for v in values) / (len(values) - 1)
    return average, math.sqrt(variance / len(values))


def _scenario_row(group: list[Any], rate: Callable[[list[Any], str | None], float]) -> str:
    cells = [group[0].scenario, group[0].variant, str(len(group)),
             str(int(all(r.passed() for r in group))),
             f"{rate(group, 'outcome'):.2f}", f"{rate(group, 'contract'):.2f}",
             *(mean(group, key, digits) for _, key, digits in COLUMNS),
             mean(group, "seconds", 1), str(sum(bool(r.error) for r in group))]
    return "| " + " | ".join(cells) + " |"


def scenario_table(runs: list[Any], rate: Callable[[list[Any], str | None], float]) -> list[str]:
    """One row for each scenario and variant."""
    head = ["Scenario", "Variant", "Trials", "pass^k", "Outcome", "Contract",
            *(title for title, _, _ in COLUMNS), "Seconds", "Errors"]
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    for sid in dict.fromkeys(r.scenario for r in runs):
        for variant in dict.fromkeys(r.variant for r in runs):
            group = [r for r in runs if r.scenario == sid and r.variant == variant]
            if group:
                lines.append(_scenario_row(group, rate))
    return lines


def _variant_cells(group: list[Any], rate: Callable[[list[Any], str | None], float]) -> list[str]:
    cost = mean_and_error(_values(group, "cost_usd"))
    return [f"{cost[0]:.4f}" if cost else MISSING, f"{cost[1]:.4f}" if cost else MISSING,
            mean(group, "turns", 1), mean(group, "tool_bytes"), f"{rate(group, 'outcome'):.2f}"]


def variant_table(runs: list[Any], rate: Callable[[list[Any], str | None], float]) -> list[str]:
    """One row for each variant over all scenarios."""
    head = ["Variant", "Runs", "Cost mean", "Cost SE", "Turns mean", "Tool bytes mean",
            "Pass rate"]
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    for variant in dict.fromkeys(r.variant for r in runs):
        group = [r for r in runs if r.variant == variant]
        lines.append("| " + " | ".join([variant, str(len(group)), *_variant_cells(group, rate)])
                     + " |")
    return lines


def _verdict(diff: float, error: float) -> str:
    return "more than 2 standard errors" if abs(diff) > 2 * error else "within 2 standard errors"


def _difference_line(runs: list[Any], name: str, base: str) -> str:
    base_cost = mean_and_error(_values([r for r in runs if r.variant == base], "cost_usd"))
    other = mean_and_error(_values([r for r in runs if r.variant == name], "cost_usd"))
    if not (base_cost and other):
        return f"Cost, {name} minus {base}: {MISSING}. A run has no cost."
    diff = other[0] - base_cost[0]
    error = math.hypot(other[1], base_cost[1])
    return (f"Cost, {name} minus {base}: {diff:+.4f} USD. "
            f"The difference is {_verdict(diff, error)} (SE {error:.4f}).")


def cost_difference_lines(runs: list[Any]) -> list[str]:
    """For each variant that is not the base: the mean cost difference to the base."""
    names = list(dict.fromkeys(r.variant for r in runs))
    base = next((name for name in BASE_NAMES if name in names), "")
    return [_difference_line(runs, name, base) for name in names if base and name != base]
