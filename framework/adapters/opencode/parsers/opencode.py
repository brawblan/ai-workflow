"""The JSONL parser for the opencode harness.

`opencode run --format json` writes one JSON object on each line. The final assistant message is the
report. The `step_finish` events give the token counts and, sometimes, the cost.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def _events(text: str) -> Iterator[dict[str, Any]]:
    """Yield each JSON object. A line that is not JSON is skipped."""
    for line in text.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            yield data


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse(stdout: str, fields: dict[str, str],
          where: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read the report and the metrics from the JSONL events.

    The report joins the text parts of the last assistant message. A message is the `messageID` of
    the part. A numeric cost is summed even when it is 0. A missing cost stays unknown.
    """
    texts: dict[str, list[str]] = {}
    order: list[str] = []
    totals = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
              "cache_read_tokens": 0, "cache_write_tokens": 0}
    seen: set[str] = set()
    cost = 0.0
    cost_present = False
    turns = 0
    for event in _events(stdout):
        kind = event.get("type")
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        if kind == "text":
            value = part.get("text")
            if isinstance(value, str) and value.strip():
                message = str(part.get("messageID") or len(order))
                if message not in texts:
                    texts[message] = []
                    order.append(message)
                texts[message].append(value)
        elif kind == "step_finish":
            turns += 1
            if _number(part.get("cost")):
                cost += float(part["cost"])
                cost_present = True
            tokens = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
            pairs = (("input", "input_tokens"), ("output", "output_tokens"),
                     ("reasoning", "reasoning_tokens"))
            for key, out in pairs:
                if _number(tokens.get(key)):
                    totals[out] += int(tokens[key])
                    seen.add(out)
            cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
            for key, out in (("read", "cache_read_tokens"), ("write", "cache_write_tokens")):
                if _number(cache.get(key)):
                    totals[out] += int(cache[key])
                    seen.add(out)
    usage: dict[str, Any] = {}
    if order:
        usage["report"] = "".join(texts[order[-1]])
    if turns:
        usage["turns"] = turns
    if cost_present:
        usage["cost_usd"] = cost
    for key in seen:
        usage[key] = totals[key]
    return usage


def transcript_stats(path: Path) -> tuple[int, int] | None:
    """Count the `tool_use` events and the bytes of their output."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    calls = size = 0
    for event in _events(text):
        if event.get("type") != "tool_use":
            continue
        calls += 1
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        output = state.get("output")
        if isinstance(output, str):
            size += len(output.encode("utf-8"))
        elif isinstance(output, (dict, list)):
            size += len(json.dumps(output).encode("utf-8"))
    return calls, size
