"""`stone usage`: a token report from the local session transcripts (issue #297, D114).

The adapter file `usage.yaml` holds the transcript format, the default folders, and the weights.
A reader format instead names a parser file, the default session files, and a rates file (D122).
The cost is then an estimate in USD from the rates. This module names no harness. The weights are
relative units, not money.
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from stone import eval_rates

DEFAULT_REBUILD_TOKENS = 30_000
UNIT_NOTE = "Cost is in relative units that follow the price ratios. It is not money."
PARTS = ("cache_read", "cache_write", "output", "input")
LENGTHS = ("5m", "1h")
# The reader path maps each part of the report to the token count key of the rates (D122).
READER_KEYS = {"input": "input_tokens", "cache_read": "cache_read_tokens",
               "cache_write": "cache_write_tokens", "output": "output_tokens"}
OFF_PEAK = datetime.min.replace(tzinfo=timezone.utc)


class UsageError(Exception):
    """The adapter has no usage file, or a PATH cannot be read."""


@dataclass
class Call:
    time: datetime | None
    model: str
    effort: str
    input: int
    cache_read: int
    cache_write: dict[str, int]
    output: int
    thinking: int


@dataclass
class Session:
    name: str
    kind: str
    calls: list[Call] = field(default_factory=list)


def load_format(framework: Path, harness: str) -> dict[str, Any]:
    path = framework / "adapters" / harness / "usage.yaml"
    if not path.is_file():
        raise UsageError(f"The adapter '{harness}' has no usage.yaml. Add it to run stone usage.")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    transcript = data.get("transcript") if isinstance(data, dict) else None
    reader = data.get("reader") if isinstance(data, dict) else None
    if not isinstance(transcript, dict) and not isinstance(reader, dict):
        raise UsageError(f"{path}: the file has no 'transcript' or 'reader' map.")
    if isinstance(reader, dict) and not data.get("rates"):
        raise UsageError(f"{path}: a reader needs a rates file. Add the 'rates' key.")
    return data


def _dotted(data: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _call(record: dict[str, Any], spec: dict[str, Any]) -> Call | None:
    usage = spec["usage"]
    if not isinstance(_dotted(record, usage["output"].rsplit(".", 1)[0]), dict):
        return None   # no usage data
    write = {"5m": _int(_dotted(record, usage["cache_write_5m"])),
             "1h": _int(_dotted(record, usage["cache_write_1h"]))}
    total = _int(_dotted(record, usage.get("cache_write_total", "")))
    if not any(write.values()) and total:
        write["5m"] = total   # no split: count the writes as the shorter cache
    return Call(_time(_dotted(record, spec["time"])), str(_dotted(record, spec["model"]) or ""),
                str(_dotted(record, spec.get("effort", "")) or ""),
                _int(_dotted(record, usage["input"])), _int(_dotted(record, usage["cache_read"])),
                write, _int(_dotted(record, usage["output"])),
                _int(_dotted(record, usage["thinking"])))


def read_transcript(path: Path, spec: dict[str, Any]) -> list[Call]:
    """Return the calls of one file. A bad line and a record with no usage data are skipped.
    A call with more than one record counts once: the last record wins."""
    wanted = spec["record"]
    calls: dict[str, Call] = {}
    order: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        raise UsageError(f"{path}: {error}") from error
    for number, line in enumerate(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or _dotted(record, wanted["field"]) != wanted["value"]:
            continue
        call = _call(record, spec)
        if call is None:
            continue
        call_id = str(_dotted(record, spec["call_id"]) or f"line-{number}")
        if call_id not in calls:
            order.append(call_id)
        calls[call_id] = call
    return [calls[call_id] for call_id in order]


def default_folders(root: Path, fmt: dict[str, Any]) -> list[Path]:
    key = str(root.resolve()).replace("/", "-").replace(".", "-")
    found: list[Path] = []
    for pattern in fmt.get("folders", []):
        expanded = os.path.expanduser(str(pattern).replace("{key}", key))
        found += [Path(item) for item in sorted(glob.glob(expanded)) if os.path.isdir(item)]
    return found


def _default_files(fmt: dict[str, Any]) -> list[Path]:
    """The default files of the reader, with '~' expanded. Each one must exist."""
    files = [Path(os.path.expanduser(str(item))) for item in fmt["reader"]["databases"]]
    for item in files:
        if not item.is_file():
            raise UsageError(f"no session database at {item}. Run a session first, or give a PATH.")
    return files


def _parser(framework: Path, harness: str, name: str) -> Any:
    """Load the parser file of the reader. Its module must have a callable `sessions`."""
    path = framework / "adapters" / harness / name
    spec = importlib.util.spec_from_file_location("stone_usage_reader_parser", path)
    if spec is None or spec.loader is None:
        raise UsageError(f"{path}: cannot load the parser file.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise UsageError(f"{path}: {error}") from error
    if not callable(getattr(module, "sessions", None)):
        raise UsageError(f"{path}: the parser file has no sessions function.")
    return module


def _reader_call(item: dict[str, Any]) -> Call:
    """Build a Call from one parser dict. The reader gives no cache split, so the write is 5m."""
    when = item.get("time")
    return Call(when if isinstance(when, datetime) and when.tzinfo else None,
                str(item.get("model") or ""), str(item.get("effort") or ""),
                _int(item.get("input")), _int(item.get("cache_read")),
                {"5m": _int(item.get("cache_write")), "1h": 0},
                _int(item.get("output")), _int(item.get("thinking")))


def _parser_sessions(items: list[dict[str, Any]], since: date | None) -> list[Session]:
    """Convert the parser dicts into Session objects. A session with no call is skipped."""
    sessions = []
    for item in items:
        calls = [_reader_call(c) for c in item.get("calls", [])]
        if since:
            calls = [c for c in calls if c.time and c.time.date() >= since]
        if calls:
            sessions.append(Session(str(item.get("name") or ""),
                                    str(item.get("kind") or "main"), calls))
    return sessions


def _reader_sessions(root: Path, files: list[Path], parser: Any, since: date | None,
                     pass_root: bool) -> list[Session]:
    """Read each file with the parser and build the Session objects. Apply --since."""
    sessions: list[Session] = []
    for file in files:
        try:
            found = parser.sessions(file, root if pass_root else None)
        except Exception as error:
            raise UsageError(str(error)) from error
        sessions += _parser_sessions(found, since)
    return sessions


def find_files(paths: list[Path], spec: dict[str, Any]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files += sorted(path.rglob(spec.get("glob", "*.jsonl")))
        else:
            raise UsageError(f"{path}: no file or folder.")
    return list(dict.fromkeys(files))


def _kind(path: Path, spec: dict[str, Any]) -> str:
    return "subagent" if spec.get("subagent_folder") in path.parts else "main"


def load_sessions(files: list[Path], spec: dict[str, Any], since: date | None) -> list[Session]:
    sessions = []
    for path in files:
        calls = read_transcript(path, spec)
        if since:
            calls = [c for c in calls if c.time and c.time.date() >= since]
        if calls:
            name = f"{path.parent.parent.name}/{path.stem}" if _kind(path, spec) == "subagent" \
                else path.stem
            sessions.append(Session(name, _kind(path, spec), calls))
    return sessions


def cost(call: Call, weights: dict[str, float]) -> dict[str, float]:
    """The weighted cost of one call, by part."""
    return {"input": call.input * weights["input"],
            "cache_read": call.cache_read * weights["cache_read"],
            "cache_write": sum(call.cache_write[n] * weights[f"cache_write_{n}"] for n in LENGTHS),
            "output": call.output * weights["output"]}


def rebuilds(calls: list[Call], seconds: dict[str, int], limit: int) -> int:
    """Count the calls after a gap longer than the cache that write more than `limit` tokens."""
    count = 0
    length = seconds["5m"]
    previous: datetime | None = None
    for call in sorted((c for c in calls if c.time), key=lambda c: c.time or datetime.min):
        gap = (call.time - previous).total_seconds() if previous and call.time else 0
        if gap > length and sum(call.cache_write.values()) > limit:
            count += 1
        if call.cache_write["1h"]:
            length = seconds["1h"]
        previous = call.time
    return count


def _label(values: list[str]) -> str:
    counts = Counter(v for v in values if v and not v.startswith("<"))
    return ", ".join(sorted(counts)) or "-"


def _extent(calls: list[Call]) -> dict[str, Any]:
    """The cache writes for each length, and the largest context of one call."""
    return {"cache_write": {n: sum(c.cache_write[n] for c in calls) for n in LENGTHS},
            "context": max(c.input + c.cache_read + sum(c.cache_write.values()) for c in calls)}


def _session_row(session: Session, fmt: dict[str, Any], limit: int) -> tuple[dict[str, Any],
                                                                              dict[str, float]]:
    """Return the report row of one session, and its weighted cost by part."""
    parts = dict.fromkeys(PARTS, 0.0)
    for call in session.calls:
        for part, value in cost(call, fmt["weights"]).items():
            parts[part] += value
    calls = session.calls
    ext = _extent(calls)
    row = {
        "session": session.name, "kind": session.kind,
        "model": _label([c.model for c in calls]), "effort": _label([c.effort for c in calls]),
        "calls": len(calls), "cache_read": sum(c.cache_read for c in calls),
        "cache_write": ext["cache_write"],
        "output": sum(c.output for c in calls), "thinking": sum(c.thinking for c in calls),
        "context": ext["context"],
        "rebuilds": rebuilds(calls, fmt["cache_seconds"], limit),
        "cost": round(sum(parts.values()), 2)}
    return row, parts


def report(sessions: list[Session], fmt: dict[str, Any], limit: int) -> dict[str, Any]:
    rows, totals = [], dict.fromkeys(PARTS, 0.0)
    for session in sessions:
        row, parts = _session_row(session, fmt, limit)
        rows.append(row)
        for part in PARTS:
            totals[part] += parts[part]
    whole = sum(totals.values())
    for row in rows:
        row["share"] = round(row["cost"] / whole, 4) if whole else 0.0
    shares = {p: round(totals[p] / whole, 4) if whole else 0.0 for p in PARTS}
    return {"unit_note": UNIT_NOTE, "rebuild_tokens": limit, "sessions": rows,
            "totals": {"calls": sum(r["calls"] for r in rows), "cost": round(whole, 2),
                       "shares": shares}}


def _call_cost(call: Call, entry: dict[str, Any]) -> tuple[dict[str, float], bool]:
    """The USD cost of one call by part, and True when the call ran in a peak window.

    Each part is one estimate call with only that token kind set (D122).
    """
    when = call.time or OFF_PEAK
    counts = {"input": call.input, "cache_read": call.cache_read,
              "cache_write": sum(call.cache_write.values()), "output": call.output}
    parts = {part: eval_rates.estimate({key: counts[part]}, entry, when)[0]
             for part, key in READER_KEYS.items()}
    return parts, eval_rates.peak_window(entry, when) is not None


def _rated_cost(calls: list[Call], rates: dict[str, Any]) -> tuple[dict[str, float], int, int,
                                                                   float | None]:
    """The USD cost by part of the rated calls, the peak count, the unrated count, and the cost.

    The cost is None when no call is rated. A call whose model has no rates is not counted.
    """
    parts = dict.fromkeys(PARTS, 0.0)
    peak = unrated = 0
    usd = 0.0
    rated = False
    for call in calls:
        entry = (rates.get("models") or {}).get(call.model)
        if entry is None:
            unrated += 1
            continue
        call_parts, at_peak = _call_cost(call, entry)
        peak += at_peak
        rated = True
        for part in PARTS:
            parts[part] += call_parts[part]
        usd += sum(call_parts.values())
    return parts, peak, unrated, round(usd, 6) if rated else None


def _reader_row(session: Session, rates: dict[str, Any]) -> tuple[dict[str, Any],
                                                                   dict[str, float]]:
    """Return the report row of one session, and its USD cost by part."""
    calls = session.calls
    parts, peak, unrated, usd = _rated_cost(calls, rates)
    ext = _extent(calls)
    row = {
        "session": session.name, "kind": session.kind,
        "model": _label([c.model for c in calls]), "effort": _label([c.effort for c in calls]),
        "calls": len(calls), "cache_read": sum(c.cache_read for c in calls),
        "cache_write": ext["cache_write"], "input": sum(c.input for c in calls),
        "output": sum(c.output for c in calls), "thinking": sum(c.thinking for c in calls),
        "context": ext["context"], "rebuilds": None, "peak_calls": peak,
        "unrated_calls": unrated, "cost": usd}
    return row, parts


def reader_report(sessions: list[Session], rates: dict[str, Any], name: str,
                  limit: int) -> dict[str, Any]:
    """The report on the reader path: the cost is an estimate in USD from the rates (D122)."""
    rows, totals = [], dict.fromkeys(PARTS, 0.0)
    for session in sessions:
        row, parts = _reader_row(session, rates)
        rows.append(row)
        for part in PARTS:
            totals[part] += parts[part]
    whole = sum(totals.values())
    for row in rows:
        row["share"] = round(row["cost"] / whole, 4) if whole and row["cost"] is not None else 0.0
    shares = {p: round(totals[p] / whole, 4) if whole else 0.0 for p in PARTS}
    note = (f"Cost is an estimate in USD from the token rates in {name}, read {rates['read']}. "
            "It is not the billed cost. A call with no rates is not counted.")
    return {"unit": "usd", "unit_note": note, "rebuild_tokens": limit, "sessions": rows,
            "totals": {"calls": sum(r["calls"] for r in rows), "cost": round(whole, 6),
                       "shares": shares}}


def _k(value: int) -> str:
    return f"{value / 1000:.1f}k" if value >= 1000 else str(value)


def _usd(value: float | None) -> str:
    """The cost as '$0.0123', or a dash when no call of the session is rated."""
    return "—" if value is None else f"${value:.4f}"


def _reader_cells(row: list[str], r: dict[str, Any]) -> list[str]:
    """Add the Input cell and the Cost (USD) cell of a reader row."""
    row.insert(8, _k(r["input"]))
    row.insert(11, _usd(r["cost"]))
    return row


def _head(reader: bool) -> list[str]:
    """The column names. A reader report adds the Input and the Cost (USD) columns."""
    head = ["Session", "Kind", "Model", "Effort", "Calls", "Cache read", "Cache write 5m/1h",
            "Output (think)", "Context", "Rebuilds", "Share"]
    if reader:
        head.insert(8, "Input")
        head.insert(11, "Cost (USD)")
    return head


def render_text(data: dict[str, Any]) -> str:
    reader = data.get("unit") == "usd"
    head = _head(reader)
    table = [head]
    for r in data["sessions"]:
        row = [r["session"], r["kind"], r["model"], r["effort"], str(r["calls"]),
               _k(r["cache_read"]),
               f"{_k(r['cache_write']['5m'])}/{_k(r['cache_write']['1h'])}",
               f"{_k(r['output'])} ({_k(r['thinking'])})", _k(r["context"]),
               "-" if r["rebuilds"] is None else str(r["rebuilds"]), f"{r['share'] * 100:.1f}%"]
        table.append(_reader_cells(row, r) if reader else row)
    widths = [max(len(row[i]) for row in table) for i in range(len(head))]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
             for row in table]
    shares = data["totals"]["shares"]
    lines.append("")
    lines.append(f"Totals: {data['totals']['calls']} calls. Share of cost: "
                 + ", ".join(f"{p.replace('_', ' ')} {shares[p] * 100:.1f}%" for p in PARTS) + ".")
    lines.append(data["unit_note"])
    return "\n".join(lines) + "\n"


def _run_reader(root: Path, framework: Path, harness: str, fmt: dict[str, Any],
                paths: list[Path], since: date | None, limit: int, as_json: bool) -> str:
    """The reader path: the parser reads each session file, and the cost uses the rates (D122)."""
    files = paths or _default_files(fmt)
    for item in files:
        if not item.is_file():
            raise UsageError(f"{item}: no file.")
    parser = _parser(framework, harness, fmt["reader"]["parser"])
    sessions = _reader_sessions(root, files, parser, since, pass_root=not paths)
    rates_file = framework / "adapters" / harness / str(fmt["rates"])
    try:
        rates = eval_rates.load(rates_file)
    except eval_rates.RatesError as error:
        raise UsageError(str(error)) from error
    data = reader_report(sessions, rates, fmt["rates"], limit)
    return json.dumps(data, indent=2) + "\n" if as_json else render_text(data)


def run(root: Path, framework: Path, harness: str, paths: list[Path], since: date | None,
        limit: int, as_json: bool) -> str:
    fmt = load_format(framework, harness)
    if fmt.get("reader"):
        return _run_reader(root, framework, harness, fmt, paths, since, limit, as_json)
    spec = fmt["transcript"]
    folders = paths or default_folders(root, fmt)
    sessions = load_sessions(find_files(folders, spec), spec, since)
    data = report(sessions, fmt, limit)
    return json.dumps(data, indent=2) + "\n" if as_json else render_text(data)
