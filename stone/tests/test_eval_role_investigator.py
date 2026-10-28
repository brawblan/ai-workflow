"""Tests for the role.investigator eval in evals/role-investigator/. Each case runs grade.py as a
subprocess with the final text in STONE_EVAL_REPORT. No model starts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from stone import evals

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "evals" / "role-investigator"
ROLE_FILE = ".claude/agents/investigator.md"
LOC = "`src/notes.py:20`"


class InvestigatorCase(unittest.TestCase):
    def grade(self, name: str, args: dict[str, Any] | str, report: str = "",
              files: dict[str, str] | None = None) -> tuple[bool, str]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ws = Path(tmp.name)
        for rel, text in (files or {}).items():
            (ws / rel).parent.mkdir(parents=True, exist_ok=True)
            (ws / rel).write_text(text, encoding="utf-8")
        raw = args if isinstance(args, str) else json.dumps(args)
        done = subprocess.run([sys.executable, str(EVAL / "grade.py"), name, "--workspace", str(ws),
                               "--args", raw], capture_output=True, text=True, timeout=120,
                              env={**os.environ, "STONE_EVAL_REPORT": report})
        data = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertIsInstance(data["pass"], bool)
        self.assertIsInstance(data["detail"], str)
        return data["pass"], data["detail"]

    def expect(self, name: str, args: dict[str, Any], cases: list[tuple[str, bool, str]],
               in_file: bool = False) -> None:
        for label, expected, text in cases:
            with self.subTest(label):
                if in_file:
                    passed, detail = self.grade(name, args, "", {"docs/reports/R.md": text})
                else:
                    passed, detail = self.grade(name, args, text)
                self.assertEqual(passed, expected, detail)

    def test_scenarios_and_workspaces(self) -> None:
        data = evals.load_scenarios(EVAL)
        self.assertEqual([s["id"] for s in data["scenarios"]], ["V1", "V2", "V3"])
        for scenario in data["scenarios"]:
            for variant in ("with", "without"):
                with self.subTest(f"{scenario['id']} {variant}"):
                    ws = evals.prepare(EVAL, scenario, REPO / "framework", ROLE_FILE, variant).path
                    self.addCleanup(shutil.rmtree, ws.parent, True)
                    self.assertEqual((ws / ROLE_FILE).exists(), variant == "with")

    def test_finding_needs_one_section(self) -> None:
        self.expect("finding", {"all": ["alpha", "beta"]}, [
            ("same heading", True, "## One\nalpha and beta"),
            ("bold line", True, "**Issue**\nalpha\nbeta"),
            ("numbered item", True, "1. alpha beta\n2. other"),
            ("table row", True, "| x | alpha | beta |"),
            ("list field stays in section", True, "## One\nalpha\n- **Severity:** beta"),
            ("different headings", False, "## One\nalpha\n## Two\nbeta"),
            ("different numbered items", False, "1. alpha\n2. beta"),
            ("different rows", False, "| alpha |\n| beta |"),
            ("none", False, "nothing")])

    def test_finding_reads_files_under_paths(self) -> None:
        args = {"all": ["alpha", "beta"], "paths": ["docs/reports"]}
        for label, expected, text in [("same section", True, "## A\nalpha beta"),
                                      ("split sections", False, "## A\nalpha\n## B\nbeta")]:
            with self.subTest(label):
                passed, detail = self.grade("finding", args, "", {"docs/reports/R.md": text})
                self.assertEqual(passed, expected, detail)

    def test_finding_form(self) -> None:
        self.expect("finding_form", {"path": "docs/reports/R.md", "topic": "alpha"}, [
            ("severity and file:line", True, f"## F\nalpha is High {LOC}"),
            ("table row with line", True, "| alpha | high | src/notes.py line 20 |"),
            ("list item fields", True, f"**1. alpha**\n- **Severity:** high\n- **Where:** {LOC}"),
            ("no file line", False, "## F\nalpha is high"),
            ("no severity", False, f"## F\nalpha {LOC}"),
            ("form in other section", False, f"## F\nalpha\n## G\nhigh {LOC}"),
            ("no topic", False, f"## F\nbeta high {LOC}")], in_file=True)

    def test_finding_form_links_severity_by_file_and_line(self) -> None:
        topic = f"## Cause\nalpha is the cause at {LOC}\n\n"
        self.expect("finding_form", {"path": "docs/reports/R.md", "topic": "alpha"}, [
            ("severity row, same file and line", True, topic + "| F1 | `src/notes.py:20` | High |"),
            ("severity row, other line", False, topic + "| F1 | `src/notes.py:14` | High |"),
            ("confidence section only", False,
             topic + "## Confidence\nHigh, src/notes.py:20 is the line.")], in_file=True)

    def test_finding_form_reads_only_the_file(self) -> None:
        args = {"path": "docs/reports/R.md", "topic": "alpha"}
        passed, detail = self.grade("finding_form", args, f"## F\nalpha high {LOC}")
        self.assertFalse(passed, detail)
        self.assertIn("no file", detail)

    def test_bad_args_do_not_crash(self) -> None:
        for name, args in [("finding", "[]"), ("finding", {}), ("finding", {"all": ["("]}),
                           ("finding", "not json"), ("finding_form", "[]"), ("finding_form", {}),
                           ("finding_form", {"path": "x.md", "topic": "("})]:
            with self.subTest(f"{name} {args}"):
                passed, detail = self.grade(name, args, "## F\nalpha high src/notes.py:1",
                                            {"x.md": "## F\nalpha"})
                self.assertFalse(passed)
                self.assertIn("the grader input is not valid", detail)


if __name__ == "__main__":
    unittest.main()
