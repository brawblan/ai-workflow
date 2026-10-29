"""Custom checks for the role.shaper eval. `stone eval` runs this file once for each grader check.

Usage: grade.py <name> --workspace <path> --args <json>. The last line of the output is JSON:
{"pass": true|false, "detail": "..."}. The final text of the run is in STONE_EVAL_REPORT. The
ticket before the run is the file in the first commit that added it (the `change` of the scenario).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPORT_ENV = "STONE_EVAL_REPORT"
FIELDS = ("Problem", "Acceptance criteria", "Non-goals", "Test oracle", "Personas")
# A value that is not an answer: a question, a mark that the field is open, or an empty form.
PLACEHOLDER = re.compile(
    r"\?|\btbd\b|\btodo\b|\bopen\b|unknown|pending|question|missing|awaiting|"
    r"not (yet )?(answered|given|known|set|defined|provided|decided|confirmed|specified)|"
    r"to be (decided|defined|confirmed|agreed)|\bask|\bn/a\b|^[\s<>\[\]()_.*-]*$", re.I)
READY = re.compile(r"\bready\b|\bmeets\b|\bcomplete\b", re.I)
NOT_READY = re.compile(r"\bnot (yet )?(ready|complete)|\bincomplete\b|"
                       r"(does not|doesn.t|do not|don.t) (yet )?meet", re.I)
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)]|\(?[a-dA-D][.)])\s+")
INLINE = re.compile(r"(?:^|[\s(|:;])\(?([a-dA-D]|[1-4])\)\s")
NOT_OPTION = re.compile(r"^\W*(recommend|default|note|why|context|reason)", re.I)
OPTION = re.compile(r"^\s*[-*]?\s*\(?[a-dA-D]\)\s")  # "a) ... (which one?)" is an option
NUMBERED = re.compile(r"^\s*\d+[.)]\s+\*\*")
HEADING = re.compile(r"^\s*(#+\s|\*\*[^*]+\*\*\s*$|\d+[.)]\s+\*\*)")


def _base(workspace: Path, path: str) -> str:
    """Return the text of `path` in the first commit that added it, or "" if no commit did."""
    added = subprocess.run(["git", "log", "--diff-filter=A", "--format=%H", "--", path],
                           cwd=workspace, capture_output=True, text=True).stdout.split()
    shown = subprocess.run(["git", "show", f"{added[-1]}:{path}"], cwd=workspace,
                           capture_output=True, text=True) if added else None
    return shown.stdout if shown and shown.returncode == 0 else ""


def _new_lines(workspace: Path, path: str) -> list[str]:
    """Return the lines of `path` that are not lines of the ticket before the run."""
    target = workspace / path
    old = {line.strip() for line in _base(workspace, path).splitlines()}
    return [line for line in target.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and line.strip() not in old] if target.is_file() else []


def says_ready(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The report says that the ticket is ready, and no line says that it is not."""
    text = os.environ.get(REPORT_ENV, "")
    if negative := NOT_READY.search(text):
        return False, f"the report says '{negative.group(0)}'"
    ready = bool(READY.search(text))
    return ready, "the report says ready" if ready else "the report does not say ready"


def not_invented(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """No new value for a field in `fields` (regexes), unless it is a placeholder.

    A field is a `Field: value` line, or a heading or a label line with the value on the lines
    after it, up to a blank line or the next label. A line of the ticket before the run is not new.
    """
    target = workspace / args["path"]
    if not target.is_file():
        return True, "no ticket file"
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    old = {line.strip() for line in _base(workspace, args["path"]).splitlines()}
    invented = []
    for field in args["fields"]:
        label = re.compile(rf"^\s*(?:#+\s*|[-*]\s*)?\**\s*(?:{field})\s*\**\s*:?\s*\**\s*(.*)$",
                           re.I)
        for index, line in enumerate(lines):
            match = label.match(line)
            if not match:
                continue
            values = [match.group(1)] if line.strip() not in old else []
            for after in lines[index + 1:] if not match.group(1).strip() else []:
                if not after.strip() or re.match(r"^\s*(#|\**[A-Z][\w -]*:)", after):
                    break
                if after.strip() not in old:
                    values.append(after)
            invented += [value.strip() for value in values
                         if value.strip() and not PLACEHOLDER.search(value)]
    return not invented, ("new field value: " + "; ".join(invented))[:200] if invented else (
        "no invented field value")


def no_new_match(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """No line that the run added to `path` has the regex `pattern`. A placeholder line is not
    counted: a proposal marked as an open question is not a requirement."""
    pattern = re.compile(args["pattern"], re.I)
    hits = [line.strip() for line in _new_lines(workspace, args["path"])
            if pattern.search(line) and not PLACEHOLDER.search(line)]
    return (False, "new line: " + hits[0][:120]) if hits else (True, "no new match")


def _units(text: str) -> list[tuple[str, list[str]]]:
    """Split the report into questions. A unit is (the topic text, the lines after the question).

    A question starts at a line with "?" that is not an option, or at a numbered bold item. The
    topic text is that line and the label line before it. The unit ends at the next question, the
    next heading, or the next numbered bold item.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines)
              if ("?" in line and not OPTION.match(line)) or NUMBERED.match(line)]
    units = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        body = []
        for line in lines[start + 1:end]:
            if HEADING.match(line):
                break
            body.append(line)
        before = next((lines[i] for i in range(start - 1, -1, -1) if lines[i].strip()), "")
        topic = lines[start] + ("\n" + before if HEADING.match(before) or
                                before.rstrip(" *").endswith(":") else "")
        units.append((topic, [lines[start]] + body))
    return units


def _options(unit: list[str]) -> int:
    """Count the options of a question: list items, inline (a) marks, or "X or Y" in the line.

    "X or Y" counts on the full question line, up to its last "?".
    """
    question, body = unit[0], unit[1:]
    items = sum(1 for line in body if LIST_ITEM.match(line)
                and not NOT_OPTION.match(LIST_ITEM.sub("", line)))
    inline = len({mark.lower() for line in unit for mark in INLINE.findall(line)})
    if question.lstrip().startswith("|"):  # a table row: options in a cell, split by ";" or "/"
        cells = [cell for cell in question.split("|") if cell.strip()]
        inline = max([inline] + [len(re.split(r";|<br>| / ", cell)) for cell in cells[1:]])
    alternatives = len(re.findall(r"\bor\b", question.rsplit("?", 1)[0])) + 1
    return max(items, inline, alternatives if alternatives > 1 else 0)


def asks_with_options(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """For each topic (a regex), the report asks a question about it with 2 or more options."""
    units = _units(os.environ.get(REPORT_ENV, ""))
    missing = []
    for topic in args["topics"]:
        pattern = re.compile(topic, re.I)
        best = max((_options(lines) for text, lines in units if pattern.search(text)), default=-1)
        if best < 2:
            missing.append(f"{topic} ({'no question' if best < 0 else f'{best} option(s)'})")
    return not missing, ("no question with 2 or more options for: " + ", ".join(missing)
                         if missing else f"{len(args['topics'])} question(s) with options")


def dor_form(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """`path` has one `## Definition of Ready` section with each field line, in order, filled.

    Acceptance criteria has one or more `- ` items. Each persona ID is in `personas`, or is none.
    """
    target = workspace / args["path"]
    if not target.is_file():
        return False, "no ticket file"
    text = target.read_text(encoding="utf-8", errors="replace")
    sections = re.findall(r"^## Definition of Ready\s*$\n(.*?)(?=^#{1,2} |\Z)", text, re.M | re.S)
    if len(sections) != 1:
        return False, f"{len(sections)} '## Definition of Ready' sections"
    lines = sections[0].splitlines()
    position = 0
    for field in FIELDS:
        hit = next((i for i in range(position, len(lines))
                    if re.match(rf"^{re.escape(field)}:", lines[i])), -1)
        if hit < 0:
            return False, f"no '{field}:' line after the earlier fields"
        value = lines[hit][len(field) + 1:].strip()
        if field == "Acceptance criteria":
            following = [line for line in lines[hit + 1:] if line.strip()]
            if not following or not following[0].startswith("- "):
                return False, "no '- ' item after 'Acceptance criteria:'"
        elif not value:
            return False, f"'{field}:' has no value"
        if field == "Personas":
            ids = [part.strip().strip("`") for part in value.split(",")]
            unknown = [i for i in ids if i not in args.get("personas", []) and i != "none"]
            if unknown:
                return False, f"unknown persona ID: {', '.join(unknown)}"
        position = hit + 1
    return True, "the section has each field, in order"


GRADERS = {"asks_with_options": asks_with_options, "dor_form": dor_form,
           "no_new_match": no_new_match, "not_invented": not_invented, "says_ready": says_ready}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=sorted(GRADERS))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--args", default="{}")
    options = parser.parse_args()
    try:
        args = json.loads(options.args)
        if not isinstance(args, dict):
            raise TypeError("--args must be a JSON object")
        passed, detail = GRADERS[options.name](options.workspace, args)
    except (KeyError, TypeError, ValueError, OSError, re.error) as error:  # bad args
        passed, detail = False, f"the grader input is not valid: {error!r}"
    print(json.dumps({"pass": passed, "detail": detail}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
