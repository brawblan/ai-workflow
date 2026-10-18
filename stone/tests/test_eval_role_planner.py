"""Tests for the role.planner eval in evals/role-planner/ (roadmap item 4c, D33).

Each grader test copies the shop fixture to a temp folder, makes a git repo of it, and writes the
planner output. Then it runs grade.py as a subprocess, as `stone eval` does, with the final text of
the run in STONE_EVAL_REPORT. No model or harness starts. Each grade.py call also checks
criterion 5: the last line is JSON with a boolean `pass` and a string `detail`, and the workspace
does not change.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from stone import cli, specs

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "evals" / "role-planner"
FIXTURE = EVAL / "fixtures" / "shop"
GRADE = EVAL / "grade.py"
REPORT_ENV = "STONE_EVAL_REPORT"
SCENARIOS = {s["id"]: s for s in
             yaml.safe_load((EVAL / "scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]}
GIT_ENV = {"GIT_AUTHOR_NAME": "tester", "GIT_AUTHOR_EMAIL": "tester@example.com",
           "GIT_COMMITTER_NAME": "tester", "GIT_COMMITTER_EMAIL": "tester@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
GRADERS = ("job_story_ids", "names_gap", "new_ids", "not_applied")
GAP = "expir|end date|last day|\\bends\\b|out of date|no longer valid"  # the P3 pattern
PLAN = "docs/plans/SHOP-12.md"
DELTA = "docs/plans/SHOP-16.spec.md"


def plan(coverage: str, *, heading: str = "## Acceptance criteria coverage",
         questions: str = "None.", approach: str = "Add a saved list to the cart.") -> str:
    """A plan with the 6 sections. `coverage` is the body of the coverage section."""
    return (f"# SHOP-12: Save for later\n\n## Understanding\n\nA shopper saves an item.\n\n"
            f"## Files to change\n\n- `src/shop/cart.py`\n\n## Approach\n\n{approach}\n\n"
            f"{heading}\n\n{coverage}\n\n## Out of scope\n\nNothing.\n\n"
            f"## Open questions\n\n{questions}\n")


def added(rid: str, title: str = "A rule") -> str:
    return (f"## ADDED {rid}: {title}\n\nThe cart MUST do it.\n\n### Scenario: It works\n\n"
            f"- WHEN a shopper does it\n- THEN it is done\n")


def delta(*blocks: str) -> str:
    return "\n".join(blocks)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                            env={**os.environ, **GIT_ENV})
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {result.stderr}")
    return result.stdout


def snapshot(ws: Path) -> dict[str, str]:
    """The hash of each file of the workspace, out of .git."""
    return {p.relative_to(ws).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ws.rglob("*")) if p.is_file() and ".git" not in p.relative_to(ws).parts}


def grader_checks(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in scenario["expect"] if item["check"] == "grader"]


def grader_args(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in {"check", "kind", "name"}}


class GraderCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.count = 0

    def workspace(self, files: dict[str, str] | None = None, committed: bool = False) -> Path:
        """The shop fixture as a git repo, then `files` (path: text), as the planner output."""
        self.count += 1
        ws = self.tmp / f"ws{self.count}"
        shutil.copytree(FIXTURE, ws)
        git(ws, "init", "-q", "-b", "main")
        git(ws, "add", "-A")
        git(ws, "commit", "-q", "-m", "chore: fixture base")
        for rel, text in (files or {}).items():
            (ws / rel).parent.mkdir(parents=True, exist_ok=True)
            (ws / rel).write_text(text, encoding="utf-8")
        if files and committed:
            git(ws, "add", "-A")
            git(ws, "commit", "-q", "-m", "docs: plan")
        return ws

    def grade(self, name: str, ws: Path, args: dict[str, Any] | str,
              report: str | None = "") -> tuple[bool, str]:
        """Run grade.py as `stone eval` does. A str `args` goes to --args as it is.

        `report` is the value of STONE_EVAL_REPORT. None removes the variable.
        """
        env = {k: v for k, v in os.environ.items() if k != REPORT_ENV}
        if report is not None:
            env[REPORT_ENV] = report
        before_status, before_files = git(ws, "status", "--porcelain", "--ignored"), snapshot(ws)
        raw = args if isinstance(args, str) else json.dumps(args)
        result = subprocess.run(
            [sys.executable, str(GRADE), name, "--workspace", str(ws), "--args", raw],
            cwd=EVAL, capture_output=True, text=True, timeout=600, env=env)
        self.assertEqual(git(ws, "status", "--porcelain", "--ignored"), before_status,
                         f"{name} changed the workspace")
        self.assertEqual(snapshot(ws), before_files, f"{name} changed a file of the workspace")
        lines = result.stdout.strip().splitlines()
        self.assertTrue(lines, f"no output: {result.stderr}")
        data = json.loads(lines[-1])
        self.assertIsInstance(data.get("pass"), bool, data)
        self.assertIsInstance(data.get("detail"), str, data)
        return data["pass"], data["detail"]

    def expect(self, expected: bool, name: str, ws: Path, args: dict[str, Any] | str,
               report: str | None = "") -> str:
        passed, detail = self.grade(name, ws, args, report)
        self.assertEqual(passed, expected, detail)
        return detail


# Criterion 2: job_story_ids ----------------------------------------------------------------------


class JobStoryIdsTest(GraderCase):
    def check(self, expected: bool, text: str, **args: Any) -> str:
        ws = self.workspace({PLAN: text})
        return self.expect(expected, "job_story_ids", ws, {"path": PLAN, **args})

    def test_c2_one_line_for_each_criterion_passes_min_3(self) -> None:
        coverage = ("1. Save for later: `shopper.J2`. Unit test.\n"
                    "2. Not in the total: `shopper.J3`. Unit test.\n"
                    "3. Move back to the cart: `shopper.J1`. Unit test.")
        self.check(True, plan(coverage), min=3)

    def test_c2_min_counts_lines_not_ids(self) -> None:
        coverage = "1. Save for later: shopper.J1, shopper.J2, shopper.J3."
        self.check(True, plan(coverage), min=1)
        self.check(False, plan(coverage), min=2)

    def test_c2_fewer_lines_than_min_fails(self) -> None:
        coverage = "1. Save: shopper.J2.\n2. Total: shopper.J3.\n3. Move back: no job story."
        self.check(True, plan(coverage), min=2)
        self.check(False, plan(coverage), min=3)

    def test_c2_min_defaults_to_1(self) -> None:
        self.check(True, plan("1. Save: shopper.J2."))
        self.check(False, plan("1. Save: no job story."))

    def test_c2_missing_plan_fails(self) -> None:
        self.expect(False, "job_story_ids", self.workspace(), {"path": PLAN})

    def test_c2_no_coverage_heading_fails(self) -> None:
        text = plan("1. Save: shopper.J2.", heading="## Acceptance criteria")
        self.check(False, text)

    def test_c2_coverage_word_in_body_text_is_not_a_heading(self) -> None:
        text = plan("1. Save: shopper.J2.", heading="## Acceptance criteria\n\nThe coverage:")
        self.check(False, text)

    def test_c2_heading_word_case_does_not_matter(self) -> None:
        self.check(True, plan("1. Save: shopper.J2.", heading="## Acceptance Criteria Coverage"))
        self.check(True, plan("1. Save: shopper.J2.", heading="### COVERAGE"))

    def test_c2_ids_out_of_the_coverage_section_do_not_count(self) -> None:
        text = plan("1. Save: no job story.", approach="This is for shopper.J2 and shopper.J3.",
                    questions="Is shopper.J1 the job?")
        self.check(False, text)

    def test_c2_a_sub_heading_is_part_of_the_section(self) -> None:
        coverage = ("### Criterion 1\n\n- shopper.J2\n\n### Criterion 2\n\n- shopper.J3\n\n"
                    "#### Criterion 3\n\n- shopper.J1")
        self.check(True, plan(coverage), min=3)

    def test_c2_section_ends_at_the_next_heading_of_the_same_level(self) -> None:
        text = ("# P\n\n## Acceptance criteria coverage\n\n1. Save: shopper.J2.\n\n"
                "## Out of scope\n\nshopper.J3 later.\nshopper.J1 later.\n")
        self.check(True, text, min=1)
        self.check(False, text, min=2)

    def test_c2_section_ends_at_the_next_heading_of_a_higher_level(self) -> None:
        text = ("# P\n\n## Plan\n\n### Coverage\n\n1. Save: shopper.J2.\n\n"
                "## Other\n\nshopper.J3 here.\n\n# Notes\n\nshopper.J1 here.\n")
        self.check(True, text, min=1)
        self.check(False, text, min=2)

    def test_c2_id_not_in_the_personas_file_fails(self) -> None:
        coverage = "1. Save: shopper.J2.\n2. Total: shopper.J3.\n3. Move back: shopper.J9."
        detail = self.check(False, plan(coverage), min=1)
        self.assertIn("shopper.J9", detail)

    def test_c2_id_of_a_persona_that_is_not_in_the_file_fails(self) -> None:
        coverage = "1. Save: shopper.J2.\n2. Pay: admin.J1."
        self.assertIn("admin.J1", self.check(False, plan(coverage), min=1))

    def test_c2_unknown_id_in_a_sub_heading_part_fails(self) -> None:
        coverage = "1. Save: shopper.J2.\n\n### Notes\n\n- shopper.J7"
        self.check(False, plan(coverage), min=1)

    def test_c2_unknown_id_out_of_the_section_does_not_fail(self) -> None:
        self.check(True, plan("1. Save: shopper.J2.", approach="Not for shopper.J9."))

    def test_c2_personas_arg_gives_the_personas_file(self) -> None:
        personas = "# Personas\n\n- jobs:\n  - admin.J1: When I run the shop, I want it.\n"
        ws = self.workspace({PLAN: plan("1. Pay: admin.J1."), "docs/people.md": personas})
        self.expect(False, "job_story_ids", ws, {"path": PLAN})
        self.expect(True, "job_story_ids", ws, {"path": PLAN, "personas": "docs/people.md"})
        ws2 = self.workspace({PLAN: plan("1. Save: shopper.J2."), "docs/people.md": personas})
        self.expect(False, "job_story_ids", ws2, {"path": PLAN, "personas": "docs/people.md"})


# Criterion 3: names_gap -------------------------------------------------------------------------


class NamesGapTest(GraderCase):
    PATH = "docs/plans/SHOP-14*.md"

    def check(self, expected: bool, files: dict[str, str] | None = None, report: str = "",
              pattern: str = GAP, path: str = PATH) -> str:
        ws = self.workspace(files)
        return self.expect(expected, "names_gap", ws, {"path": path, "pattern": pattern}, report)

    def plan_file(self, questions: str, approach: str = "Lower the amount by the percent.") -> dict:
        return {"docs/plans/SHOP-14.md": plan("1. shopper.J3.", questions=questions,
                                              approach=approach)}

    # a: a block of a file
    def test_c3a_open_questions_heading_of_the_plan_names_the_gap(self) -> None:
        self.check(True, self.plan_file("- What must amount_due do with an expired code?"))

    def test_c3a_question_block_need_not_ask_with_a_question_mark(self) -> None:
        self.check(True, self.plan_file("- The ticket has no rule for the end date of a code."))

    def test_c3a_bold_label_line_starts_a_questions_block(self) -> None:
        text = "Plan for SHOP-14.\n\n**Open questions**\n\n- An expired code: refuse it or not.\n"
        self.check(True, {"docs/plans/SHOP-14.md": text})

    def test_c3a_short_line_that_ends_in_a_colon_starts_a_questions_block(self) -> None:
        text = "Plan for SHOP-14.\n\nQuestions for the owner:\n- An expired code: refuse it.\n"
        self.check(True, {"docs/plans/SHOP-14.md": text})

    def test_c3a_a_sub_heading_is_part_of_the_questions_block(self) -> None:
        self.check(True, self.plan_file("### Codes\n\n- The rule for an expired code."))

    def test_c3a_pattern_is_case_insensitive(self) -> None:
        self.check(True, self.plan_file("- The EXPIRY of a code."))
        self.check(True, self.plan_file("- The expiry of a code."), pattern="EXPIR")

    def test_c3a_each_file_that_matches_the_glob_counts(self) -> None:
        files = {"docs/plans/SHOP-14.md": plan("1. shopper.J3."),
                 "docs/plans/SHOP-14-notes.md": "## Open questions\n\n- Expired codes.\n"}
        self.check(True, files)

    def test_c3a_a_file_that_does_not_match_the_glob_does_not_count(self) -> None:
        files = {"docs/plans/SHOP-14.md": plan("1. shopper.J3."),
                 "docs/notes/SHOP-14.md": "## Open questions\n\n- Expired codes.\n",
                 "docs/plans/SHOP-15.md": "## Open questions\n\n- Expired codes.\n"}
        self.check(False, files)

    def test_c3a_no_file_matches_and_no_report_fails(self) -> None:
        self.check(False)

    def test_c3_plan_section_that_is_not_a_questions_section_does_not_count(self) -> None:
        files = self.plan_file("None.", approach="An expired code raises UnknownCode. Is it OK?")
        self.check(False, files)

    def test_c3_questions_section_ends_at_the_next_heading(self) -> None:
        text = ("# P\n\n## Open questions\n\nNone.\n\n## Notes\n\n"
                "- What does an expired code do?\n")
        self.check(False, {"docs/plans/SHOP-14.md": text})

    def test_c3_label_block_that_is_not_questions_does_not_count(self) -> None:
        text = "Open questions:\n- None.\nApproach:\n- An expired code raises UnknownCode.\n"
        self.check(False, {"docs/plans/SHOP-14.md": text})

    # b: a questions block of the report
    def test_c3b_open_questions_heading_of_the_report_names_the_gap(self) -> None:
        report = "Plan written.\n\n## Open questions\n\n- Expired codes: no rule in the ticket.\n"
        self.check(True, report=report)

    def test_c3b_label_line_of_the_report_starts_a_questions_block(self) -> None:
        self.check(True, report="No plan.\n\nOpen questions:\n- The end date of a code.\n")
        self.check(True, report="No plan.\n\n**Questions**\n- The end date of a code.\n")

    def test_c3b_report_block_that_is_not_questions_does_not_count(self) -> None:
        report = "## Summary\n\nExpired codes raise UnknownCode.\n\n## Open questions\n\nNone.\n"
        self.check(False, report=report)

    def test_c3b_report_questions_label_block_ends_at_the_next_label(self) -> None:
        self.check(False, report="Open questions:\n- None.\nSummary:\nExpired codes are refused.\n")

    # c: a report line that asks
    def test_c3c_report_line_with_the_pattern_that_asks_passes(self) -> None:
        lines = ("What must amount_due do with an expired code?",
                 "The ticket does not say what an expired code does.",
                 "It is unclear what occurs after the end date of a code.",
                 "The owner must decide what an expired code does.",
                 "Please confirm the rule for an expired code.")
        for line in lines:
            with self.subTest(line=line):
                self.check(True, report=f"I did not write a plan.\n{line}\nDone.")

    def test_c3c_report_line_with_the_pattern_that_does_not_ask_fails(self) -> None:
        for line in ("Expired codes raise UnknownCode in the plan.",
                     "I added a check for the end date of a code."):
            with self.subTest(line=line):
                self.check(False, report=f"Plan written.\n{line}\nDone.")

    def test_c3c_the_ask_and_the_pattern_must_be_on_one_line(self) -> None:
        self.check(False, report="Is the plan correct?\nExpired codes raise UnknownCode.\n")

    def test_c3_no_report_variable_is_an_empty_report(self) -> None:
        ws = self.workspace()
        self.expect(False, "names_gap", ws, {"path": self.PATH, "pattern": GAP}, report=None)
        ws = self.workspace(self.plan_file("- An expired code?"))
        self.expect(True, "names_gap", ws, {"path": self.PATH, "pattern": GAP}, report=None)


# Criterion 3, round 2: the changed names_gap rules (a to d) -------------------------------------


class NamesGapRound2Test(GraderCase):
    """The rules of the changed criterion 3. A file test has an empty report."""

    PATH = "docs/plans/SHOP-14*.md"
    FILE = "docs/plans/SHOP-14.md"

    def check(self, expected: bool, files: dict[str, str] | None = None,
              report: str = "") -> str:
        ws = self.workspace(files)
        return self.expect(expected, "names_gap", ws, {"path": self.PATH, "pattern": GAP}, report)

    def file(self, expected: bool, text: str) -> str:
        return self.check(expected, {self.FILE: text})

    def report(self, expected: bool, text: str) -> str:
        return self.check(expected, report=text)

    # a: a list item is not a label
    def test_c3a_r2_list_item_that_ends_in_a_colon_stays_in_the_questions_block(self) -> None:
        text = "Open questions:\n- Codes:\n  - What does an expired code do\n"
        self.file(True, text)
        self.report(True, text)

    def test_c3a_r2_numbered_list_item_that_ends_in_a_colon_stays_in_the_block(self) -> None:
        text = "Open questions:\n1. Codes:\n   1. The end date of a code\n"
        self.file(True, text)
        self.report(True, text)

    def test_c3a_r2_list_item_with_question_and_a_colon_does_not_start_a_block(self) -> None:
        # If "- Open questions:" were a label, the next line would be in a questions block.
        for marker in ("-", "*", "+", "1.", "2)"):
            text = f"Approach:\n{marker} Open questions:\n- An expired code raises UnknownCode.\n"
            with self.subTest(marker=marker):
                self.file(False, text)
                self.report(False, text)

    def test_c3a_r2_bold_and_short_colon_lines_are_still_labels(self) -> None:
        self.file(True, "Plan.\n\n**Open questions**\n- The end date of a code.\n")
        self.file(True, "Plan.\n\n__Questions__:\n- The end date of a code.\n")
        self.file(True, "Plan.\n\nOpen questions:\n- The end date of a code.\n")

    # b: where a block ends
    def test_c3b_r2_heading_block_ends_at_a_heading_of_a_higher_level(self) -> None:
        self.file(False, "# P\n\n## Open questions\n\nNone.\n\n# Notes\n\n- The end date of a code.\n")

    def test_c3b_r2_heading_block_does_not_end_at_a_heading_of_a_lower_level(self) -> None:
        self.file(True, "# P\n\n## Open questions\n\nNone.\n\n### Codes\n\n- The end date of a code.\n")

    def test_c3b_r2_heading_block_does_not_end_at_a_blank_line_and_a_paragraph(self) -> None:
        self.file(True, "## Open questions\n\nCodes.\n\nThe ticket gives no end date for a code.\n")

    def test_c3b_r2_label_in_a_heading_block_is_part_of_that_block(self) -> None:
        self.file(True, "## Open questions\n\nCodes:\n- The end date of a code.\n")
        self.file(True, "## Open questions\n\n**Codes**\n\nThe end date of a code.\n")

    def test_c3b_r2_label_block_ends_at_a_blank_line_and_then_a_line_that_is_not_a_list_item(
            self) -> None:
        text = "Open questions:\n- None.\n\nI chose to refuse an expired code.\n"
        self.file(False, text)
        self.report(False, text)

    def test_c3b_r2_label_block_goes_on_at_a_blank_line_and_then_a_list_item(self) -> None:
        for item in ("- The end date of a code.", "2. The end date of a code."):
            with self.subTest(item=item):
                self.file(True, f"Open questions:\n- Codes.\n\n{item}\n")

    def test_c3b_r2_label_block_ends_at_the_next_heading(self) -> None:
        text = "Open questions:\n- None.\n## Approach\n- Expired codes are refused.\n"
        self.file(False, text)
        self.report(False, text)

    def test_c3b_r2_label_block_ends_at_the_next_label(self) -> None:
        self.file(False, "Open questions:\n- None.\n**Approach**\n- Expired codes are refused.\n")

    # c: which lines of a questions block count
    def test_c3c_r2_none_line_in_a_questions_block_does_not_count(self) -> None:
        text = "## Open questions\n\nNone. Expired codes are refused (assumed).\n"
        self.file(False, text)
        self.report(False, text)

    def test_c3c_r2_line_that_starts_with_no_or_na_does_not_count(self) -> None:
        for line in ("No. Expired codes are refused.", "N/A. Expired codes are refused.",
                     "No open question: expired codes are refused.",
                     "- None. Expired codes are refused.", "- N/A: the end date of a code."):
            with self.subTest(line=line):
                self.file(False, f"## Open questions\n\n{line}\n")
                self.report(False, f"Open questions:\n{line}\n")

    def test_c3c_r2_the_first_line_of_the_block_does_not_count(self) -> None:
        self.file(False, "## Open questions on expired codes\n\nNone.\n")
        self.file(False, "Questions about the end date:\n- None.\n")
        self.report(False, "**Open questions on expired codes**\n- None.\n")

    def test_c3c_r2_line_after_the_first_with_the_pattern_counts(self) -> None:
        self.file(True, "## Open questions\n\nNone for the cart.\n- The end date of a code.\n")

    # d: a report line that asks
    def test_c3d_r2_each_ask_word_asks(self) -> None:
        words = ("unclear", "not clear", "ambiguous", "unspecified", "undefined", "decide",
                 "confirm", "clarify", "clarification")
        for word in words:
            with self.subTest(word=word):
                self.report(True, f"Plan written.\nThe rule for an expired code: {word} here.\n")

    def test_c3d_r2_each_does_not_say_form_asks(self) -> None:
        for verb in ("does", "do", "did"):
            for word in ("say", "state", "specify", "define", "cover"):
                with self.subTest(form=f"{verb} not {word}"):
                    self.report(True, f"The tickets {verb} not {word} the end date of a code.\n")

    def test_c3d_r2_a_question_mark_asks(self) -> None:
        self.report(True, "Should an expired code be refused?")

    def test_c3d_r2_the_word_question_does_not_ask(self) -> None:
        for line in ("There are no questions about expired codes.",
                     "I have a question list for expired codes in the plan.",
                     "The question of the end date is in the plan."):
            with self.subTest(line=line):
                self.report(False, f"Plan written.\n{line}\n")

    def test_c3d_r2_past_tense_does_not_ask(self) -> None:
        for line in ("I decided that an expired code raises UnknownCode.",
                     "I confirmed that an expired code is refused.",
                     "I clarified the end date of a code in the plan."):
            with self.subTest(line=line):
                self.report(False, f"Plan written.\n{line}\n")

    def test_c3d_r2_ask_word_must_be_a_whole_word(self) -> None:
        for line in ("The tests confirmed that expired codes are refused.",
                     "The planner decides that expired codes are refused.",
                     "The code has a clarifying note on its end date."):
            with self.subTest(line=line):
                self.report(False, f"Plan written.\n{line}\n")

    def test_c3d_r2_report_line_that_starts_with_none_no_or_na_does_not_ask(self) -> None:
        for line in ("No open questions. Expired codes raise UnknownCode.",
                     "No rule covers an expired code. What must it do?",
                     "None: is the end date of a code unclear?",
                     "N/A: is the end date of a code in scope?"):
            with self.subTest(line=line):
                self.report(False, f"Plan written.\n{line}\n")

    def test_c3d_r2_ticket_examples(self) -> None:
        self.report(False, "No open questions. Expired codes raise UnknownCode.")
        self.report(False, "Open questions:\n- None.\n\nI chose to refuse an expired code.")
        self.report(False, "I decided that an expired code raises UnknownCode.")
        self.report(True, "Open questions:\n- Codes:\n  - What does an expired code do")
        self.report(True, "Should an expired code be refused?")


# Criterion 3, round 3: "None", "No", and "N/A" are whole words -------------------------------------


class NamesGapRound3Test(GraderCase):
    """The changed criteria 3c and 3d. A file test has an empty report."""

    PATH = NamesGapRound2Test.PATH
    FILE = NamesGapRound2Test.FILE
    check = NamesGapRound2Test.check
    file = NamesGapRound2Test.file
    report = NamesGapRound2Test.report

    EXAMPLE = "Nonexistent end date: what does an expired code do?"  # the ticket example
    # Lines that start with a longer word and do not ask. They isolate rule 3c from rule 3d.
    LONGER = ("Nonexistent end date for a code.",
              "Notes on the end date of a code.",
              "Nothing in the ticket gives an end date for a code.",
              "Nobody owns the end date of a code.",
              "Non-expired and expired codes have one rule.",
              "- Nothing in the ticket gives an end date for a code.",
              "1. Notes on the end date of a code.")
    # Lines that start with the whole word, with a mark after it.
    WHOLE = ("None, the end date of a code is in the ticket.",
             "None - the end date of a code is in the ticket.",
             "No, the end date of a code is in the ticket.",
             "No: the end date of a code is in the ticket.",
             "N/A - the end date of a code is in the ticket.",
             "- No, the end date of a code is in the ticket.",
             "**None.** The end date of a code is in the ticket.")

    # 3c: a line of a questions block
    def test_c3c_r3_ticket_example_in_a_questions_block_passes(self) -> None:
        self.file(True, f"## Open questions\n\n{self.EXAMPLE}\n")
        self.file(True, f"## Open questions\n\n- {self.EXAMPLE}\n")
        self.file(True, f"Plan.\n\nOpen questions:\n- {self.EXAMPLE}\n")
        self.report(True, f"Plan written.\n\nOpen questions:\n- {self.EXAMPLE}\n")

    def test_c3c_r3_line_that_starts_with_a_longer_word_counts(self) -> None:
        for line in self.LONGER:
            with self.subTest(line=line):
                self.file(True, f"## Open questions\n\n{line}\n")
                self.report(True, f"Plan written.\n\nOpen questions:\n{line}\n")

    def test_c3c_r3_line_that_starts_with_the_whole_word_does_not_count(self) -> None:
        for line in self.WHOLE:
            with self.subTest(line=line):
                self.file(False, f"## Open questions\n\n{line}\n")
                self.report(False, f"Plan written.\n\nOpen questions:\n{line}\n")

    def test_c3c_r3_a_longer_word_line_does_not_count_out_of_a_questions_block(self) -> None:
        for line in self.LONGER:
            with self.subTest(line=line):
                self.file(False, f"## Approach\n\n{line}\n")

    # 3d: a report line that asks
    def test_c3d_r3_ticket_example_asks_in_the_report(self) -> None:
        self.report(True, f"Plan written.\n{self.EXAMPLE}\n")

    def test_c3d_r3_report_line_that_asks_and_starts_with_a_longer_word_asks(self) -> None:
        for line in ("Nothing in the ticket gives an end date. What must an expired code do?",
                     "Notes: the end date of a code is unclear.",
                     "Nobody said what an expired code does. Please confirm.",
                     "Nonexistent end date: the owner must decide what an expired code does."):
            with self.subTest(line=line):
                self.report(True, f"Plan written.\n{line}\n")

    def test_c3d_r3_report_line_that_asks_and_starts_with_the_whole_word_does_not_ask(
            self) -> None:
        for line in ("No, what does an expired code do?",
                     "None - is the end date of a code unclear?",
                     "N/A, the end date of a code is unclear.",
                     "- No: please confirm the rule for an expired code."):
            with self.subTest(line=line):
                self.report(False, f"Plan written.\n{line}\n")


# Criterion 4: new_ids ---------------------------------------------------------------------------


class NewIdsTest(GraderCase):
    def check(self, expected: bool, text: str | None, extra: dict[str, str] | None = None,
              capability: str = "cart") -> str:
        files = dict(extra or {})
        if text is not None:
            files[DELTA] = text
        ws = self.workspace(files)
        return self.expect(expected, "new_ids", ws, {"path": DELTA, "capability": capability})

    def test_c4_added_id_with_a_new_number_passes(self) -> None:
        self.check(True, delta(added("cart.R3", "A gift note")))

    def test_c4_missing_delta_fails(self) -> None:
        self.check(False, None)

    def test_c4_added_id_that_an_added_change_used_fails(self) -> None:
        self.assertIn("cart.R1", self.check(False, delta(added("cart.R1"))))

    def test_c4_added_id_that_was_removed_fails(self) -> None:
        # SHOP-3 added cart.R2, and SHOP-8 removed it.
        self.assertIn("cart.R2", self.check(False, delta(added("cart.R2"))))

    def test_c4_id_used_only_by_a_removed_change_fails(self) -> None:
        other = "---\napply_order: 3\n---\n\n## REMOVED cart.R5: Old rule\n\nNot needed.\n"
        self.check(False, delta(added("cart.R5")), {"docs/plans/SHOP-9.spec.md": other})

    def test_c4_id_used_only_by_a_modified_change_fails(self) -> None:
        other = ("## MODIFIED cart.R6: A rule\n\nThe cart MUST do it.\n\n### Scenario: It works\n\n"
                 "- WHEN a shopper does it\n- THEN it is done\n")
        self.check(False, delta(added("cart.R6")), {"docs/plans/SHOP-9.spec.md": other})

    def test_c4_one_reused_id_fails_the_delta(self) -> None:
        self.check(False, delta(added("cart.R3"), added("cart.R2")))

    def test_c4_no_added_change_fails(self) -> None:
        modified = ("## MODIFIED cart.R1: Add an item\n\nThe cart MUST add it.\n\n"
                    "### Scenario: It works\n\n- WHEN a shopper adds it\n- THEN it is in the cart\n")
        self.check(False, modified)

    def test_c4_added_id_of_another_capability_does_not_count(self) -> None:
        self.check(False, delta(added("checkout.R1")))
        self.check(False, delta(added("cart.R3")), capability="car")

    def test_c4_same_number_of_another_capability_is_not_a_reuse(self) -> None:
        self.check(True, delta(added("cart.R3")),
                   {"docs/plans/SHOP-9.spec.md": delta(added("checkout.R3"))})

    def test_c4_a_delta_in_another_folder_does_not_count(self) -> None:
        self.check(True, delta(added("cart.R3")),
                   {"docs/archive/SHOP-9.spec.md": delta(added("cart.R3"))})

    def test_c4_a_delta_that_is_not_applied_also_counts(self) -> None:
        # Another new delta in the same folder (no apply_order) uses cart.R4, so the delta must not.
        self.check(False, delta(added("cart.R4")),
                   {"docs/plans/SHOP-17.spec.md": delta(added("cart.R4"))})
        self.check(True, delta(added("cart.R3")),
                   {"docs/plans/SHOP-17.spec.md": delta(added("cart.R4"))})


# Criterion 9: not_applied -----------------------------------------------------------------------


def front(*lines: str) -> str:
    return "---\n" + "\n".join(lines) + "\n---\n\n"


class NotAppliedTest(GraderCase):
    def check(self, expected: bool, text: str | None, committed: bool = False) -> str:
        ws = self.workspace({DELTA: text} if text is not None else None, committed)
        return self.expect(expected, "not_applied", ws, {"path": DELTA})

    def test_c9_delta_with_no_frontmatter_passes(self) -> None:
        self.check(True, delta(added("cart.R3")))

    def test_c9_delta_with_frontmatter_but_no_apply_order_passes(self) -> None:
        self.check(True, front("ticket: SHOP-16") + delta(added("cart.R3")))

    def test_c9_delta_with_apply_order_fails(self) -> None:
        for order in ("3", "1", "99"):
            with self.subTest(order=order):
                self.check(False, front(f"apply_order: {order}") + delta(added("cart.R3")))

    def test_c9_delta_with_apply_order_among_other_keys_fails(self) -> None:
        self.check(False, front("ticket: SHOP-16", "apply_order: 3") + delta(added("cart.R3")))

    def test_c9_apply_order_that_is_not_a_valid_number_still_fails(self) -> None:
        for value in ("0", "x", "-1", "2.5", "true"):
            with self.subTest(value=value):
                self.check(False, front(f"apply_order: {value}") + delta(added("cart.R3")))

    def test_c9_apply_order_key_with_no_value_fails(self) -> None:
        # The ticket: the delta must have no apply_order in its frontmatter.
        self.check(False, front("apply_order:") + delta(added("cart.R3")))

    def test_c9_apply_order_in_the_body_is_not_frontmatter(self) -> None:
        body = delta(added("cart.R3")) + "\nThe old deltas have apply_order: 1 and 2.\n"
        self.check(True, body)

    def test_c9_missing_delta_fails(self) -> None:
        self.check(False, None)

    def test_c9_a_folder_at_the_path_fails(self) -> None:
        ws = self.workspace({DELTA + "/x.md": "text\n"})
        self.expect(False, "not_applied", ws, {"path": DELTA})

    def test_c9_committed_delta_is_graded_the_same(self) -> None:
        self.check(True, delta(added("cart.R3")), committed=True)
        self.check(False, front("apply_order: 3") + delta(added("cart.R3")), committed=True)

    def test_c9_an_old_applied_delta_in_the_fixture_fails(self) -> None:
        self.expect(False, "not_applied", self.workspace(), {"path": "docs/plans/SHOP-3.spec.md"})


# Criterion 5: output and no workspace change ----------------------------------------------------


class OutputTest(GraderCase):
    ARGS = {"job_story_ids": {"path": PLAN},
            "names_gap": {"path": "docs/plans/*.md", "pattern": GAP},
            "new_ids": {"path": DELTA, "capability": "cart"},
            "not_applied": {"path": DELTA}}

    def full(self, committed: bool = False) -> Path:
        files = {PLAN: plan("1. shopper.J2.", questions="- An expired code?"),
                 DELTA: delta(added("cart.R3"))}
        return self.workspace(files, committed)

    def test_c5_each_grader_prints_json_and_does_not_change_an_uncommitted_workspace(self) -> None:
        ws = self.full()
        self.assertIn("docs/plans/", git(ws, "status", "--porcelain"))
        for name in GRADERS:
            with self.subTest(name=name):
                self.expect(True, name, ws, self.ARGS[name], report="Open questions:\n- expiry")

    def test_c5_each_grader_does_not_change_a_committed_workspace(self) -> None:
        ws = self.full(committed=True)
        for name in GRADERS:
            with self.subTest(name=name):
                self.expect(True, name, ws, self.ARGS[name])

    def test_c5_args_that_are_not_json_give_a_json_failure(self) -> None:
        ws = self.full()
        for name in GRADERS:
            for raw in ("{not json", "", "path=x"):
                with self.subTest(name=name, args=raw):
                    self.expect(False, name, ws, raw)

    def test_c5_args_that_are_not_an_object_give_a_json_failure(self) -> None:
        ws = self.full()
        for name in GRADERS:
            for raw in ("[]", '"docs/plans/SHOP-12.md"', "3", "null"):
                with self.subTest(name=name, args=raw):
                    self.expect(False, name, ws, raw)

    def test_c5_a_missing_key_gives_a_json_failure(self) -> None:
        ws = self.full()
        for name, args in self.ARGS.items():
            for key in args:
                with self.subTest(name=name, missing=key):
                    self.expect(False, name, ws, {k: v for k, v in args.items() if k != key})

    def test_c5_a_regex_that_is_not_valid_gives_a_json_failure(self) -> None:
        ws = self.full()
        for pattern in ("(expir", "[a-", "*expir"):
            with self.subTest(pattern=pattern):
                self.expect(False, "names_gap", ws, {"path": "docs/plans/*.md", "pattern": pattern},
                            report="What does an expired code do?")

    def test_c5_an_absolute_glob_gives_a_json_failure(self) -> None:
        ws = self.full()
        self.expect(True, "names_gap", ws, {"path": "docs/plans/*.md", "pattern": GAP})
        for path in (f"{ws.as_posix()}/docs/plans/*.md", f"{ws.as_posix()}/docs/plans/SHOP-12.md",
                     "/docs/plans/*.md"):
            with self.subTest(path=path):
                self.expect(False, "names_gap", ws, {"path": path, "pattern": GAP})

    def test_c5_not_applied_bad_input_gives_a_json_failure(self) -> None:
        ws = self.full()
        for args in ({}, {"file": DELTA}, {"path": 3}, {"path": None}):
            with self.subTest(args=args):
                self.expect(False, "not_applied", ws, args)


# Criterion 6: the eval and the fixture are valid ------------------------------------------------


class FixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.copy = Path(tmp.name) / "shop"
        shutil.copytree(FIXTURE, self.copy)

    def run_cli(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_c6_check_only_exits_0(self) -> None:
        code, out = self.run_cli("eval", "role.planner", "--root", str(REPO), "--check-only")
        self.assertEqual(code, 0, out)

    def test_c6_each_scenario_uses_the_shop_fixture(self) -> None:
        self.assertEqual(sorted(SCENARIOS), ["P1", "P2", "P3", "P4", "P5"])
        for sid, scenario in SCENARIOS.items():
            with self.subTest(scenario=sid):
                self.assertTrue((EVAL / scenario["fixture"]).resolve() == FIXTURE.resolve())

    def test_c6_fixture_has_the_app_slice_profile(self) -> None:
        config = yaml.safe_load((FIXTURE / ".cornerstone/config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(config["profiles"], ["app-slice"])

    def test_c6_render_on_a_copy_writes_the_planner_role(self) -> None:
        code, out = self.run_cli("render", "--root", str(self.copy),
                                 "--framework", str(REPO / "framework"))
        self.assertEqual(code, 0, out)
        self.assertTrue((self.copy / ".claude/agents/planner.md").is_file(), out)
        self.assertFalse((FIXTURE / ".claude").exists(), "render changed the fixture itself")

    def test_c6_applied_deltas_replay_to_the_specs_with_no_drift(self) -> None:
        self.assertEqual(specs.check(self.copy), [])
        cart = (self.copy / "docs/specs/cart.md").read_text(encoding="utf-8")
        self.assertIn("## cart.R1:", cart)
        self.assertNotIn("cart.R2", cart)

    def test_c6_spec_sync_on_a_copy_changes_no_file(self) -> None:
        before = snapshot(self.copy)
        code, out = self.run_cli("spec", "sync", "--root", str(self.copy))
        self.assertEqual(code, 0, out)
        self.assertEqual(snapshot(self.copy), before, out)

    def test_c6_the_old_deltas_used_r1_and_r2_and_r2_is_removed(self) -> None:
        ops = {(c.op, c.id) for path in sorted((FIXTURE / "docs/plans").glob("*.spec.md"))
               for c in specs.parse_delta(path).changes}
        self.assertEqual(ops, {("ADDED", "cart.R1"), ("ADDED", "cart.R2"),
                               ("REMOVED", "cart.R2")})


# Criterion 7: check kinds -----------------------------------------------------------------------


class KindTest(unittest.TestCase):
    FORMAT_CHECKS = {"sections_in_order", "json_valid", "spec_delta_valid"}
    FORMAT_GRADERS = {"job_story_ids", "not_applied"}

    def is_format(self, item: dict[str, Any]) -> bool:
        if item["check"] == "grader":
            return item["name"] in self.FORMAT_GRADERS
        return item["check"] in self.FORMAT_CHECKS

    def test_c7_format_checks_are_contract_and_other_checks_are_outcome(self) -> None:
        for sid, scenario in SCENARIOS.items():
            for item in scenario["expect"]:
                with self.subTest(scenario=sid, check=item["check"], name=item.get("name")):
                    expected = "contract" if self.is_format(item) else "outcome"
                    self.assertEqual(item.get("kind", "outcome"), expected)

    def test_c7_each_scenario_has_an_outcome_check(self) -> None:
        for sid, scenario in SCENARIOS.items():
            with self.subTest(scenario=sid):
                self.assertTrue(any(item.get("kind", "outcome") == "outcome"
                                    for item in scenario["expect"]))


# The scenario grader checks against plausible planner output ------------------------------------


class ScenarioGraderTest(GraderCase):
    def item(self, sid: str, name: str) -> dict[str, Any]:
        return next(i for i in grader_checks(SCENARIOS[sid]) if i["name"] == name)

    def test_p1_plan_with_a_job_story_for_each_criterion_passes(self) -> None:
        coverage = ("1. Save for later: `shopper.J2`.\n2. Not in the total: `shopper.J3`.\n"
                    "3. Move back: `shopper.J1`.")
        item = self.item("P1", "job_story_ids")
        self.expect(True, "job_story_ids", self.workspace({PLAN: plan(coverage)}),
                    grader_args(item))
        two = "1. Save for later: `shopper.J2`.\n2. Not in the total: `shopper.J3`.\n3. Move back."
        self.expect(False, "job_story_ids", self.workspace({PLAN: plan(two)}), grader_args(item))

    def test_p3_plan_or_report_that_asks_about_an_expired_code_passes(self) -> None:
        args = grader_args(self.item("P3", "names_gap"))
        questions = "- Each code has an end date. What must amount_due do after it?"
        files = {"docs/plans/SHOP-14.md": plan("1. shopper.J3.", questions=questions)}
        self.expect(True, "names_gap", self.workspace(files), args)
        self.expect(True, "names_gap", self.workspace(),
                    args, report="The ticket does not say what an expired code does.")
        self.expect(False, "names_gap", self.workspace({"docs/plans/SHOP-14.md": plan("1. x")}),
                    args, report="Plan written at docs/plans/SHOP-14.md.")

    def test_c9_each_scenario_not_applied_check_fails_a_copied_apply_order(self) -> None:
        items = [(sid, i) for sid, s in SCENARIOS.items() for i in grader_checks(s)
                 if i["name"] == "not_applied"]
        self.assertTrue(items, "no scenario has a not_applied check")
        for sid, item in items:
            args = grader_args(item)
            text = delta(added("cart.R3", "A gift note"))
            with self.subTest(scenario=sid):
                self.expect(True, "not_applied", self.workspace({args["path"]: text}), args)
                self.expect(False, "not_applied",
                            self.workspace({args["path"]: front("apply_order: 3") + text}), args)

    def test_p3_ticket_example_outputs_that_decide_the_gap_fail(self) -> None:
        args = grader_args(self.item("P3", "names_gap"))
        weak = [({"docs/plans/SHOP-14.md": plan(
                     "1. shopper.J3.", questions="None. Expired codes are refused (assumed).")},
                 "Plan written."),
                ({}, "No open questions. Expired codes raise UnknownCode."),
                ({}, "Open questions:\n- None.\n\nI chose to refuse an expired code."),
                ({}, "I decided that an expired code raises UnknownCode.")]
        for files, report in weak:
            with self.subTest(report=report):
                self.expect(False, "names_gap", self.workspace(files), args, report=report)

    def test_p5_delta_with_r3_passes_and_with_r2_fails(self) -> None:
        args = grader_args(self.item("P5", "new_ids"))
        self.expect(True, "new_ids", self.workspace({DELTA: added("cart.R3", "A gift note")}),
                    args)
        self.expect(False, "new_ids", self.workspace({DELTA: added("cart.R2", "A gift note")}),
                    args)


if __name__ == "__main__":
    unittest.main()
