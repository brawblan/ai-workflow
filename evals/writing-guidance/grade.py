"""Custom checks for the guidance.writing eval. `stone eval` runs this file once for each grader check.

Usage: grade.py <name> --workspace <path> --args <json>. The last line of the output is JSON:
{"pass": true|false, "detail": "..."}. The environment variable STONE_EVAL_REPORT has the final
text of the run. No grader changes the workspace.

The K17 rules come from `grader-ste.txt`, a pinned copy of the rules. When the live rules change, the
grader stays the same, so the results of different dates stay comparable (D69).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from stone import writing_check

REPORT_ENV = "STONE_EVAL_REPORT"
RULES = Path(__file__).resolve().parent / "grader-ste.txt"
# A first line that is a greeting or an announcement, not the answer.
PREAMBLE = re.compile(r"^\W*(sure|certainly|of course|great|okay|ok|absolutely|i['’]ll|i will|"
                      r"i['’]m going to|let me|here is|here['’]s|below is|happy to)\b", re.I)
# A last line that offers more help or asks for feedback.
CLOSING = re.compile(r"\b(let me know|feel free|hope this|would you like|happy to help|"
                     r"do you want me)\b", re.I)
WORD = re.compile(r"\S+")
# A reply that a model wraps in one code fence. K17 skips fenced text, so the fence must go first.
FENCE = re.compile(r"\A\s*(`{3,}|~{3,})[\w+-]*[ \t]*\n(.*?)\n[ \t]*\1\s*\Z", re.S)


def _report() -> str:
    """Return the final text of the run, without one fence that wraps the whole reply."""
    text = os.environ.get(REPORT_ENV, "")
    wrapped = FENCE.match(text)
    return wrapped.group(2) if wrapped else text


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _findings(rule: str | None = None) -> list[Any]:
    rules = writing_check.load_rules(RULES, None)
    found = writing_check.check_text("report.md", _report(), rules)
    return [f for f in found if rule is None or f"Rule {rule}:" in f.message]


def _by_rule(findings: list[Any]) -> str:
    counts = Counter(re.match(r"Rule (\d+):", f.message).group(1) for f in findings)  # type: ignore[union-attr]
    return ", ".join(f"rule {rule} x{n}" for rule, n in sorted(counts.items(), key=lambda i: int(i[0])))


def k17_errors(_: Path, __: dict[str, Any]) -> tuple[bool, str]:
    """No K17 finding at error level (a warning does not count). An empty report fails."""
    if not _report().strip():
        return False, "the report is empty"
    errors = [f for f in _findings() if f.severity == "error"]
    return not errors, _by_rule(errors) or "no error"


def _rule_check(rule: str) -> Any:
    def check(_: Path, __: dict[str, Any]) -> tuple[bool, str]:
        if not _report().strip():
            return False, "the report is empty"
        found = [f for f in _findings(rule) if f.severity == "error"]
        return not found, f"{len(found)} finding(s)" if found else "none"
    return check


def answer_first(_: Path, __: dict[str, Any]) -> tuple[bool, str]:
    """The first line of the report is not a greeting or an announcement."""
    lines = _lines(_report())
    if not lines:
        return False, "the report is empty"
    return not PREAMBLE.search(lines[0]), lines[0][:60]


def no_filler_close(_: Path, __: dict[str, Any]) -> tuple[bool, str]:
    """The last line of the report does not offer more help or ask for feedback."""
    lines = _lines(_report())
    if not lines:
        return False, "the report is empty"
    return not CLOSING.search(lines[-1]), lines[-1][:60]


def max_words(_: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The report has `limit` words or fewer. It also fails on an empty report."""
    count = len(WORD.findall(_report()))
    return 0 < count <= int(args["limit"]), f"{count} words, limit {args['limit']}"


GRADERS = {
    "k17_errors": k17_errors,
    "sentence_length": _rule_check("8"),
    "vague_words": _rule_check("5"),
    "paragraph_length": _rule_check("13"),
    "answer_first": answer_first,
    "no_filler_close": no_filler_close,
    "max_words": max_words,
}


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
    except (KeyError, TypeError, ValueError, OSError) as error:
        passed, detail = False, f"the grader input is not valid: {error!r}"
    print(json.dumps({"pass": passed, "detail": detail}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
