"""The parsers for the opencode harness.

`opencode run --format json` writes one JSON object on each line. The final assistant message is the
report. The `step_finish` events give the token counts and, sometimes, the cost.

The `sessions` function reads the session database that OpenCode keeps in SQLite (issue #328).
One row of the `session_v2` table is one session. One row of the `session_message` table with the
type `assistant` is one model call.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_NOTE = "The OpenCode 2.2.6 schema is expected."


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


def _open(path: Path) -> sqlite3.Connection:
    """Open the session database read-only. A missing file raises a RuntimeError."""
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise RuntimeError(f"{path}: cannot open the database ({error}). {SCHEMA_NOTE}") from None
    connection.row_factory = sqlite3.Row
    return connection


def _rows(connection: sqlite3.Connection, path: Path, sql: str) -> list[Any]:
    """Read all rows of one query. A missing table raises a RuntimeError."""
    try:
        return connection.execute(sql).fetchall()
    except sqlite3.Error as error:
        raise RuntimeError(f"{path}: cannot read the table ({error}). {SCHEMA_NOTE}") from None


def _count(value: Any) -> int:
    """The token count as an int. A missing or bad value is 0."""
    return int(value) if _number(value) else 0


def _moment(created: Any) -> datetime | None:
    """The epoch milliseconds as a timezone-aware UTC datetime. A bad value gives None."""
    if not _number(created) or created <= 0:
        return None
    return datetime.fromtimestamp(created / 1000, tz=timezone.utc)


def _model(model: dict[str, Any]) -> str:
    """The model name is 'providerID/id'. A missing part gives an empty name."""
    model_id = str(model.get("id") or "")
    provider = str(model.get("providerID") or "")
    return f"{provider}/{model_id}" if model_id and provider else ""


def _call(data: dict[str, Any]) -> dict[str, Any] | None:
    """Build one call dict from an assistant message. A message with no tokens map is skipped."""
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    when = data.get("time") if isinstance(data.get("time"), dict) else {}
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    reason = _count(tokens.get("reasoning"))
    return {"time": _moment(when.get("created")), "model": _model(model),
            "effort": str(data.get("agent") or ""), "input": _count(tokens.get("input")),
            "cache_read": _count(cache.get("read")), "cache_write": _count(cache.get("write")),
            "output": _count(tokens.get("output")) + reason, "thinking": reason}


def _calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The call dicts of one session, ordered by the created time."""
    calls = [call for message in messages if (call := _call(message)) is not None]
    start = datetime.min.replace(tzinfo=timezone.utc)
    calls.sort(key=lambda call: call["time"] or start)
    return calls


def _messages(connection: sqlite3.Connection, path: Path) -> dict[str, list[dict[str, Any]]]:
    """Group the assistant messages of the database by session id."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    sql = "SELECT session_id, type, data FROM session_message"
    for row in _rows(connection, path, sql):
        if row["type"] != "assistant":
            continue
        try:
            data = json.loads(row["data"])
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            grouped.setdefault(str(row["session_id"]), []).append(data)
    return grouped


def _under(directory: Any, root: Path) -> bool:
    """True when the session directory is the root folder or under it."""
    if not isinstance(directory, str):
        return False
    bases = (str(root), str(root.resolve()))
    return any(directory == base or directory.startswith(base + "/") for base in bases)


def sessions(path: Path, root: Path | None) -> list[dict[str, Any]]:
    """Return one dict for each session of the database that has at least one model call.

    One dict has the session id as `name`, the `kind` (`main`, or `subagent` for a session with a
    parent), and the `calls`. With `root`, keep only the sessions of that folder.
    """
    connection = _open(path)
    try:
        rows = _rows(connection, path, "SELECT id, parent_id, directory FROM session_v2")
        grouped = _messages(connection, path)
    finally:
        connection.close()
    found = []
    for row in rows:
        calls = _calls(grouped.get(str(row["id"]), []))
        if not calls or (root is not None and not _under(row["directory"], root)):
            continue
        found.append({"name": str(row["id"]),
                      "kind": "subagent" if row["parent_id"] is not None else "main",
                      "calls": calls})
    found.sort(key=lambda item: item["name"])
    return found
