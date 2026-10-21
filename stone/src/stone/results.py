"""Read the eval result files in `evals/results/` (P5, D50).

`stone eval` writes one file for each run: `<date>-<component>-<model>.md`. The first line names the
component. The second block names the model. This module reads those two items, so that `stone
render` can write `models_tested` and `stone check` can test it. The file name is not parsed,
because a component id and a model id can both contain a dash.
"""

from __future__ import annotations

import re
from pathlib import Path

RESULTS = Path("evals/results")
_COMPONENT = re.compile(r"^# Eval results: (\S+)[ \t]*$", re.M)
_MODEL = re.compile(r"^Model: `([^`\n]+)`", re.M)


def result_models(root: Path) -> dict[str, list[str]]:
    """Return the tested models of each component, from the result files. Sorted, no duplicates.

    A file with no component line or no model is not a result of a run. It is skipped.
    """
    found: dict[str, set[str]] = {}
    for path in sorted((root / RESULTS).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        component, model = _COMPONENT.search(text), _MODEL.search(text)
        if component and model:
            found.setdefault(component.group(1), set()).add(model.group(1))
    return {component: sorted(models) for component, models in found.items()}
