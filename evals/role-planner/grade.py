"""Custom checks for the role.planner eval. `stone eval` runs this file once for each grader check.

Usage: grade.py <name> --workspace <path> --args <json>. The last line of the output is JSON:
{"pass": true|false, "detail": "..."}. The environment variable STONE_EVAL_REPORT has the final
text of the run (D33). No grader changes the workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from stone import specs

REPORT_ENV = "STONE_EVAL_REPORT"
JOB_STORY = re.compile(r"\b[a-z][a-z0-9-]*\.J[1-9]\d*\b")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s")
# A label line starts a block in text with no heading: a bold line, or a short line that ends in ":".
LABEL = re.compile(r"^\s{0,3}(\*\*[^*]+\*\*:?|__[^_]+__:?|[^.:!?|]{1,60}:)\s*$")
# A line of the report that names a gap: a question, or words that say that the ticket is not clear.
ASKS = re.compile(r"\?|question|unclear|not clear|ambiguous|unspecified|undefined|"
                  r"(does|do|did) not (say|state|specify|define|cover)|decide|confirm|clarif",
                  re.I)


def _read(workspace: Path, path: str) -> str | None:
    target = workspace / path
    return target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None


def _level(line: str) -> int:
    """Return the heading level of the line, or 0 if it is not a heading."""
    match = HEADING.match(line)
    return len(match[1]) if match else 0


def _blocks(text: str, word: str) -> list[str]:
    """Return each block of the text whose first line has `word` in it.

    A heading block ends at the next heading of the same or a higher level. A label block ends at
    the next heading or label. A label in a heading block is part of that block.
    """
    blocks: list[str] = []
    current: list[str] | None = None
    level = 0  # the level of the open heading block, or 0 for a label block
    for line in text.splitlines():
        new = _level(line)
        starts = (new and (not level or new <= level)) or (LABEL.match(line) and not (
            current is not None and level))
        if starts:
            if current is not None:
                blocks.append("\n".join(current))
            current = [line] if word in line.lower() else None
            level = new if current is not None else 0
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append("\n".join(current))
    return blocks


def _section(text: str, word: str) -> str | None:
    """Return the body of the first heading section with `word` in its heading.

    The section ends at the next heading of the same or a higher level.
    """
    lines = text.splitlines()
    for start, line in enumerate(lines):
        level = _level(line)
        if level and word in line.lower():
            end = next((i for i in range(start + 1, len(lines))
                        if 0 < _level(lines[i]) <= level), len(lines))
            return "\n".join(lines[start + 1:end])
    return None


def job_story_ids(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The coverage section of the plan names a job story on at least `min` lines.

    Each job story ID in the section must be in the personas file (default
    constitution/personas.md).
    """
    plan = _read(workspace, args["path"])
    if plan is None:
        return False, f"no file {args['path']}"
    personas = _read(workspace, args.get("personas", "constitution/personas.md")) or ""
    known = set(JOB_STORY.findall(personas))
    section = _section(plan, "coverage")
    if section is None:
        return False, "the plan has no coverage section"
    lines = [line for line in section.splitlines() if set(JOB_STORY.findall(line)) & known]
    unknown = sorted(set(JOB_STORY.findall(section)) - known)
    minimum = int(args.get("min", 1))
    detail = f"{len(lines)} line(s) with a job story ID, {minimum} needed"
    if unknown:
        return False, f"{detail}; not in the personas file: {', '.join(unknown)}"
    return len(lines) >= minimum, detail


def names_gap(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The run names the gap (`pattern`) as an open question.

    It passes if an open questions section of a plan that matches the glob `path` has the pattern,
    or if the report has it in an open questions block or on a line that asks.
    """
    pattern = re.compile(args["pattern"], re.I)
    for path in sorted(workspace.glob(args["path"])):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(pattern.search(block) for block in _blocks(text, "question")):
                return True, f"the open questions of {path.name} name the gap"
    report = os.environ.get(REPORT_ENV, "")
    if any(pattern.search(block) for block in _blocks(report, "question")):
        return True, "the open questions of the report name the gap"
    for line in report.splitlines():
        if pattern.search(line) and ASKS.search(line):
            return True, f"the report asks: {line.strip()[:80]}"
    return False, "no open question names the gap"


def new_ids(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The delta at `path` adds a `capability` requirement with a number that no other delta used."""
    path = workspace / args["path"]
    if not path.is_file():
        return False, f"no file {args['path']}"
    capability = args["capability"]
    used: dict[str, str] = {}
    for other in sorted(path.parent.glob("*" + specs.DELTA_SUFFIX)):
        if other.resolve() != path.resolve():
            for change in specs.parse_delta(other).changes:
                used.setdefault(change.id, other.name)
    added = [change.id for change in specs.parse_delta(path).changes
             if change.op == "ADDED" and change.id.startswith(capability + ".R")]
    if not added:
        return False, f"the delta adds no {capability} requirement"
    reused = [f"{rid} (used in {used[rid]})" for rid in added if rid in used]
    if reused:
        return False, "a number is used again: " + ", ".join(reused)
    return True, "ADDED " + ", ".join(added)


GRADERS = {"job_story_ids": job_story_ids, "names_gap": names_gap, "new_ids": new_ids}


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
    except (KeyError, TypeError, ValueError, OSError, re.error) as error:  # bad args, no file
        passed, detail = False, f"the grader input is not valid: {error!r}"
    print(json.dumps({"pass": passed, "detail": detail}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
