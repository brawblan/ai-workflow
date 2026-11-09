"""The stream-json parser for the reference harness.

The core keeps the same functions, so this file gives the adapter a stable parser name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stone import eval_metrics, evals


def parse(stdout: str, fields: dict[str, str],
          where: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read the last JSON object that has the keys and values in `where`."""
    return evals.parse_output(stdout, fields, where)


def transcript_stats(path: Path) -> tuple[int, int] | None:
    """Count the tool calls and the bytes of the tool results."""
    return eval_metrics.transcript_stats(path)
