"""Tests for the role.reviewer eval in evals/role-reviewer/. Each case runs grade.py as a
subprocess with the final text of the run in STONE_EVAL_REPORT. No model starts. The graders read
only the report, so the workspace is a temp dir. Each call checks that the workspace does not
change and that the last output line is JSON."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "evals" / "role-reviewer"
SCENARIOS = {s["id"]: s for s in
             yaml.safe_load((EVAL / "scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]}
STRONG = {
    "R1": "## Findings\n\n**1. High: wrong note deleted (`src/notes.py:20`)**\n\n`delete` runs "
          "`del self.items[number]`, a 0-based index. It should be `del self.items[number - 1]`.\n\n"
          "## Confidence and open risks for G4\nI am confident in finding 1.",
    "R2": "## Findings\n\n**1. Medium: scope drift (`src/notes.py:25`)**\n\nThe change adds "
          "Notes.clear(), which the ticket does not ask for.\n",
    "R3": "## Findings\n\n**1. Medium: no test for criterion 2 (`tests/test_notes.py:30`)**\n\n"
          "No test checks the case: search(\"idea\") is not tested.\n"}
PARTIAL = {"R1": "The delete method uses items[number], the wrong note goes.",
           "R2": "The change adds a clear method that is not part of the ticket.",
           "R3": "Criterion 2, the case rule, has no test."}
WEAK = "Looks good. Approve."
R4_CLEAN = ("**Verdict: no findings.** I found no defects.\n\n| # | Criterion | Code | Test |\n"
            "|---|---|---|---|\n| 1 | count() returns 0 | `src/notes.py:16-18` | test_count |\n\n"
            "### Confidence\nHigh.\n\n### Open risks for G4\n- I had no decision log.")


def check_args(sid: str, name: str) -> dict[str, Any]:
    item = next(i for i in SCENARIOS[sid]["expect"] if i.get("name") == name)
    return {k: v for k, v in item.items() if k not in {"check", "kind", "name"}}


class ReviewerCase(unittest.TestCase):
    def grade(self, name: str, args: dict[str, Any] | str, report: str) -> tuple[bool, str]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ws = Path(tmp.name)
        (ws / "keep.txt").write_text("x", encoding="utf-8")
        raw = args if isinstance(args, str) else json.dumps(args)
        done = subprocess.run([sys.executable, str(EVAL / "grade.py"), name, "--workspace", str(ws),
                               "--args", raw], capture_output=True, text=True, timeout=120,
                              env={**os.environ, "STONE_EVAL_REPORT": report})
        self.assertEqual([p.name for p in ws.iterdir()], ["keep.txt"])
        data = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertIsInstance(data["pass"], bool)
        self.assertIsInstance(data["detail"], str)
        return data["pass"], data["detail"]

    def expect(self, name: str, args: dict[str, Any], cases: list[tuple[str, bool, str]]) -> None:
        for label, expected, report in cases:
            with self.subTest(label):
                passed, detail = self.grade(name, args, report)
                self.assertEqual(passed, expected, detail)

    def test_finding_needs_one_section(self) -> None:
        args = {"all": ["alpha", "beta"]}
        self.expect("finding", args, [
            ("same heading section", True, "## One\nalpha and beta"),
            ("bold line", True, "**Issue**\nalpha\nbeta"),
            ("numbered item", True, "1. alpha beta\n2. other"),
            ("table row", True, "| x | alpha | beta |"),
            ("different headings", False, "## One\nalpha\n## Two\nbeta"),
            ("different numbered items", False, "1. alpha\n2. beta"),
            ("bold numbered items", False, "**1. alpha**\n**2. beta**"),
            ("different rows", False, "| alpha |\n| beta |"),
            ("none", False, "nothing")])

    def test_finding_form(self) -> None:
        loc = "at src/notes.py:20"
        self.expect("finding_form", {"topic": "alpha"}, [
            ("severity and file:line", True, f"## F\nalpha is High {loc}"),
            ("severity and line n", True, "## F\nalpha, severity minor, line 20"),
            ("no severity", False, f"## F\nalpha {loc}"),
            ("no location", False, "## F\nalpha is high"),
            ("form in other section", False, f"## F\nalpha\n## G\nhigh {loc}"),
            ("no topic", False, f"## F\nbeta high {loc}")])

    def test_finding_form_evidence_field(self) -> None:
        report = "**1. Major: scope drift (`src/notes.py:20-22`)**\n\n- **Evidence:** adds `def clear(self)`."
        self.assertTrue(self.grade("finding_form", check_args("R2", "finding_form"), report)[0])

    def test_no_finding(self) -> None:
        for label, expected, report in [
                ("clean R4", True, R4_CLEAN), ("no findings", True, "No findings"),
                ("confidence high", True, "Confidence: high"), ("risk low", True, "The risk is low"),
                ("no high or medium", True, "No high or medium findings"),
                ("low with location", True, "## Note\nLow: style at src/notes.py:20"),
                    ("coverage table", True, "| 1 | count | src/notes.py:16 | test |"),
                ("confidence section", True, "Confidence: high, see src/notes.py:3"),
                ("open risks section", True, "Open risks\nhigh effort, src/notes.py:3"),
                ("medium with location", False, "## F\nMedium: bug at src/notes.py:20"),
                ("critical with line", False, "**Critical** bug on line 20"),
                ("blocking", False, "1. Blocking defect in src/notes.py:7"),
                ("major in a table row", False, "| major | src/notes.py:7 |"),
                ("moderate", False, "## F\nModerate: src/notes.py:7")]:
            with self.subTest(label):
                passed, detail = self.grade("no_finding", {}, report)
                self.assertEqual(passed, expected, detail)

    def test_bad_args_do_not_crash(self) -> None:
        for name, args in [("finding", {}), ("finding", {"all": ["("]}), ("finding", "not json"),
                           ("finding_form", {"topic": "("}), ("finding_form", {})]:
            with self.subTest(f"{name} {args}"):
                passed, detail = self.grade(name, args, "## F\nalpha high src/notes.py:1")
                self.assertFalse(passed)
                self.assertIn("the grader input is not valid", detail)

    def test_calibration(self) -> None:
        for sid in ("R1", "R2", "R3"):
            for label, report, found, form in [("strong", STRONG[sid], True, True),
                                               ("weak", WEAK, False, False),
                                               ("partial", PARTIAL[sid], True, False)]:
                for name, expected in (("finding", found), ("finding_form", form)):
                    with self.subTest(f"{sid} {label} {name}"):
                        passed, detail = self.grade(name, check_args(sid, name), report)
                        self.assertEqual(passed, expected, detail)


if __name__ == "__main__":
    unittest.main()
