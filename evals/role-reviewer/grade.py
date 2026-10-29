"""Custom checks for the role.reviewer eval. `stone eval` runs this file once for each grader check.

Usage: grade.py <name> --workspace <path> --args <json>. The last line of the output is JSON:
{"pass": true|false, "detail": "..."}. The final text of the run is in STONE_EVAL_REPORT. A check
reads the report in sections: a section starts at a heading, a bold line, a numbered item, or a
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
SEVERITY = re.compile(r"\b(critical|blocker|blocking|high|major|medium|moderate|low|minor|nit|"
                      r"severity|P[0-3]|sev\s*\d)\b", re.I)
_S = r"(critical|blocker|blocking|high|major|medium|moderate)\b"
SERIOUS = re.compile(rf"\b{_S}", re.I)
LOCATION = re.compile(r"\.py\S*:\d+|\.py\W{0,4}(lines?|L)\s*\d+|\blines?\s+\d+|#L\d+|\bL\d+\b",
                      re.I)
# Words that rate the review or deny a finding, not a finding: "Confidence: high", "risk is
# low", "no high or medium findings", "Severity: none".
NOT_FINDING = re.compile(
    r"\b(confidence|risks?)\b\W{0,4}(level\W*)?(is\W*)?(very\s+)?(high|medium|moderate|low)\b|"
    r"\b(high|medium|moderate|low)\b\W{0,4}(confidence|risk)\b|"
    rf"\b(no|zero|0|none|without)\b[^.\n]{{0,40}}?\b{_S}(\W+(or|and|nor|,)?\W*{_S})*|"
    r"severity\W{0,4}(none|n/a)", re.I)
RATING = re.compile(r"^\W*(confidence|open risks?|risks?)\b", re.I)


def _sections(text: str) -> list[str]:
    """Split the report at each line that starts a section."""
    sections: list[list[str]] = [[]]
    for line in text.splitlines():
        if START.match(line) and sections[-1]:
            sections.append([])
        sections[-1].append(line)
    return ["\n".join(lines) for lines in sections if any(line.strip() for line in lines)]


def _matching(patterns: list[str]) -> list[str]:
    compiled = [re.compile(pattern, re.I) for pattern in patterns]
    return [section for section in _sections(os.environ.get(REPORT_ENV, ""))
            if all(pattern.search(section) for pattern in compiled)]


def finding(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """One section of the report matches each regex in `all`."""
    hits = _matching(args["all"])
    return (True, "found: " + " ".join(hits[0].split())[:160]) if hits else (
        False, "no section matches all of: " + "; ".join(args["all"]))


def finding_form(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """A section that matches `topic` gives a severity and a location (a file and a line)."""
    hits = _matching([args["topic"]])
    if not hits:
        return False, "no section names the topic"
    good = [s for s in hits if SEVERITY.search(s) and LOCATION.search(s)]
    if good:
        return True, "severity and location: " + " ".join(good[0].split())[:160]
    return False, (f"{len(hits)} section(s) name the topic, none with a severity and a "
                   "file and line")


def no_finding(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """No section gives a location and a severity of medium or higher. A section about the
    confidence or the open risks is not a finding. A low or minor note is not counted."""
    for section in _sections(os.environ.get(REPORT_ENV, "")):
        if RATING.match(section.lstrip("#*-| ")):
            continue
        text = NOT_FINDING.sub(" ", section)
        if SERIOUS.search(text) and LOCATION.search(text):
            return False, "a finding: " + " ".join(section.split())[:160]
    return True, "no finding of medium or higher severity"


GRADERS = {"finding": finding, "finding_form": finding_form, "no_finding": no_finding}


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
