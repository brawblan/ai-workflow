"""The model matrix of `stone eval --summary ... --by model` (#304).

One row for each component and model. A run that has no value for a key gives no value to the mean,
so a cell shows "—", never 0. The runs come from one or more kept `runs.jsonl` files.
"""

from __future__ import annotations

from typing import Any

from . import eval_metrics

MISSING = eval_metrics.MISSING
TOKEN_NOTE = ("Tokens: compare them only inside one model family. Each family has its own "
              "tokenizer.")
# (column title, usage key, decimals) of the mean columns that follow Pass rate and Cost per pass.
MEANS = (("Cost", "cost_usd", 4), ("Turns", "turns", 1), ("Tool bytes", "tool_bytes", 0),
         ("Seconds", "seconds", 1), ("Tokens in", "input_tokens", 0),
         ("Tokens out", "output_tokens", 0))


def model_label(run: Any) -> str:
    """The ID of the run as `--model` takes it: `<harness>:<model>`. An old run has no harness."""
    model = getattr(run, "model", "") or "unknown"
    harness = getattr(run, "harness", "")
    return f"{harness}:{model}" if harness else model


def _mean(values: list[float]) -> dict[str, Any] | None:
    """The mean and the standard error. The error is None for fewer than 2 values."""
    found = eval_metrics.mean_and_error(values)
    if not found:
        return None
    return {"mean": found[0], "se": found[1] if len(values) > 1 else None, "n": len(values)}


def _cost_per_pass(group: list[Any]) -> float | None:
    """The total cost divided by the passing runs. None if no run passes or a run has no cost."""
    costs = eval_metrics._values(group, "cost_usd")
    passing = sum(r.passed() for r in group)
    if not passing or len(costs) < len(group):
        return None
    return sum(costs) / passing


def _row(component: str, model: str, group: list[Any]) -> dict[str, Any]:
    row: dict[str, Any] = {"component": component, "model": model, "runs": len(group),
                           "pass_rate": _mean([float(r.passed()) for r in group]),
                           "cost_per_pass": _cost_per_pass(group)}
    for _, key, _ in MEANS:
        row[key] = _mean(eval_metrics._values(group, key))
    return row


def rows(runs: list[Any]) -> list[dict[str, Any]]:
    """One row for each component and model. The base variant ('without') is left out."""
    groups: dict[tuple[str, str], list[Any]] = {}
    for run in runs:
        if run.variant not in eval_metrics.BASE_NAMES:
            key = (getattr(run, "component", "") or "unknown", model_label(run))
            groups.setdefault(key, []).append(run)
    return [_row(component, model, group) for (component, model), group in groups.items()]


def variants(runs: list[Any]) -> list[str]:
    """The variants that the rows count."""
    return list(dict.fromkeys(r.variant for r in runs if r.variant not in eval_metrics.BASE_NAMES))


def _cell(value: dict[str, Any] | None, digits: int) -> str:
    if not value:
        return MISSING
    error = MISSING if value["se"] is None else f"{value['se']:.{digits}f}"
    return f"{value['mean']:.{digits}f} ±{error}"


def text(found: list[dict[str, Any]], counted: list[str]) -> str:
    """The Markdown table, then the variant line and the token note."""
    head = ["Component", "Model", "Runs", "Pass rate", "Cost per pass",
            *(title for title, _, _ in MEANS)]
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    for row in found:
        per_pass = row["cost_per_pass"]
        cells = [row["component"], row["model"], str(row["runs"]), _cell(row["pass_rate"], 2),
                 MISSING if per_pass is None else f"{per_pass:.4f}",
                 *(_cell(row[key], digits) for _, key, digits in MEANS)]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "Each mean shows ±standard error. The error is — for one run. Cost is in USD.",
              f"Variants counted: {', '.join(counted) or MISSING}.", TOKEN_NOTE]
    return "\n".join(lines) + "\n"


def as_json(found: list[dict[str, Any]], counted: list[str]) -> dict[str, Any]:
    """The same data as `text`, for `--json`."""
    return {"variants": counted, "token_note": TOKEN_NOTE, "rows": found}
