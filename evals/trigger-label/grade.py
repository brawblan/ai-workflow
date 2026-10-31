"""Custom checks for the label trigger eval. `stone eval` runs this file once for each grader check.

Usage: grade.py <name> --workspace <path> --args <json>. The last line of the output is JSON:
{"pass": true|false, "detail": "..."}. The report is in STONE_EVAL_REPORT: the `report` field of
the structured output for `with`, the final text for `without`. The posted text is in
STONE_EVAL_POSTED, and each call of the fake forge CLI is in STONE_EVAL_GH_CALLS (D101).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from stone import trigger_eval

REPORT_ENV, POSTED_ENV, CALLS_ENV = "STONE_EVAL_REPORT", "STONE_EVAL_POSTED", "STONE_EVAL_GH_CALLS"
NOT_READY = re.compile(r"\bnot (yet )?(ready|complete)|\bincomplete\b|"
                       r"(does not|doesn.t|do not|don.t) (yet )?meet", re.I)
MISSING = re.compile(r"\bmissing\b|\babsent\b|\bnot (given|provided|stated|defined)\b", re.I)
READY = re.compile(r"\bready\b|\bmeets\b|\bcomplete\b", re.I)
CLAIMS_READY = re.compile(r"\b(is|as|marked|looks) (now )?ready\b", re.I)
NEGATION = re.compile(r"\bnot\b|n.t\b|\bno\b", re.I)
# A line that says that nothing is missing: "No Definition of Ready field is missing", "Missing
# fields: none", "not a missing field" (found in the run of 2026-10-31).
NONE_MISSING = re.compile(r"\b(no|none of the|nothing)\b[^.\n]{0,40}\bmissing\b|"
                          r"\bnone (is |are )?missing|\bmissing( fields?)?\W+none\b|"
                          r"\bnot a missing\b", re.I)
ASKS = re.compile(r"\?\s*\**\s*$|\bquestions? (for|to) the author\b", re.I)


def _report() -> str:
    return os.environ.get(REPORT_ENV, "")


def _missing(text: str) -> re.Match[str] | None:
    """The first "missing" word on a line that does not say that nothing is missing."""
    for line in text.splitlines():
        found = MISSING.search(line)
        if found and not NONE_MISSING.search(line):
            return found
    return None


def says_ready(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The report says that the ticket is ready, and no line says that it is not or that a
    field is missing."""
    text = _report()
    if negative := NOT_READY.search(text) or _missing(text):
        return False, f"the report says '{negative.group(0)}'"
    ready = bool(READY.search(text))
    return ready, "the report says ready" if ready else "the report does not say ready"


def not_ready(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The report says that the ticket is not ready or that a field is missing, and no line says
    that the ticket is ready."""
    text = _report()
    for line in text.splitlines():
        if CLAIMS_READY.search(line) and not NEGATION.search(line):
            return False, f"a line says ready: {line.strip()[:80]!r}"
    found = NOT_READY.search(text) or _missing(text)
    return bool(found), (f"the report says '{found.group(0)}'" if found
                         else "the report does not say that the ticket is not ready")


def names_missing(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The report names each field in `topics` (regexes)."""
    text = _report()
    absent = [topic for topic in args["topics"] if not re.search(topic, text, re.I)]
    return not absent, (f"not named: {absent}" if absent else "each missing field is named")


def no_question(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """No line of the report asks a question. No human is in the job (the profile steps)."""
    asked = [line.strip() for line in _report().splitlines() if ASKS.search(line)]
    return not asked, (f"{len(asked)} question(s), first: {asked[0][:80]!r}" if asked
                       else "no question")


def posted_framed(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The post job posted the report on the issue, with the framing of D38."""
    return trigger_eval.framed(os.environ.get(POSTED_ENV, ""), _report(), args["role"],
                               os.environ.get(CALLS_ENV, ""), args["call"])


GRADERS = {"names_missing": names_missing, "no_question": no_question, "not_ready": not_ready,
           "posted_framed": posted_framed, "says_ready": says_ready}


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
