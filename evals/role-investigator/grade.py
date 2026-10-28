"""Custom checks for the role.investigator eval. `stone eval` runs this file once for each grader check.

Usage: grade.py <name> --workspace <path> --args <json>. The last line of the output is JSON:
{"pass": true|false, "detail": "..."}. The final text of the run is in STONE_EVAL_REPORT. A check
reads the text in sections: a section starts at a heading, a bold line, a numbered item, or a
table row, and it ends at the next one. One finding is in one section.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPORT_ENV = "STONE_EVAL_REPORT"
# A "- **Where:**" item is a field of the finding above it, so a list item does not start one.
START = re.compile(r"^\s*(#+\s|\*\*[^*]+\*\*:?\s*$|(\*\*)?\d+[.)]\s|\|)")
SEVERITY = re.compile(r"\b(critical|blocker|blocking|high|major|medium|moderate|low|minor|"
                      r"severity|P[0-3]|sev\s*\d)\b", re.I)
LOCATION = re.compile(r"\.py\S*:\d+|\.py\W{0,4}(lines?|L)\s*\d+|\blines?\s+\d+|#L\d+|\bL\d+\b",
                      re.I)


def _sections(text: str) -> list[str]:
    """Split the text at each line that starts a section."""
    sections: list[list[str]] = [[]]
    for line in text.splitlines():
        if START.match(line) and sections[-1]:
            sections.append([])
        sections[-1].append(line)
    return ["\n".join(lines) for lines in sections if any(line.strip() for line in lines)]


def _texts(workspace: Path, args: dict[str, Any]) -> list[str]:
    """Return the file `path` if args has one. Else the final text and each file under `paths`."""
    if "path" in args:
        target = workspace / args["path"]
        return [target.read_text(encoding="utf-8", errors="replace")] if target.is_file() else []
    texts = [os.environ.get(REPORT_ENV, "")]
    for folder in args.get("paths", []):
        texts += [p.read_text(encoding="utf-8", errors="replace")
                  for p in sorted((workspace / folder).rglob("*")) if p.is_file()]
    return texts


def _matching(workspace: Path, args: dict[str, Any], patterns: list[str]) -> list[str]:
    compiled = [re.compile(pattern, re.I) for pattern in patterns]
    return [section for text in _texts(workspace, args) for section in _sections(text)
            if all(pattern.search(section) for pattern in compiled)]


def finding(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """One section of the final text, or of a file under `paths`, matches each regex in `all`."""
    hits = _matching(workspace, args, args["all"])
    return (True, "found: " + " ".join(hits[0].split())[:160]) if hits else (
        False, "no section matches all of: " + "; ".join(args["all"]))


def finding_form(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """A section of the file `path` that matches `topic` gives a severity and a file and line."""
    if not (workspace / args["path"]).is_file():
        return False, f"no file {args['path']}"
    hits = _matching(workspace, args, [args["topic"]])
    if not hits:
        return False, "no section names the topic"
    good = [s for s in hits if SEVERITY.search(s) and LOCATION.search(s)]
    if good:
        return True, "severity and location: " + " ".join(good[0].split())[:160]
    return False, (f"{len(hits)} section(s) name the topic, none with a severity and a "
                   "file and line")


GRADERS = {"finding": finding, "finding_form": finding_form}


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
