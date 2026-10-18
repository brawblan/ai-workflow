"""Tests for the role.planner eval in evals/role-planner/ (roadmap item 4c, D35).

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
import re
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
GRADERS = ("job_story_ids", "names_gap", "new_ids", "not_applied", "open_question")
GAP = "expir|end date|last day|\\bends\\b|out of date|no longer valid"  # the P3 pattern
PLAN = "docs/plans/SHOP-12.md"
DELTA = "docs/plans/SHOP-16.spec.md"
# Open questions in the form of planner step 7, about the P3 gap (an expired code).
OQ_LIST = ("1. Each code has an end date. What must amount_due do with an expired code?\n"
           "   - (a) Raise UnknownCode.\n"
           "   - (b) Raise a new ExpiredCode error.\n"
           "   - Recommendation: (b), because the shopper sees why the code fails.\n"
           "   - Default until G2: the plan raises UnknownCode, as in (a).")
OQ_INLINE = ("The ticket does not say what amount_due does with an expired code. The options\n"
             "are to raise UnknownCode or to ignore the code. I recommend that it raises\n"
             "UnknownCode. The default until G2 is that the plan raises UnknownCode.")
OQ_TABLE = ("| Question | Options | Recommendation | Default until G2 |\n"
            "| --- | --- | --- | --- |\n"
            "| What does amount_due do with an expired code? | Raise UnknownCode; ignore the code "
            "| Raise UnknownCode | The plan raises UnknownCode |")


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


# EVAL-4e: open_question (planner step 7) --------------------------------------------------------


def requirement(op: str, rid: str, title: str, body: str = "The checkout MUST do it.") -> str:
    """One change of a delta. A REMOVED change has no scenario."""
    if op == "REMOVED":
        return f"## REMOVED {rid}: {title}\n\n{body}\n"
    return (f"## {op} {rid}: {title}\n\n{body}\n\n### Scenario: It works\n\n"
            f"- WHEN a shopper does it\n- THEN it is done\n")


def question(*lines: str) -> str:
    """One numbered open question with nested items."""
    first, *rest = lines
    return "\n".join([f"1. {first}", *(f"   - {line}" for line in rest)])


ASK = "What must amount_due do with an expired code?"
REC = "Recommendation: raise UnknownCode."
DEFAULT = "Default until G2: the plan raises UnknownCode."
TWO = ("(a) Raise UnknownCode.", "(b) Ignore the code.")


class OpenQuestionTest(GraderCase):
    """EVAL-4e. A file test has an empty report, and a report test has no plan file."""

    PATH = "docs/plans/SHOP-14*.md"
    FILE = "docs/plans/SHOP-14.md"
    DELTA = "docs/plans/SHOP-14.spec.md"
    DELTA_GLOB = "docs/plans/SHOP-14*.spec.md"

    def check(self, expected: bool, files: dict[str, str] | None = None, report: str | None = "",
              **extra: Any) -> str:
        args = {"path": self.PATH, "pattern": GAP, "delta": self.DELTA_GLOB, **extra}
        return self.expect(expected, "open_question", self.workspace(files), args, report)

    def plan_file(self, questions: str, approach: str = "Lower the amount by the percent.") -> dict:
        return {self.FILE: plan("1. shopper.J3.", questions=questions, approach=approach)}

    def file(self, expected: bool, questions: str, **extra: Any) -> str:
        return self.check(expected, self.plan_file(questions), **extra)

    def report(self, expected: bool, text: str, **extra: Any) -> str:
        return self.check(expected, report=text, **extra)

    def both(self, expected: bool, questions: str) -> None:
        """The questions in the plan section, and in an "Open questions:" block of the report."""
        with self.subTest(source="plan"):
            self.file(expected, questions)
        with self.subTest(source="report"):
            self.report(expected, f"Plan written at {self.FILE}.\n\nOpen questions:\n{questions}\n")

    # Criterion 2: the 3 forms ------------------------------------------------------------------
    def test_oq_c2_numbered_list_with_nested_option_items_passes(self) -> None:
        self.both(True, OQ_LIST)

    def test_oq_c2_numbered_list_with_nested_numbered_options_passes(self) -> None:
        text = ("1. What must amount_due do with an expired code?\n"
                "   - Options:\n     1. Raise UnknownCode.\n     2. Ignore the code.\n"
                f"   - {REC}\n   - {DEFAULT}")
        self.both(True, text)

    def test_oq_c2_inline_paragraph_that_wraps_passes(self) -> None:
        self.both(True, OQ_INLINE)

    def test_oq_c2_inline_text_on_one_line_passes(self) -> None:
        self.both(True, OQ_INLINE.replace("\n", " "))

    def test_oq_c2_table_with_named_columns_passes(self) -> None:
        self.both(True, OQ_TABLE)

    def test_oq_c2_table_after_a_blank_line_after_the_label_passes(self) -> None:
        for label in ("Open questions:", "**Open questions**"):
            text = f"Plan written.\n\n{label}\n\n{OQ_TABLE}\n"
            with self.subTest(label=label):
                self.report(True, text)
                self.check(True, {self.FILE: text})

    def test_oq_c2_table_with_other_columns_and_order_passes(self) -> None:
        table = ("| # | Question | Default until G2 | Recommendation | Options |\n"
                 "|:-:|:---|:---|:---|:---|\n"
                 "| 1 | The end date of a code: what then? | The plan raises UnknownCode "
                 "| ExpiredCode | (a) UnknownCode, (b) ExpiredCode |")
        self.both(True, table)

    def test_oq_c2_table_row_with_only_some_parts_fails(self) -> None:
        table = ("| Question | Options |\n| --- | --- |\n"
                 "| What does an expired code do? | Raise UnknownCode; ignore the code |")
        self.both(False, table)

    # Criterion 1: the block ----------------------------------------------------------------------
    def test_oq_c1_gap_out_of_a_questions_block_fails(self) -> None:
        self.check(False, self.plan_file("None.", approach=OQ_INLINE))
        self.check(False, {self.FILE: f"# SHOP-14\n\n## Approach\n\n{OQ_LIST}\n"})

    def test_oq_c1_a_block_with_open_or_question_in_its_first_line_counts(self) -> None:
        for heading in ("## Open questions", "## Questions", "## Open items", "### Question 1"):
            with self.subTest(heading=heading):
                self.check(True, {self.FILE: f"# SHOP-14\n\n{heading}\n\n{OQ_LIST}\n"})
        self.check(False, {self.FILE: f"# SHOP-14\n\n## Notes\n\n{OQ_LIST}\n"})

    def test_oq_c1_the_first_line_of_the_block_does_not_name_the_gap(self) -> None:
        body = "- (a) Refuse the code. (b) Ignore the code.\n- I recommend (a).\n- Default: (a)."
        detail = self.check(False, {self.FILE: f"## Open questions on expired codes\n\n{body}\n"})
        self.assertIn("gap", detail)
        self.report(False, f"**Open questions on expired codes**\n{body}\n")

    def test_oq_c1_line_that_starts_with_none_no_or_na_does_not_name_the_gap(self) -> None:
        rest = "expired codes: (a) refuse, (b) ignore. I recommend (a). Default: (a)."
        for word in ("None.", "No,", "N/A:", "- None:", "**No.**"):
            with self.subTest(word=word):
                self.both(False, f"{word} {rest}")

    def test_oq_c1_line_that_starts_with_a_longer_word_names_the_gap(self) -> None:
        line = ("Nothing in the ticket says what an expired code does. (a) Refuse it. "
                "(b) Ignore it. I recommend (a). Default until G2: (a).")
        self.both(True, line)

    def test_oq_c1_the_parts_must_be_in_one_block(self) -> None:
        text = (f"# SHOP-14\n\n## Open questions\n\n{question(ASK, *TWO, DEFAULT)}\n\n"
                f"## Questions for the owner\n\n- {REC}\n")
        self.assertIn("recommendation", self.check(False, {self.FILE: text}))

    def test_oq_c1_the_parts_must_be_in_one_source(self) -> None:
        files = self.plan_file(question(ASK, *TWO, DEFAULT))
        self.check(False, files, report="Open questions:\n- I recommend (a) for an expired code.\n")

    def test_oq_c1_a_file_that_does_not_match_the_glob_does_not_count(self) -> None:
        for rel in ("docs/plans/SHOP-15.md", "docs/notes/SHOP-14.md"):
            with self.subTest(path=rel):
                self.check(False, {rel: plan("1. shopper.J3.", questions=OQ_LIST)})

    def test_oq_c1_each_file_that_matches_the_glob_counts(self) -> None:
        self.check(True, {self.FILE: plan("1. shopper.J3."),
                          "docs/plans/SHOP-14-questions.md": f"## Open questions\n\n{OQ_LIST}\n"})

    def test_oq_c1_no_plan_and_no_report_fails(self) -> None:
        self.check(False)
        self.check(False, report=None)
        self.check(True, self.plan_file(OQ_LIST), report=None)

    # Criterion 3: the whole report ---------------------------------------------------------------
    def test_oq_c3_one_line_report_that_asks_passes(self) -> None:
        self.report(True, "The ticket does not say what an expired code does: (a) refuse it, "
                          "(b) ignore it. I recommend (a). The default until G2 is (a).")
        self.report(True, "What does an expired code do? Options: refuse it or ignore it. "
                          "I recommend refusing it. Default: refuse it.")

    def test_oq_c3_report_with_the_parts_on_other_lines_passes(self) -> None:
        self.report(True, "I wrote no plan.\n\nWhat must amount_due do with an expired code?\n\n"
                          "Options: raise UnknownCode, or ignore the code.\n\n"
                          "I recommend UnknownCode.\n\nThe default until G2 is UnknownCode.\n")

    def test_oq_c3_report_line_with_the_gap_that_does_not_ask_fails(self) -> None:
        self.report(False, "Expired codes: (a) refuse them, (b) ignore them. I recommend (a). "
                           "Default until G2: (a).")

    def test_oq_c3_the_ask_must_be_on_the_line_with_the_gap(self) -> None:
        self.report(False, "Is the plan correct?\n\nExpired codes: (a) refuse them, (b) ignore "
                           "them. I recommend (a). Default until G2: (a).\n")

    def test_oq_c3_report_line_that_asks_and_starts_with_none_does_not_count(self) -> None:
        self.report(False, "None: what does an expired code do? (a) refuse, (b) ignore. "
                           "I recommend (a). Default: (a).")

    def test_oq_c3_the_whole_text_rule_is_only_for_the_report(self) -> None:
        line = ("The ticket does not say what an expired code does: (a) refuse it, (b) ignore "
                "it. I recommend (a). The default until G2 is (a).")
        self.check(False, {self.FILE: f"# SHOP-14\n\n{line}\n"})

    # Criterion 4: the default on a line that names the gap ---------------------------------------
    NO_DEFAULT = question(ASK, *TWO, "Recommendation: (a).")

    def test_oq_c4_default_on_a_gap_line_of_the_same_plan_passes(self) -> None:
        approach = "Until G2, the plan raises UnknownCode for an expired code."
        self.check(True, self.plan_file(self.NO_DEFAULT, approach=approach))
        self.assertIn("default", self.check(False, self.plan_file(self.NO_DEFAULT)))

    def test_oq_c4_default_on_a_gap_line_of_the_same_report_passes(self) -> None:
        self.report(True, "Plan written. The default for an expired code until G2: the plan "
                          f"raises UnknownCode.\n\nOpen questions:\n{self.NO_DEFAULT}\n")

    def test_oq_c4_default_on_a_line_that_does_not_name_the_gap_fails(self) -> None:
        approach = "Until G2, the plan raises UnknownCode."
        self.check(False, self.plan_file(self.NO_DEFAULT, approach=approach))

    def test_oq_c4_default_in_a_different_source_does_not_count(self) -> None:
        self.check(False, self.plan_file(self.NO_DEFAULT),
                   report="Done. The default for an expired code is UnknownCode.")
        approach = "Until G2, the plan raises UnknownCode for an expired code."
        self.check(False, {self.FILE: plan("1. shopper.J3.", approach=approach)},
                   report=f"Open questions:\n{self.NO_DEFAULT}\n")

    def test_oq_c4_negated_default_on_a_gap_line_does_not_count(self) -> None:
        approach = "There is no default for an expired code."
        self.check(False, self.plan_file(self.NO_DEFAULT, approach=approach))

    # Criterion 5: the options --------------------------------------------------------------------
    def test_oq_c5_each_option_label_form_counts(self) -> None:
        for first, second in (("(a)", "(b)"), ("(1)", "(2)"), ("a)", "b)"), ("A.", "B."),
                              ("A:", "B:"), ("Option A:", "Option B:"),
                              ("Option 1:", "Option 2:")):
            text = question(ASK, f"{first} Raise UnknownCode.", f"{second} Ignore the code.",
                            REC, DEFAULT)
            with self.subTest(labels=(first, second)):
                self.both(True, text)

    def test_oq_c5_labels_on_one_line_count(self) -> None:
        self.both(True, question(f"{ASK} (a) Raise UnknownCode. (b) Ignore the code.",
                                 REC, DEFAULT))

    def test_oq_c5_one_label_or_the_same_label_two_times_fails(self) -> None:
        for items in (("(a) Raise UnknownCode.",),
                      ("(a) Raise UnknownCode.", "(a) Ignore the code.")):
            with self.subTest(items=items):
                detail = self.file(False, question(ASK, *items, REC, DEFAULT))
                self.assertIn("options", detail)

    def test_oq_c5_parts_after_the_word_options_count(self) -> None:
        for sep in ("; ", ", ", " or ", " / "):
            text = question(ASK, f"Options: raise UnknownCode{sep}ignore the code.", REC, DEFAULT)
            with self.subTest(sep=sep):
                self.both(True, text)

    def test_oq_c5_one_part_after_the_word_option_fails(self) -> None:
        self.file(False, question(ASK, "Option: raise UnknownCode.", REC, DEFAULT))

    def test_oq_c5_parts_end_at_a_recommendation_word(self) -> None:
        text = question(ASK, "The option I recommend is to raise UnknownCode, or to ignore it.",
                        DEFAULT)
        self.assertIn("options", self.file(False, text))

    def test_oq_c5_parts_end_at_a_default_word(self) -> None:
        text = question(ASK, "Option: raise UnknownCode. The default until G2, or until the "
                             "owner answers, is UnknownCode.", REC)
        self.assertIn("options", self.file(False, text))

    def test_oq_c5_list_items_after_an_options_line_count(self) -> None:
        text = (f"1. {ASK}\n   - Options:\n     - Raise UnknownCode.\n     - Ignore the code.\n"
                f"   - {REC}\n   - {DEFAULT}")
        self.both(True, text)

    def test_oq_c5_recommendation_and_default_items_are_not_options(self) -> None:
        text = (f"1. {ASK}\n   - Options:\n     - Raise UnknownCode.\n"
                f"     - {REC}\n     - {DEFAULT}")
        self.assertIn("options", self.file(False, text))

    def test_oq_c5_no_options_fails(self) -> None:
        self.assertIn("options", self.file(False, question(ASK, REC, DEFAULT)))

    # Criterion 6: a negated or empty recommendation or default -----------------------------------
    def test_oq_c6_negated_default_does_not_count(self) -> None:
        for line in ("No default until G2.", "There is no default.", "I have not a default.",
                     "The plan goes on without a default."):
            with self.subTest(line=line):
                self.assertIn("default", self.file(False, question(ASK, *TWO, REC, line)))

    def test_oq_c6_negated_recommendation_does_not_count(self) -> None:
        for line in ("I do not recommend an option.", "No recommendation.",
                     "I go on without a recommendation."):
            with self.subTest(line=line):
                detail = self.file(False, question(ASK, *TWO, line, DEFAULT))
                self.assertIn("recommendation", detail)

    def test_oq_c6_a_no_that_is_not_just_before_the_word_does_not_negate(self) -> None:
        line = "The ticket has no rule, so I recommend (a)."
        self.file(True, question(ASK, *TWO, line, DEFAULT))

    def test_oq_c6_empty_or_none_value_does_not_count(self) -> None:
        cases = (("recommendation", question(ASK, *TWO, "Recommendation: none.", DEFAULT)),
                 ("recommendation", question(ASK, *TWO, "Recommendation: N/A", DEFAULT)),
                 ("recommendation", question(ASK, *TWO, DEFAULT, "Recommendation:")),
                 ("default", question(ASK, *TWO, REC, "Default: none.")),
                 ("default", question(ASK, *TWO, REC, "Default:")))
        for part, text in cases:
            with self.subTest(text=text):
                self.assertIn(part, self.file(False, text))

    def test_oq_c6_empty_recommendation_before_a_default_line_does_not_count(self) -> None:
        # "Recommendation:" has no value. The default on the next line is not its value.
        self.file(False, question(ASK, *TWO, "Recommendation:", DEFAULT))

    def test_oq_c6_default_until_g2_none_does_not_count(self) -> None:
        self.file(False, question(ASK, *TWO, REC, "Default until G2: none."))

    def test_oq_c6_empty_or_none_table_cell_does_not_count(self) -> None:
        head = "| Question | Options | Recommendation | Default until G2 |\n| --- | --- | --- | --- |\n"
        ask = "What does an expired code do?"
        cases = (("recommendation", f"| {ask} | Refuse it; ignore it | | The plan refuses it |"),
                 ("recommendation", f"| {ask} | Refuse it; ignore it | None | The plan refuses it |"),
                 ("default", f"| {ask} | Refuse it; ignore it | Refuse it | |"),
                 ("default", f"| {ask} | Refuse it; ignore it | Refuse it | None |"))
        for part, row in cases:
            with self.subTest(row=row):
                self.assertIn(part, self.file(False, head + row))

    # Criterion 7: the delta ----------------------------------------------------------------------
    def with_delta(self, text: str, rel: str | None = None) -> dict[str, str]:
        return {**self.plan_file(OQ_LIST), (rel or self.DELTA): text}

    def test_oq_c7_added_requirement_with_the_gap_in_the_title_fails(self) -> None:
        text = requirement("ADDED", "checkout.R1", "Refuse an expired code")
        detail = self.check(False, self.with_delta(text))
        self.assertIn("checkout.R1", detail)
        self.assertIn("delta", detail)

    def test_oq_c7_added_requirement_with_the_gap_in_the_body_fails(self) -> None:
        text = requirement("ADDED", "checkout.R1", "Codes at checkout",
                           "amount_due MUST raise UnknownCode for an expired code.")
        self.assertIn("checkout.R1", self.check(False, self.with_delta(text)))

    def test_oq_c7_modified_requirement_with_the_gap_fails(self) -> None:
        text = requirement("MODIFIED", "cart.R1", "Add an item",
                           "The cart MUST refuse an item after its end date.")
        self.assertIn("cart.R1", self.check(False, self.with_delta(text)))

    def test_oq_c7_one_change_with_the_gap_among_others_fails(self) -> None:
        text = delta(requirement("ADDED", "checkout.R1", "Lower the amount"),
                     requirement("ADDED", "checkout.R2", "Refuse an expired code"))
        detail = self.check(False, self.with_delta(text))
        self.assertIn("checkout.R2", detail)

    def test_oq_c7_removed_change_with_the_gap_does_not_count(self) -> None:
        text = requirement("REMOVED", "cart.R1", "Expired items", "Expired items are gone.")
        self.check(True, self.with_delta(text))

    def test_oq_c7_delta_without_the_gap_passes(self) -> None:
        text = requirement("ADDED", "checkout.R1", "Lower the amount by the percent of the code")
        self.check(True, self.with_delta(text))

    def test_oq_c7_no_delta_file_is_not_a_failure(self) -> None:
        self.check(True, self.plan_file(OQ_LIST))

    def test_oq_c7_delta_pattern_replaces_the_pattern_for_the_delta(self) -> None:
        text = requirement("ADDED", "checkout.R1", "A code that has ended is refused")
        self.check(True, self.with_delta(text))  # the default delta_pattern is `pattern`
        self.check(False, self.with_delta(text), delta_pattern=r"\bend(s|ed)\b")
        other = requirement("ADDED", "checkout.R1", "Refuse an expired code")
        self.check(True, self.with_delta(other), delta_pattern=r"\bend(s|ed)\b")

    def test_oq_c7_only_a_delta_that_matches_the_glob_counts(self) -> None:
        text = requirement("ADDED", "checkout.R1", "Refuse an expired code")
        self.check(True, self.with_delta(text, "docs/notes/SHOP-14.spec.md"))
        self.check(True, self.with_delta(text, "docs/plans/SHOP-15.spec.md"))
        self.check(False, self.with_delta(text, "docs/plans/SHOP-14-codes.spec.md"))

    def test_oq_c7_delta_with_the_gap_fails_a_report_question_too(self) -> None:
        files = {self.DELTA: requirement("ADDED", "checkout.R1", "Refuse an expired code")}
        self.check(False, files, report=f"Open questions:\n{OQ_LIST}\n")

    def test_oq_c7_added_requirement_with_no_scenario_still_writes_the_default(self) -> None:
        # The delta is not valid, but it still writes the default as a requirement.
        text = "## ADDED checkout.R1: Refuse an expired code\n\nThe checkout MUST refuse it.\n"
        self.check(False, self.with_delta(text))

    def test_oq_c7_the_fixture_deltas_do_not_count(self) -> None:
        self.check(True, self.plan_file(OQ_LIST), delta="docs/plans/*.spec.md")


# Criterion 9 of EVAL-4e: a label block goes on at a blank line and a table row -------------------


class LabelTableTest(GraderCase):
    PATH = "docs/plans/SHOP-14*.md"
    FILE = "docs/plans/SHOP-14.md"
    TABLE = "| Question |\n| --- |\n| The end date of a code. |"

    def names_gap(self, expected: bool, text: str) -> None:
        args = {"path": self.PATH, "pattern": GAP}
        with self.subTest(source="plan", text=text):
            self.expect(expected, "names_gap", self.workspace({self.FILE: text}), args)
        with self.subTest(source="report", text=text):
            self.expect(expected, "names_gap", self.workspace(), args, report=text)

    def test_oq_c9_names_gap_label_block_goes_on_at_a_blank_line_and_a_table_row(self) -> None:
        for label in ("Open questions:", "**Open questions**", "__Questions__:"):
            self.names_gap(True, f"Plan.\n\n{label}\n\n{self.TABLE}\n")
            self.names_gap(True, f"Plan.\n\n{label}\n- Codes.\n\n{self.TABLE}\n")

    def test_oq_c9_names_gap_label_block_still_ends_at_a_blank_line_and_a_paragraph(
            self) -> None:
        self.names_gap(False, "Open questions:\n\n| Question |\n| --- |\n| None |\n\n"
                              "The end date of a code is in the plan.\n")

    def test_oq_c9_a_table_row_out_of_a_questions_block_does_not_count(self) -> None:
        self.names_gap(False, f"Approach:\n\n{self.TABLE}\n")


# EVAL-4e round 2: the review fixes of open_question ----------------------------------------------


class OpenQuestionRound2Test(GraderCase):
    """EVAL-4e round 2 (R1 to R6). The helpers are the helpers of OpenQuestionTest."""

    PATH, FILE = OpenQuestionTest.PATH, OpenQuestionTest.FILE
    DELTA, DELTA_GLOB = OpenQuestionTest.DELTA, OpenQuestionTest.DELTA_GLOB
    check = OpenQuestionTest.check
    plan_file = OpenQuestionTest.plan_file
    file = OpenQuestionTest.file
    report = OpenQuestionTest.report
    both = OpenQuestionTest.both
    with_delta = OpenQuestionTest.with_delta
    NO_DEFAULT = OpenQuestionTest.NO_DEFAULT

    # R1: a value that starts with "no" is a value --------------------------------------------------
    def test_oq_r1_default_no_discount_counts(self) -> None:
        self.both(True, question(ASK, *TWO, REC, "Default until G2: no discount, as with no code."))

    def test_oq_r1_recommendation_no_discount_counts(self) -> None:
        self.both(True, question(ASK, *TWO, "Recommendation: no discount.", DEFAULT))

    def test_oq_r1_options_no_discount_or_raise_gives_2_options(self) -> None:
        self.both(True, question(ASK, "Options: no discount, or raise UnknownCode.", REC, DEFAULT))

    def test_oq_r1_no_discount_in_a_table_cell_counts(self) -> None:
        table = ("| Question | Options | Recommendation | Default until G2 |\n"
                 "| --- | --- | --- | --- |\n"
                 "| What does amount_due do with an expired code? | No discount; raise UnknownCode "
                 "| No discount | No discount |")
        self.both(True, table)

    def test_oq_r1_none_na_and_tbd_are_still_an_empty_value(self) -> None:
        for value in ("none", "None.", "N/A", "n/a.", "TBD", "tbd."):
            with self.subTest(value=value):
                self.assertIn("default", self.file(
                    False, question(ASK, *TWO, REC, f"Default until G2: {value}")))
                self.assertIn("recommendation", self.file(
                    False, question(ASK, *TWO, f"Recommendation: {value}", DEFAULT)))
                self.assertIn("options", self.file(
                    False, question(ASK, f"Options: {value}", REC, DEFAULT)))

    def test_oq_r1_only_the_first_word_of_the_value_is_empty(self) -> None:
        # "none" later in the value, or a longer word that starts with "none", is a value.
        self.file(True, question(ASK, *TWO, REC, "Default until G2: UnknownCode, and none else."))
        self.file(True, question(ASK, *TWO, REC, "Default until G2: nonetheless UnknownCode."))

    # R2: a word in a sentence that ends in "?" does not count --------------------------------------
    def test_oq_r2_default_word_in_a_question_is_not_a_default(self) -> None:
        detail = self.file(False, question("What must the default be for an expired code?",
                                           *TWO, REC))
        self.assertIn("default", detail)

    def test_oq_r2_recommend_word_in_a_question_is_not_a_recommendation(self) -> None:
        detail = self.file(False, question(ASK, *TWO, "Which option do you recommend?", DEFAULT))
        self.assertIn("recommendation", detail)

    def test_oq_r2_both_words_in_questions_give_neither_part(self) -> None:
        text = question("What must the default be for an expired code?", *TWO,
                        "Which option do you recommend?")
        for source in ("plan", "report"):
            with self.subTest(source=source):
                if source == "plan":
                    detail = self.file(False, text)
                else:
                    detail = self.report(False, f"Open questions:\n{text}\n")
                self.assertIn("recommendation", detail)
                self.assertIn("default", detail)

    def test_oq_r2_word_in_a_sentence_that_ends_in_a_full_stop_counts(self) -> None:
        self.both(True, question(ASK, *TWO, REC, "Default until G2: UnknownCode. Is that right?"))
        self.both(True, question(ASK, *TWO, "I recommend (a). Do you agree?", DEFAULT))

    def test_oq_r2_question_before_the_word_on_the_same_line_does_not_stop_it(self) -> None:
        self.both(True, question(f"{ASK} Default until G2: UnknownCode.", *TWO, REC))

    def test_oq_r2_default_word_in_a_question_on_a_gap_line_does_not_count(self) -> None:
        approach = "What is the default for an expired code?"
        self.assertIn("default", self.check(False, self.plan_file(self.NO_DEFAULT,
                                                                  approach=approach)))

    # R3: an open note or a question in the delta does not count ------------------------------------
    def test_oq_r3_open_question_note_in_a_requirement_passes(self) -> None:
        text = requirement("ADDED", "checkout.R1", "Lower the amount by the percent",
                           "What an expired code does is an open question (see the plan).")
        self.check(True, self.with_delta(text))

    def test_oq_r3_each_open_note_phrase_in_a_requirement_passes(self) -> None:
        for note in ("not decided", "not yet decided", "not approved", "not yet approved"):
            body = f"The checkout MUST lower the amount. An expired code is {note}."
            for op in ("ADDED", "MODIFIED"):
                with self.subTest(note=note, op=op):
                    text = requirement(op, "checkout.R1", "Lower the amount", body)
                    self.check(True, self.with_delta(text))

    def test_oq_r3_line_that_asks_in_a_requirement_passes(self) -> None:
        text = requirement("MODIFIED", "checkout.R1", "Lower the amount",
                           "The checkout MUST lower the amount.\n\nWhat does an expired code do?")
        self.check(True, self.with_delta(text))

    def test_oq_r3_line_that_writes_the_default_still_fails(self) -> None:
        text = requirement("ADDED", "checkout.R1", "Codes at checkout",
                           "An expired code MUST raise UnknownCode.")
        self.assertIn("checkout.R1", self.check(False, self.with_delta(text)))

    def test_oq_r3_default_line_fails_in_a_section_with_an_open_note(self) -> None:
        body = ("What an expired code does is an open question (see the plan).\n\n"
                "An expired code MUST raise UnknownCode.")
        for op in ("ADDED", "MODIFIED"):
            with self.subTest(op=op):
                text = requirement(op, "checkout.R1", "Codes at checkout", body)
                self.assertIn("checkout.R1", self.check(False, self.with_delta(text)))

    def test_oq_r3_heading_line_always_counts(self) -> None:
        for title in ("Refuse an expired code?", "Expired codes (open question)",
                      "Expired codes, not yet decided"):
            with self.subTest(title=title):
                text = requirement("ADDED", "checkout.R1", title)
                self.assertIn("checkout.R1", self.check(False, self.with_delta(text)))

    # R5: the list items after a line with "option" or "options" that ends in ":" -----------------
    def options_list(self, intro: str, *items: str, gap: str = "\n") -> str:
        """An open question with an intro line and nested items, then REC and DEFAULT."""
        body = gap.join(f"     - {item}" for item in items)
        return f"1. {ASK}\n   - {intro}\n{body}\n   - {REC}\n   - {DEFAULT}"

    def test_oq_r5_text_between_the_word_and_the_colon_counts_the_items(self) -> None:
        for intro in ("The options are:", "Options for an expired code:", "Options (pick one):",
                      "Here is each option:"):
            with self.subTest(intro=intro):
                self.both(True, self.options_list(intro, "Raise UnknownCode.", "Ignore the code."))

    def test_oq_r5_blank_lines_between_the_items_are_skipped(self) -> None:
        text = self.options_list("The options are:", "Raise UnknownCode.", "Ignore the code.",
                                 gap="\n\n")
        self.file(True, text)

    def test_oq_r5_count_stops_at_a_line_that_is_not_a_list_item(self) -> None:
        text = (f"1. {ASK}\n   - The options are:\n     - Raise UnknownCode.\n\n"
                "   The ticket gives no rule for this.\n\n     - Ignore the code.\n"
                f"   - {REC}\n   - {DEFAULT}")
        self.assertIn("options", self.file(False, text))

    # R6: which list items are options ---------------------------------------------------------
    def test_oq_r6_recommendation_and_default_items_are_not_options(self) -> None:
        for item in ("Recommendation: raise UnknownCode.", "I recommend raising UnknownCode.",
                     "Default until G2: the code raises UnknownCode.",
                     "The plan uses UnknownCode until G2."):
            with self.subTest(item=item):
                text = self.options_list("The options are:", "Raise UnknownCode.", item)
                self.assertIn("options", self.file(False, text))

    def test_oq_r6_ticket_example_items_are_not_options(self) -> None:
        # Each item has 1 label only, so 2 options can only come from 2 option items.
        for item in ("Recommendation: (b)", "I recommend (b)", "Default until G2: (a)"):
            with self.subTest(item=item):
                text = self.options_list("Options for an expired code:", "Raise UnknownCode.", item)
                self.assertIn("options", self.file(False, text))

    def test_oq_r6_item_with_the_word_later_is_an_option(self) -> None:
        text = self.options_list("The options are:", "Raise UnknownCode.",
                                 "Raise ExpiredCode (recommended)")
        self.both(True, text)

    def test_oq_r6_wrapped_line_that_joins_an_item_does_not_stop_the_count(self) -> None:
        text = (f"1. {ASK}\n   - The options are:\n     - Raise UnknownCode, so that the shopper\n"
                "       sees one error for each bad code.\n     - Ignore the code.\n"
                f"   - {REC}\n   - {DEFAULT}")
        self.both(True, text)


class OpenQuestionRound2ScenarioTest(GraderCase):
    """EVAL-4e round 2, R4: the P3 delta_pattern and a scenario that names Code.ends."""

    def args(self) -> dict[str, Any]:
        item = next(i for i in grader_checks(SCENARIOS["P3"]) if i["name"] == "open_question")
        return grader_args(item)

    def test_oq_r4_p3_delta_pattern_does_not_match_ends(self) -> None:
        pattern = re.compile(self.args()["delta_pattern"], re.I)
        for text in ("SAVE10 ends 2030-12-31", "Code.ends", "the code ends"):
            with self.subTest(text=text):
                self.assertIsNone(pattern.search(text))
        for text in ("an expired code", "the end date of a code", "a code that has ended"):
            with self.subTest(text=text):
                self.assertIsNotNone(pattern.search(text))

    def test_oq_r4_p3_scenario_that_names_code_ends_passes(self) -> None:
        text = ("## ADDED checkout.R1: Lower the amount by the percent\n\n"
                "amount_due MUST lower the amount by the percent of the code.\n\n"
                "### Scenario: A valid code\n\n- GIVEN SAVE10 ends 2030-12-31\n"
                "- WHEN a shopper uses SAVE10 on 2026-01-01\n- THEN the amount is 10% lower\n")
        files = {"docs/plans/SHOP-14.md": plan("1. shopper.J3.", questions=OQ_LIST),
                 "docs/plans/SHOP-14.spec.md": text}
        self.expect(True, "open_question", self.workspace(files), self.args())

    def test_oq_r4_p3_delta_with_expired_end_date_or_ended_still_fails(self) -> None:
        for title in ("Refuse an expired code", "Refuse a code after its end date",
                      "A code that has ended raises UnknownCode"):
            with self.subTest(title=title):
                files = {"docs/plans/SHOP-14.md": plan("1. shopper.J3.", questions=OQ_LIST),
                         "docs/plans/SHOP-14.spec.md": requirement("ADDED", "checkout.R1", title)}
                self.expect(False, "open_question", self.workspace(files), self.args())


# EVAL-4e round 3: grade each open question of a block by itself ---------------------------------

Q1_NO_REC = ("1. What must amount_due do with an expired code?\n   - (a) Raise UnknownCode.\n"
             "   - (b) Ignore the code.\n   - Default until G2: (a).")
ROUNDING_REC = "- Recommendation: round half up to the cent."


def ex_numbered(nested: str = "   - ") -> str:
    """Q9, pass: 2 numbered questions with bold text, each with its options and parts."""
    return (f"1. **What happens with an expired code?** Each code has an `ends` date, but the\n"
            f"   ticket does not say what `amount_due` does after that date.\n"
            f"{nested}a. Raise `UnknownCode`.\n{nested}b. Raise a new `ExpiredCode` error.\n"
            f"{nested}c. Ignore the code and charge the full amount.\n"
            f"{nested}Recommendation: b.\n{nested}Default until G2: c.\n"
            f"2. **How is a discount rounded?** The ticket gives no rule.\n"
            f"{nested}a. Round half up to the cent.\n{nested}b. Round half to even.\n"
            f"{nested}Recommendation: a.\n{nested}Default until G2: a.")


def ex_bold_q() -> str:
    """Q9, pass: "**Q1. ...**" and "**Q2. ...**", each with "- A:", "- B:" and the parts."""
    return ("**Q1. What happens with a code after its `ends` date?**\n\n"
            "- A: Raise `UnknownCode`, as for a code that is not in the list.\n"
            "- B: Raise a new `ExpiredCode` error.\n- Recommendation: B\n"
            "- Default until G2: **A**\n\n"
            "**Q2. How is the discount rounded?**\n\n- A: Round half up to the cent.\n"
            "- B: Round half to even.\n- Recommendation: A\n- Default until G2: **A**")


def ex_no_rec(q3_part: str) -> str:
    """Q9, fail: Q1 names the gap with options and a default, but only Q3 has `q3_part`."""
    return ("**Q1. What does `amount_due` do with an expired code?**\n\n"
            "- a. Raise `UnknownCode` **(default)**\n- b. Raise a new `ExpiredCode` error.\n\n"
            "**Q2. Is the percent an int or a float?**\n\n- a. An int. b. A float.\n"
            "- Default until G2: an int.\n\n"
            "**Q3. Does a code match in a different case?**\n\n"
            f"- a. Match the case. b. Ignore the case.\n- {q3_part}")


def ex_no_default(q4_part: str) -> str:
    """Q9, fail: Q1 names the gap with options and a recommendation, and Q4 has `q4_part`."""
    return ("**Q1. What does `amount_due` do with a code after its end date?**\n\n"
            "- (a) Raise `UnknownCode`.\n- (b) Raise a new `ExpiredCode` error.\n"
            "- Recommendation: (b)\n\n"
            "**Q2. Is the percent an int or a float?**\n\n- (a) An int. (b) A float.\n"
            "- Recommendation: (a)\n- Default until G2: an int.\n\n"
            "**Q3. Does a code match in a different case?**\n\n"
            "- (a) Match the case. (b) Ignore the case.\n- Recommendation: (b)\n\n"
            "**Q4. What does `amount_due` do with a code that is not in the list?**\n\n"
            f"- {q4_part}")


class OpenQuestionRound3Test(GraderCase):
    """EVAL-4e round 3 (Q1 to Q9). The helpers are the helpers of OpenQuestionTest."""

    PATH, FILE = OpenQuestionTest.PATH, OpenQuestionTest.FILE
    DELTA, DELTA_GLOB = OpenQuestionTest.DELTA, OpenQuestionTest.DELTA_GLOB
    check = OpenQuestionTest.check
    plan_file = OpenQuestionTest.plan_file
    file = OpenQuestionTest.file
    report = OpenQuestionTest.report
    both = OpenQuestionTest.both

    def both_detail(self, questions: str, *missing: str, absent: tuple[str, ...] = ()) -> None:
        """Both sources fail, and the detail names each part of `missing` and no part of `absent`."""
        for source in ("plan", "report"):
            with self.subTest(source=source):
                if source == "plan":
                    detail = self.file(False, questions)
                else:
                    detail = self.report(False, f"Plan written at {self.FILE}.\n\n"
                                                f"Open questions:\n{questions}\n")
                for part in missing:
                    self.assertIn(part, detail)
                for part in absent:
                    self.assertNotIn(part, detail)

    # Q1: each part must be in the question that names the gap ------------------------------------
    def test_oq_q1_recommendation_of_a_different_question_does_not_count(self) -> None:
        text = f"{Q1_NO_REC}\n2. **How is a discount rounded?**\n   {ROUNDING_REC}"
        self.both_detail(text, "recommendation", absent=("default", "options"))

    def test_oq_q1_default_of_a_different_question_does_not_count(self) -> None:
        text = (f"1. {ASK}\n   - (a) Raise UnknownCode.\n   - (b) Ignore the code.\n"
                f"   - {REC}\n2. **How is a discount rounded?**\n"
                "   - Default until G2: round half up.")
        self.both_detail(text, "default", absent=("recommendation",))

    def test_oq_q1_options_of_a_different_question_do_not_count(self) -> None:
        text = (f"1. **{ASK}**\n   - {REC}\n   - {DEFAULT}\n"
                "2. **How is a discount rounded?**\n   - (a) Half up.\n   - (b) Half to even.")
        self.both_detail(text, "options")

    def test_oq_q1_default_on_a_gap_line_of_a_different_question_still_counts(self) -> None:
        # Criterion 4 stays: a line of the same source that names the gap can give the default.
        self.both(True, ex_no_default("The plan treats an expired code as an unknown code."))

    def test_oq_q1_default_on_a_gap_line_out_of_the_block_still_counts(self) -> None:
        text = f"1. {ASK}\n   - (a) Raise UnknownCode.\n   - (b) Ignore the code.\n   - {REC}"
        text += "\n2. **How is a discount rounded?**\n   - Default until G2: round half up."
        approach = "Until G2, the plan raises UnknownCode for an expired code."
        self.check(True, self.plan_file(text, approach=approach))

    # Q2: the lines that start a question ---------------------------------------------------------
    def test_oq_q2_each_start_line_at_the_left_margin_starts_a_question(self) -> None:
        for start in ("Q2. How is a discount rounded?", "Q2: How is a discount rounded?",
                      "q2 How is a discount rounded?", "Question 2: How is a discount rounded?",
                      "**Rounding.** How is a discount rounded?", "__Rounding.__ How is it rounded?",
                      "**How is a discount rounded?**", "2. **Rounding.** How is it rounded?",
                      "- **Q2. Rounding?**", "* **Rounding**", "1) __Rounding__"):
            text = f"{Q1_NO_REC}\n\n{start}\n{ROUNDING_REC}"
            with self.subTest(start=start):
                self.both_detail(text, "recommendation")

    def test_oq_q2_a_heading_starts_a_question(self) -> None:
        for heading in ("### Q2. Rounding", "### Rounding", "#### How is a discount rounded?"):
            text = f"{Q1_NO_REC}\n\n{heading}\n\n{ROUNDING_REC}"
            with self.subTest(heading=heading):
                self.assertIn("recommendation", self.file(False, text))

    def test_oq_q2_heading_questions_in_the_section_each_pass_by_themselves(self) -> None:
        text = (f"### Q1. Expired codes\n\n{question(ASK, *TWO, REC, DEFAULT)}\n\n"
                "### Q2. Rounding\n\n1. How is a discount rounded?\n   - (a) Half up.\n"
                "   - (b) Half to even.\n   - Recommendation: (a).\n   - Default until G2: (a).")
        self.file(True, text)

    def test_oq_q2_an_indented_line_does_not_start_a_question(self) -> None:
        for start in ("   - **Q2. Rounding?**", "   **Rounding.** How is a discount rounded?",
                      "   Q2. How is a discount rounded?", "  Question 2: rounding?",
                      "    2. **Rounding.**"):
            text = f"{Q1_NO_REC}\n\n{start}\n{ROUNDING_REC}"
            with self.subTest(start=start):
                self.both(True, text)

    def test_oq_q2_bold_text_in_a_nested_item_stays_in_the_question(self) -> None:
        text = (f"1. **{ASK}**\n   - **Why:** the ticket gives no rule.\n   - (a) Raise UnknownCode."
                f"\n   - (b) Ignore the code.\n   - **Note:** the shopper sees the error.\n"
                f"   - {REC}\n   - {DEFAULT}")
        self.both(True, text)

    def test_oq_q2_bold_start_right_after_a_list_item_starts_a_question(self) -> None:
        # Q9 form 2 with no blank line between the questions.
        text = ("**Q1. What happens with a code after its `ends` date?**\n"
                "- A: Raise `UnknownCode`.\n- B: Raise a new `ExpiredCode` error.\n"
                "- Default until G2: **A**\n"
                "**Q2. How is the discount rounded?**\n- A: Half up.\n- B: Half to even.\n"
                "- Recommendation: A")
        self.both_detail(text, "recommendation")

    # Q3: a bold option, recommendation, or default line does not start a question --------------
    def test_oq_q3_bold_option_lines_do_not_start_a_question(self) -> None:
        for first, second in (("**Option A:** Raise UnknownCode.", "**Option B:** Ignore it."),
                              ("**A:** Raise UnknownCode.", "**B:** Ignore the code."),
                              ("**(a)** Raise UnknownCode.", "**(b)** Ignore the code."),
                              ("**a)** Raise UnknownCode.", "**b)** Ignore the code."),
                              ("- **Option 1:** Raise UnknownCode.", "- **Option 2:** Ignore it.")):
            text = (f"**Q1. {ASK}**\n\n{first}\n\n{second}\n\n- {REC}\n- {DEFAULT}")
            with self.subTest(options=(first, second)):
                self.both(True, text)

    def test_oq_q3_underscore_bold_option_lines_are_options(self) -> None:
        # Q3 names "__" bold too. The nested form has no question start, so it tests the labels.
        first, second = "__Option A:__ Raise UnknownCode.", "__Option B:__ Ignore it."
        with self.subTest(form="left margin"):
            self.both(True, f"**Q1. {ASK}**\n\n{first}\n\n{second}\n\n- {REC}\n- {DEFAULT}")
        with self.subTest(form="nested"):
            self.both(True, question(ASK, first, second, REC, DEFAULT))

    def test_oq_q3_bold_recommendation_lines_do_not_start_a_question(self) -> None:
        for line in ("**Recommendation:** (a).", "**My recommendation:** (a).",
                     "**Our recommendation:** (a).", "**Recommended:** (a).",
                     "- **Recommendation:** (a)."):
            text = f"**Q1. {ASK}**\n\n- {TWO[0]}\n- {TWO[1]}\n\n{line}\n\n- {DEFAULT}"
            with self.subTest(line=line):
                self.both(True, text)

    def test_oq_q3_bold_default_lines_do_not_start_a_question(self) -> None:
        for line in ("**Default until G2:** (a).", "**Plan default until G2:** (a).",
                     "**The default until G2:** (a).", "**The plan uses** UnknownCode until G2.",
                     "- **Default until G2:** (a)."):
            text = f"**Q1. {ASK}**\n\n- {TWO[0]}\n- {TWO[1]}\n- {REC}\n\n{line}"
            with self.subTest(line=line):
                self.both(True, text)

    def test_oq_q3_all_parts_on_bold_lines_pass(self) -> None:
        text = (f"**Q1. {ASK}**\n\n**Option A:** Raise UnknownCode.\n\n"
                "**Option B:** Raise a new ExpiredCode error.\n\n**Recommendation:** B.\n\n"
                "**Default until G2:** A.\n\n**Q2. How is a discount rounded?**\n\n"
                "**Option A:** Half up.\n\n**Option B:** Half to even.\n\n"
                "**Recommendation:** A.\n\n**Default until G2:** A.")
        self.both(True, text)

    # Q4: the lines before the first start, and a block with no start -----------------------------
    def test_oq_q4_lines_before_the_first_start_are_a_question(self) -> None:
        text = ("The ticket does not say what amount_due does with an expired code.\n"
                "- (a) Raise UnknownCode.\n- (b) Ignore the code.\n- Default until G2: (a).\n\n"
                f"**Rounding.** How is a discount rounded?\n{ROUNDING_REC}")
        self.both_detail(text, "recommendation")

    def test_oq_q4_a_block_with_no_start_is_one_question(self) -> None:
        text = ("The ticket does not say what amount_due does with an expired code.\n"
                "- (a) Raise UnknownCode.\n- (b) Ignore the code.\n- Default until G2: (a).\n\n"
                f"How is a discount rounded?\n{ROUNDING_REC}")
        self.file(True, text)

    def test_oq_q4_one_question_that_starts_with_a_start_line_passes(self) -> None:
        for start in (f"**Expired codes.** {ASK}", f"Q1. {ASK}", f"1. **{ASK}**",
                      f"- **Q1. {ASK}**"):
            text = f"{start}\n   - {TWO[0]}\n   - {TWO[1]}\n   - {REC}\n   - {DEFAULT}"
            with self.subTest(start=start):
                self.both(True, text)

    def test_oq_q4_round_1_and_2_forms_still_pass(self) -> None:
        for name, text in (("list", OQ_LIST), ("inline", OQ_INLINE), ("table", OQ_TABLE),
                           ("one line", OQ_INLINE.replace("\n", " "))):
            with self.subTest(form=name):
                self.both(True, text)

    # Q5: each table row is a question ------------------------------------------------------------
    HEAD = "| Question | Options | Recommendation | Default until G2 |\n| --- | --- | --- | --- |\n"
    ROW_GAP = "| What does amount_due do with an expired code? | Raise UnknownCode; ignore it "
    ROW_ROUND = "| How is a discount rounded? | Half up; half to even "

    def test_oq_q5_default_in_a_different_row_does_not_count(self) -> None:
        table = self.HEAD + self.ROW_GAP + "| Raise UnknownCode | |\n" + self.ROW_ROUND + \
            "| Half up | The plan rounds half up |"
        self.both_detail(table, "default", absent=("recommendation",))

    def test_oq_q5_recommendation_in_a_different_row_does_not_count(self) -> None:
        table = self.HEAD + self.ROW_ROUND + "| Half up | Half up |\n" + self.ROW_GAP + \
            "| | The plan raises UnknownCode |"
        self.both_detail(table, "recommendation")

    def test_oq_q5_options_in_a_different_row_do_not_count(self) -> None:
        table = self.HEAD + ("| What does amount_due do with an expired code? | "
                             "| Raise UnknownCode | The plan raises UnknownCode |\n") + \
            self.ROW_ROUND + "| Half up | Half up |"
        self.both_detail(table, "options")

    def test_oq_q5_a_full_row_after_other_rows_passes(self) -> None:
        table = self.HEAD + self.ROW_ROUND + "| Half up | Half up |\n" + self.ROW_GAP + \
            "| Raise UnknownCode | The plan raises UnknownCode |"
        self.both(True, table)

    # Q6: the whole report is split in the same way -----------------------------------------------
    WHOLE = ("I wrote the plan at docs/plans/SHOP-14.md.\n\n"
             "What must amount_due do with an expired code? Options: raise UnknownCode, or ignore "
             "the code. The default until G2 is UnknownCode.\n\n")

    def test_oq_q6_whole_report_part_in_a_different_question_does_not_count(self) -> None:
        for start in ("**Rounding.** How is a discount rounded?", "## Rounding",
                      "Q2. How is a discount rounded?"):
            with self.subTest(start=start):
                detail = self.report(False, f"{self.WHOLE}{start}\n\nI recommend half up.\n")
                self.assertIn("recommendation", detail)

    def test_oq_q6_whole_report_with_no_start_is_one_question(self) -> None:
        self.report(True, f"{self.WHOLE}How is a discount rounded? I recommend half up.\n")

    def test_oq_q6_whole_report_with_all_parts_in_the_gap_question_passes(self) -> None:
        self.report(True, f"{self.WHOLE.rstrip()} I recommend UnknownCode.\n\n"
                          "**Rounding.** How is a discount rounded? Half up.\n")

    # Q7: the words that give a recommendation ----------------------------------------------------
    def test_oq_q7_each_recommendation_word_counts(self) -> None:
        for line in ("I recommend (a).", "Recommended: (a).", "Recommendation: (a).",
                     "My suggestion: (a).", "Suggested: (a).", "Suggestion: (a).",
                     "Preferred: (a).", "I prefer (a).", "(a) is my preferred option."):
            with self.subTest(line=line):
                self.both(True, question(ASK, *TWO, line, DEFAULT))

    def test_oq_q7_suggest_and_may_prefer_do_not_give_a_recommendation(self) -> None:
        for line in ("I suggest an optional argument for the date.",
                     "The author may prefer to strip spaces.",
                     "The author may prefer (a)."):
            with self.subTest(line=line):
                self.both_detail(question(ASK, *TWO, line, DEFAULT), "recommendation")

    # Q8: a parameter default in code is not a default of the plan --------------------------------
    def test_oq_q8_parameter_default_in_code_does_not_count(self) -> None:
        for line in ("Add a `today` argument (default `date.today()`).",
                     "Add `today: date` (default `date.today()`) to amount_due."):
            with self.subTest(line=line):
                self.both_detail(question(ASK, *TWO, REC, line), "default")

    def test_oq_q8_parameter_default_on_a_gap_line_does_not_count(self) -> None:
        approach = "Compare `today` (default `date.today()`) with the end date of the code."
        self.assertIn("default", self.check(False, self.plan_file(OpenQuestionTest.NO_DEFAULT,
                                                                  approach=approach)))

    def test_oq_q8_default_marks_and_a_code_value_still_count(self) -> None:
        for items in (("(a) Raise UnknownCode (default).", TWO[1], REC),
                      ("(a) Raise UnknownCode **(default)**", TWO[1], REC),
                      (*TWO, REC, "Default until G2: `UnknownCode`"),
                      (*TWO, REC, "Default until G2: raise `UnknownCode`.")):
            with self.subTest(items=items):
                self.both(True, question(ASK, *items))

    # Q9: realistic multi-question examples -------------------------------------------------------
    def test_oq_q9_numbered_bold_questions_with_nested_options_pass(self) -> None:
        for nested in ("   - ", "   "):
            with self.subTest(nested=repr(nested)):
                self.both(True, ex_numbered(nested))

    def test_oq_q9_bold_q_questions_with_a_and_b_items_pass(self) -> None:
        self.both(True, ex_bold_q())

    def test_oq_q9_recommendation_only_in_q3_fails(self) -> None:
        for part in ("The author may prefer to strip spaces too.",
                     "Recommendation: (b), ignore the case."):
            with self.subTest(part=part):
                self.both_detail(ex_no_rec(part), "recommendation", absent=("default",))

    def test_oq_q9_default_only_in_q4_that_does_not_name_the_gap_fails(self) -> None:
        self.both_detail(ex_no_default("The plan treats it as an unknown code."), "default",
                         absent=("recommendation",))


# EVAL-4e round 4: split open questions by the style of the gap question --------------------------

Q2_FULL = ("**Q2. How is a discount rounded?**\n\n- (a) Half up.\n- (b) Half to even.\n"
           "- Recommendation: (a).\n- Default until G2: (a).")


def ex_s11_bold(blank: bool = True) -> str:
    """S11, pass: "**Q1. ...**", "**Options:**", 2 option items, and the bold parts."""
    sep = "\n\n" if blank else "\n"
    return sep.join(("**Q1. What happens with an expired code?**", "**Options:**",
                     "- (a) Reject it\n- (b) Ignore the end date", "**Recommendation:** (a)",
                     "**Default until G2:** (b)"))


def ex_s11_headings(q1_rec: str = "#### Recommendation\n\n(a) Reject it.\n\n") -> str:
    """S11, pass: "### Q1" with "####" sub-headings for the parts, and then "### Q2"."""
    return ("### Q1. Expired codes\n\nWhat happens with an expired code?\n\n"
            "#### Options\n\n- (a) Reject it.\n- (b) Ignore the end date.\n\n"
            f"{q1_rec}#### Default until G2\n\n(b) Ignore the end date.\n\n"
            "### Q2. Rounding\n\nHow is a discount rounded?\n\n#### Options\n\n- (a) Half up.\n"
            "- (b) Half to even.\n\n#### Recommendation\n\n(a)\n\n#### Default until G2\n\n(a)")


class OpenQuestionRound4Test(GraderCase):
    """EVAL-4e round 4 (S1 to S13). The helpers are the helpers of OpenQuestionTest."""

    PATH, FILE = OpenQuestionTest.PATH, OpenQuestionTest.FILE
    DELTA, DELTA_GLOB = OpenQuestionTest.DELTA, OpenQuestionTest.DELTA_GLOB
    check = OpenQuestionTest.check
    plan_file = OpenQuestionTest.plan_file
    file = OpenQuestionTest.file
    report = OpenQuestionTest.report
    both = OpenQuestionTest.both
    both_detail = OpenQuestionRound3Test.both_detail

    # S1: the gap line sets the style of a question start ---------------------------------------
    def test_oq_s1_numbered_gap_question_splits_at_each_numbered_item(self) -> None:
        text = (f"1. {ASK}\n   - {TWO[0]}\n   - {TWO[1]}\n   - {DEFAULT}\n"
                "2. How is a discount rounded?\n   - Recommendation: half up.")
        self.both_detail(text, "recommendation", absent=("default", "options"))

    def test_oq_s1_bullet_gap_question_splits_at_each_bullet_item(self) -> None:
        text = (f"- {ASK}\n  - {TWO[0]}\n  - {TWO[1]}\n  - {DEFAULT}\n"
                "- How is a discount rounded?\n  - Recommendation: half up.")
        self.both_detail(text, "recommendation", absent=("default", "options"))

    def test_oq_s1_bold_gap_question_splits_at_each_bold_line(self) -> None:
        text = (f"**Expired codes.** {ASK}\n\n- {TWO[0]}\n- {TWO[1]}\n- {DEFAULT}\n\n"
                "**Rounding.** How is a discount rounded?\n\n- Recommendation: half up.")
        self.both_detail(text, "recommendation", absent=("default", "options"))

    def test_oq_s1_strongest_style_up_to_the_gap_line_is_used(self) -> None:
        # "**Q1 ...**" is stronger than the numbered gap item, so "2." stays in Q1.
        text = (f"**Q1. Expired codes**\n\n1. {ASK}\n   - {TWO[0]}\n   - {TWO[1]}\n\n"
                f"2. Which error does the shopper see?\n   - {REC}\n   - {DEFAULT}")
        self.both(True, text)

    def test_oq_s1_lower_heading_does_not_start_a_heading_question(self) -> None:
        self.file(True, ex_s11_headings())

    def test_oq_s1_same_or_higher_heading_starts_a_heading_question(self) -> None:
        q2 = "How is a discount rounded?\n\n#### Recommendation\n\n(a) Half up."
        for heading in ("### Q2. Rounding", "### Rounding", "## Rounding"):
            text = (f"### Q1. Expired codes\n\n{ASK}\n\n- {TWO[0]}\n- {TWO[1]}\n\n- {DEFAULT}\n\n"
                    f"{heading}\n\n{q2}")
            with self.subTest(heading=heading):
                self.assertIn("recommendation", self.file(False, text))

    def test_oq_s1_heading_always_starts_a_question_in_a_numbered_block(self) -> None:
        for heading in ("### Rounding", "#### Rounding", "##### Rounding"):
            text = f"{Q1_NO_REC}\n\n{heading}\n\n{ROUNDING_REC}"
            with self.subTest(heading=heading):
                self.assertIn("recommendation", self.file(False, text))

    # S2: the Q<n> line, the bold line after a blank line, and the plain bullet item --------------
    def test_oq_s2_q_line_starts_a_question_in_each_style(self) -> None:
        for gap in (f"1. {ASK}", f"- {ASK}", f"**Expired codes.** {ASK}"):
            for start in ("Q2. How is a discount rounded?", "- Q2: How is it rounded?",
                          "**Question 2.** How is it rounded?"):
                text = (f"{gap}\n   - {TWO[0]}\n   - {TWO[1]}\n   - {DEFAULT}\n\n"
                        f"{start}\n{ROUNDING_REC}")
                with self.subTest(gap=gap, start=start):
                    self.both_detail(text, "recommendation")

    def test_oq_s2_bold_line_after_a_blank_line_starts_a_list_question(self) -> None:
        for gap in (f"1. {ASK}", f"- {ASK}"):
            for start in ("**Rounding.** How is it rounded?", "* **Rounding**",
                          "- **How is a discount rounded?**"):
                text = (f"{gap}\n   - {TWO[0]}\n   - {TWO[1]}\n   - {DEFAULT}\n\n"
                        f"{start}\n{ROUNDING_REC}")
                with self.subTest(gap=gap, start=start):
                    self.both_detail(text, "recommendation")

    def test_oq_s2_plain_bullet_does_not_start_a_question_of_other_styles(self) -> None:
        for gap in (f"1. {ASK}", f"**Q1. {ASK}**", f"**Expired codes.** {ASK}"):
            text = f"{gap}\n\nOptions:\n\n- Reject it\n- Ignore it\n\n- {REC}\n- {DEFAULT}"
            with self.subTest(gap=gap):
                self.both(True, text)

    # S3: a question in a paragraph -----------------------------------------------------------------
    PARAGRAPH = "The ticket does not say what amount_due does with an expired code. Options:"

    def test_oq_s3_paragraph_with_option_bullets_and_recommendation_passes(self) -> None:
        text = (f"{self.PARAGRAPH}\n\n- Raise UnknownCode.\n- Ignore the code.\n\n"
                f"{REC}\n\n{DEFAULT}")
        self.both(True, text)

    def test_oq_s3_paragraph_with_an_options_table_and_recommendation_passes(self) -> None:
        text = (f"{self.PARAGRAPH}\n\n| Option | Effect |\n| --- | --- |\n"
                "| (a) Raise UnknownCode | The shopper sees an error |\n"
                "| (b) Ignore the code | The shopper pays the full amount |\n\n"
                f"{REC}\n\n{DEFAULT}")
        self.both(True, text)

    def test_oq_s3_later_plain_bullets_do_not_set_the_style(self) -> None:
        text = (f"{self.PARAGRAPH}\n\n- (a) Raise UnknownCode.\n- (b) Ignore the code.\n\n"
                f"- {REC}\n\n- {DEFAULT}")
        self.both(True, text)

    def test_oq_s3_later_numbered_item_after_a_blank_line_does_not_set_the_style(self) -> None:
        # Round 5 (T3) changed this: a later numbered item stays in the paragraph question.
        text = ("The ticket does not say what amount_due does with an expired code. (a) Raise "
                "UnknownCode. (b) Ignore the code. Default until G2: (a).\n\n"
                "1. How is a discount rounded? Recommendation: half up.\n"
                "2. Which currency? Recommendation: EUR.")
        self.both(True, text)

    def test_oq_s3_later_start_with_no_blank_line_does_not_set_the_style(self) -> None:
        text = ("The ticket does not say what amount_due does with an expired code. (a) Raise "
                "UnknownCode. (b) Ignore the code. Default until G2: (a).\n"
                "**Recommendation.** (a), so that the shopper sees an error.")
        self.both(True, text)

    # S4: a line that gives a part never starts a question ------------------------------------------
    def test_oq_s4_part_lines_do_not_start_a_bold_question(self) -> None:
        for line in ("**Options:**", "**Option A:** Raise UnknownCode.", "(a) Raise UnknownCode.",
                     "A: Raise UnknownCode.", "**Suggested answer:** (a).",
                     "**Interim default:** (a).", "**I recommend (a).**",
                     "**The plan uses** UnknownCode for now.", "**Until G2** the build waits."):
            text = (f"**Expired codes.** {ASK}\n\n{line}\n\n- {TWO[0]}\n- {TWO[1]}\n"
                    f"- {REC}\n- {DEFAULT}")
            with self.subTest(line=line):
                self.both(True, text)

    def test_oq_s4_numbered_part_lines_do_not_start_a_numbered_question(self) -> None:
        text = (f"1. {ASK}\n2. (a) Raise UnknownCode.\n3. (b) Ignore the code.\n"
                f"4. {REC}\n5. {DEFAULT}")
        self.both(True, text)

    def test_oq_s4_bold_label_with_a_colon_does_not_start_a_question(self) -> None:
        for label in ("**Context:** the ticket gives no rule.",
                      "**Why it matters**: the shopper pays.", "- **Context:** no rule.",
                      "__Context:__ no rule."):
            text = (f"**Expired codes.** {ASK}\n\n{label}\n\n- {TWO[0]}\n- {TWO[1]}\n"
                    f"- {REC}\n- {DEFAULT}")
            with self.subTest(label=label):
                self.both(True, text)

    # S5: table rows --------------------------------------------------------------------------------
    HEAD = OpenQuestionRound3Test.HEAD

    def test_oq_s5_lines_after_the_table_do_not_count_for_the_last_row(self) -> None:
        table = (self.HEAD + "| How is a discount rounded? | Half up; half to even | Half up "
                 "| Half up |\n| What does amount_due do with an expired code? "
                 "| Raise UnknownCode; ignore it | | The plan raises UnknownCode |")
        self.both_detail(f"{table}\n\nRecommendation: raise UnknownCode.", "recommendation")

    def test_oq_s5_full_last_row_with_text_after_the_table_passes(self) -> None:
        self.both(True, f"{OQ_TABLE}\n\nThe table gives each option.")

    # S6: a heading or a bold-only line is a label for the next line -----------------------------
    def test_oq_s6_bold_only_and_heading_labels_give_the_next_line(self) -> None:
        for rec in ("**Recommendation**\n\n(a)", "- **Recommendation**\n  (a)",
                    "**Recommendation**\nRaise UnknownCode."):
            text = f"**Q1. {ASK}**\n\n- {TWO[0]}\n- {TWO[1]}\n\n{rec}\n\n{DEFAULT}"
            with self.subTest(rec=rec):
                self.both(True, text)
        self.file(True, f"### Q1. Expired codes\n\n{ASK}\n\n- {TWO[0]}\n- {TWO[1]}\n\n"
                        f"#### Recommendation\n\n(a)\n\n{DEFAULT}")

    def test_oq_s6_bold_only_options_label_counts_the_items(self) -> None:
        text = (f"**Q1. {ASK}**\n\n- **Options**\n  - Raise UnknownCode.\n  - Ignore the code.\n\n"
                f"{REC}\n\n{DEFAULT}")
        self.both(True, text)

    def test_oq_s6_label_with_a_different_part_on_the_next_line_does_not_count(self) -> None:
        text = f"**Q1. {ASK}**\n\n- {TWO[0]}\n- {TWO[1]}\n\n**Recommendation**\n\n{DEFAULT}"
        self.both_detail(text, "recommendation", absent=("default", "options"))
        self.assertIn("recommendation", self.file(False, ex_s11_headings(
            "#### Recommendation\n\n")))

    # S7: a bold list item counts as an option ------------------------------------------------------
    def test_oq_s7_bold_list_items_count_as_options(self) -> None:
        text = (f"**Q1. {ASK}**\n\n- **Reject it** with an error\n- **Ignore it**\n\n"
                f"**Recommendation:** reject it.\n\n**Default until G2:** ignore it.")
        self.both(True, text)

    def test_oq_s7_bold_label_and_part_items_do_not_count_as_options(self) -> None:
        text = (f"**Q1. {ASK}**\n\n- **Context:** the ticket gives no rule.\n"
                "- **Reject it** with an error\n- **Recommendation:** reject it.\n"
                "- **Default until G2:** reject it.")
        self.both_detail(text, "options", absent=("recommendation", "default"))

    # S8: a bold line or a Q<n> line is not joined to the line before it -------------------------
    def test_oq_s8_start_line_right_after_a_list_item_is_not_joined(self) -> None:
        for start in ("Q2. How is a discount rounded? I recommend (a).",
                      "Question 2: rounding? I recommend (a).",
                      "**Q2. Rounding?** I recommend (a)."):
            text = f"**Q1. {ASK}**\n- {TWO[0]}\n- {TWO[1]}\n- {DEFAULT}\n{start}"
            with self.subTest(start=start):
                self.both_detail(text, "recommendation")

    def test_oq_s8_bold_line_right_after_a_bold_question_list_item_is_not_joined(self) -> None:
        text = (f"**Expired codes.** {ASK}\n- {TWO[0]}\n- {TWO[1]}\n- {DEFAULT}\n"
                "**Rounding.** I recommend (a), half up.")
        self.both_detail(text, "recommendation")

    def test_oq_s8_bold_line_after_a_paragraph_line_keeps_its_parts(self) -> None:
        # Not joined: "**Recommendation:**" still gives its value as its own line.
        text = (f"{ASK} (a) Raise UnknownCode. (b) Ignore the code.\n"
                "**Recommendation:** (a).\n**Default until G2:** (a).")
        self.both(True, text)

    # S9: underscore bold option labels ---------------------------------------------------------------
    def test_oq_s9_underscore_bold_option_labels_count(self) -> None:
        for first, second in (("__Option A:__ Raise UnknownCode.", "__Option B:__ Ignore it."),
                              ("__A:__ Raise UnknownCode.", "__B:__ Ignore the code.")):
            with self.subTest(options=(first, second), form="left margin"):
                self.both(True, f"**Q1. {ASK}**\n\n{first}\n\n{second}\n\n- {REC}\n- {DEFAULT}")
            with self.subTest(options=(first, second), form="nested"):
                self.both(True, question(ASK, first, second, REC, DEFAULT))

    def test_oq_s9_one_underscore_label_is_not_2_options(self) -> None:
        self.both_detail(question(ASK, "__A:__ Raise UnknownCode.", REC, DEFAULT), "options")

    # S10: suggest and prefer -----------------------------------------------------------------------
    def test_oq_s10_suggest_and_prefer_before_an_option_recommend(self) -> None:
        for line in ("I suggest (a).", "I'd prefer option B.", "We suggest (b).",
                     "I would suggest option (a).", "We prefer answer (a).", "I prefer (a).",
                     "Suggested: (a).", "Suggested answer: (a).", "Suggested option: (b).",
                     "Preferred: (a).", "Preferred answer: (a).", "(a) Raise it (preferred).",
                     "I prefer to strip spaces."):  # round 5 (T6) moved this line here
            with self.subTest(line=line):
                self.both(True, question(ASK, *TWO, line, DEFAULT))

    def test_oq_s10_suggest_and_prefer_before_other_words_do_not_recommend(self) -> None:
        for line in ("I suggest an optional argument.", "We suggest raising ExpiredCode.",
                     "The ticket suggested nothing.",
                     "We suggest optional rounding.", "The preferred way is not clear.",
                     "We suggest a new ExpiredCode error."):
            with self.subTest(line=line):
                self.both_detail(question(ASK, *TWO, line, DEFAULT), "recommendation")

    # S11: realistic outputs that pass --------------------------------------------------------------
    def test_oq_s11_bold_q_with_bold_options_label_passes(self) -> None:
        for blank in (True, False):
            with self.subTest(blank=blank):
                self.both(True, ex_s11_bold(blank))
                self.both(True, f"{ex_s11_bold(blank)}\n\n{Q2_FULL}")

    def test_oq_s11_bold_option_names_pass(self) -> None:
        text = ex_s11_bold().replace("- (a) Reject it\n- (b) Ignore the end date",
                                     "- **Reject it** with an error\n- **Ignore it**")
        text = text.replace("(a)", "reject it").replace("(b)", "ignore it")
        self.both(True, text)
        self.both(True, f"{text}\n\n{Q2_FULL}")

    def test_oq_s11_heading_questions_with_sub_headings_pass(self) -> None:
        self.file(True, ex_s11_headings())

    # S12: realistic outputs that fail --------------------------------------------------------------
    def test_oq_s12_plain_numbered_list_does_not_leak_parts(self) -> None:
        text = ("1. What happens with an expired code? Options: (a) reject, (b) ignore.\n"
                "2. Which currency? Recommendation: EUR. Default until G2: EUR.")
        self.both_detail(text, "recommendation", "default", absent=("options",))

    def test_oq_s12_text_after_a_question_table_does_not_leak_parts(self) -> None:
        table = ("| Question | Options |\n| --- | --- |\n"
                 "| What does amount_due do with an expired code? | Raise UnknownCode; ignore it |")
        text = f"{table}\n\nRounding: Recommendation: down. Default until G2: down."
        self.both_detail(text, "recommendation", "default", absent=("options",))

    # S13: the round 1 to 3 forms still pass --------------------------------------------------------
    def test_oq_s13_earlier_forms_still_pass(self) -> None:
        for name, text in (("list", OQ_LIST), ("inline", OQ_INLINE), ("table", OQ_TABLE),
                           ("numbered bold", ex_numbered()), ("bold q", ex_bold_q())):
            with self.subTest(form=name):
                self.both(True, text)


# EVAL-4e round 5: the option count, bold bullets, labels, prefer, and suggest -------------------

BOLD_ASK = "**What happens to an expired code?**"


class OpenQuestionRound5Test(GraderCase):
    """EVAL-4e round 5 (T1 to T8). The helpers are the helpers of OpenQuestionTest."""

    PATH, FILE = OpenQuestionTest.PATH, OpenQuestionTest.FILE
    DELTA, DELTA_GLOB = OpenQuestionTest.DELTA, OpenQuestionTest.DELTA_GLOB
    check = OpenQuestionTest.check
    plan_file = OpenQuestionTest.plan_file
    file = OpenQuestionTest.file
    report = OpenQuestionTest.report
    both = OpenQuestionTest.both
    both_detail = OpenQuestionRound3Test.both_detail

    # T1: a question with only 1 option fails ---------------------------------------------------
    def test_oq_t1_ticket_example_bold_question_with_1_option_fails(self) -> None:
        text = ("1. **What happens with an expired code?** The ticket does not say.\n"
                "   - **Reject it with an error.**\n   Recommendation: reject it.\n"
                "   Default until G2: reject it.")
        self.both_detail(text, "options", absent=("recommendation", "default"))

    def test_oq_t1_bold_item_alone_is_not_a_second_option(self) -> None:
        for first in ("1. **What happens with an expired code?**",
                      f"1. **Expired codes.** {ASK}", f"**Q1. {ASK}**"):
            text = (f"{first}\n   - **Reject it with an error.**\n   - {REC}\n   - {DEFAULT}")
            with self.subTest(first=first):
                self.both_detail(text, "options", absent=("recommendation", "default"))

    def test_oq_t1_plain_question_with_1_option_fails(self) -> None:
        self.both_detail(question(ASK, "Reject it with an error.", REC, DEFAULT), "options",
                         absent=("recommendation", "default"))

    # T2: the list items after a first line that ends in "?" ------------------------------------
    def test_oq_t2_items_after_a_question_line_count_as_options(self) -> None:
        for first in (ASK, "**What happens with an expired code?**"):
            with self.subTest(first=first, form="numbered"):
                self.both(True, question(first, "Reject it.", "Ignore it.", REC, DEFAULT))
            with self.subTest(first=first, form="bold paragraph"):
                text = f"**Q1. {ASK}**" if first == ASK else first
                self.both(True, f"{text}\n\n- Reject it.\n- Ignore it.\n- {REC}\n- {DEFAULT}")

    def test_oq_t2_count_stops_at_a_line_that_is_not_a_list_item(self) -> None:
        tail = f"\n\n{REC}\n\n{DEFAULT}"
        self.file(True, f"{BOLD_ASK}\n\n- Reject it.\n- Ignore it.{tail}")
        detail = self.file(False, f"{BOLD_ASK}\n\n- Reject it.\n\nThe shop owner must decide."
                                  f"\n\n- Ignore it.{tail}")
        self.assertIn("options", detail)

    def test_oq_t2_label_part_and_option_word_items_do_not_count(self) -> None:
        for item in ("- Options:", "- **Context:** the ticket gives no rule.",
                     "- The ticket gives no option for this.", "- Both options cost the shop money.",
                     "- I recommend that it rejects the code.", "- Default: reject it."):
            text = f"{BOLD_ASK}\n\n{item}\n- Reject it.\n- {REC}\n- {DEFAULT}"
            with self.subTest(item=item):
                self.both_detail(text, "options", absent=("recommendation", "default"))

    def test_oq_t2_bold_only_items_count(self) -> None:
        for items in ("- **Reject it**\n- **Ignore it**", "- **Ignore it**\n- Reject it."):
            with self.subTest(items=items):
                self.both(True, f"{BOLD_ASK}\n\n{items}\n- {REC}\n- {DEFAULT}")

    def test_oq_t2_items_with_the_same_option_label_count_as_1(self) -> None:
        for second in ("(a) Ignore the code.", "A. Ignore the code.", "a) Ignore the code.",
                       "**A.** Ignore the code."):
            text = question(ASK, "(a) Raise UnknownCode.", second, REC, DEFAULT)
            with self.subTest(second=second):
                self.both_detail(text, "options", absent=("recommendation", "default"))

    def test_oq_t2_items_with_different_option_labels_count_as_2(self) -> None:
        for second in ("(b) Ignore the code.", "B. Ignore the code."):
            with self.subTest(second=second):
                self.both(True, question(ASK, "(a) Raise UnknownCode.", second, REC, DEFAULT))

    # T3: a question in a paragraph ---------------------------------------------------------------
    PARAGRAPH = ("The ticket does not say what happens to a code after its end date. Options:")

    def test_oq_t3_ticket_example_paragraph_with_numbered_options_passes(self) -> None:
        text = (f"{self.PARAGRAPH}\n\n1. Reject it with an error.\n2. Accept it at full price.\n\n"
                "Recommendation: 1. Default until G2: 1.")
        self.both(True, text)

    def test_oq_t3_later_bullet_item_does_not_set_the_style(self) -> None:
        text = (f"{self.PARAGRAPH} (a) Reject it. (b) Ignore it. Default until G2: (a).\n\n"
                "- How is a discount rounded? Recommendation: (a), half up.")
        self.both(True, text)

    def test_oq_t3_later_q_line_or_bold_paragraph_after_a_blank_line_sets_the_style(
            self) -> None:
        for start in ("Q2. How is a discount rounded?", "**Rounding.** How is it rounded?",
                      "**How is a discount rounded?**"):
            text = (f"{self.PARAGRAPH} (a) Reject it. (b) Ignore it. Default until G2: (a).\n\n"
                    f"{start}\n\nRecommendation: half up.")
            with self.subTest(start=start):
                self.both_detail(text, "recommendation", absent=("options", "default"))

    def test_oq_t3_later_heading_sets_the_style(self) -> None:
        text = (f"{self.PARAGRAPH} (a) Reject it. (b) Ignore it. Default until G2: (a).\n\n"
                "### Rounding\n\nRecommendation: half up.")
        detail = self.file(False, text)
        self.assertIn("recommendation", detail)
        self.assertNotIn("default", detail)

    # T4: a bold bullet item has the bullet style -----------------------------------------------
    def test_oq_t4_bold_bullets_do_not_split_a_bold_paragraph_question(self) -> None:
        text = (f"{BOLD_ASK}\n\n- **Reject** with an error (recommended)\n"
                "- **Ignore** the end date\n\nDefault until G2: ignore it.")
        self.both(True, text)

    def test_oq_t4_bold_label_bullets_are_option_lines(self) -> None:
        for items in ("- **(a)** Accept it\n- **(b)** Ignore it",
                      "- **A.** Accept it\n- **B.** Ignore it"):
            with self.subTest(items=items):
                self.both(True, f"{BOLD_ASK}\n\n{items}\n\n{REC}\n\n{DEFAULT}")

    def test_oq_t4_ticket_bold_label_bullets_stay_in_the_question(self) -> None:
        # "(a)" and "A." are the same label: 1 option. The parts after them stay in the question.
        text = f"{BOLD_ASK}\n\n- **(a)** Accept it\n- **A.** Ignore it\n- {REC}\n- {DEFAULT}"
        self.both_detail(text, "options", absent=("recommendation", "default"))

    def test_oq_t4_bold_bullet_after_a_blank_line_starts_a_numbered_block_question(self) -> None:
        for start in ("* **Rounding**", "- **Rounding** How is a discount rounded?"):
            text = f"{Q1_NO_REC}\n\n{start}\n  {ROUNDING_REC}"
            with self.subTest(start=start):
                self.both_detail(text, "recommendation", absent=("options", "default"))

    # T5: a bold-only line that does not end in "?" is a label ----------------------------------
    def test_oq_t5_bold_only_labels_do_not_start_a_bold_question(self) -> None:
        text = (f"{BOLD_ASK}\n\n**Why it matters**\n\nThe shopper pays the full price.\n\n"
                "**Options**\n\n- Reject it.\n- Ignore it.\n\n**Recommendation**\n\nReject it.\n\n"
                f"{DEFAULT}")
        self.both(True, text)

    def test_oq_t5_bold_only_label_does_not_start_a_numbered_question(self) -> None:
        for label in ("**Why it matters**", "**Options**", "**Context**"):
            text = (f"1. {ASK}\n   - {TWO[0]}\n   - {TWO[1]}\n\n{label}\n\n"
                    f"- {REC}\n- {DEFAULT}")
            with self.subTest(label=label):
                self.both(True, text)

    def test_oq_t5_bold_only_question_still_starts_a_question(self) -> None:
        for gap in (f"{BOLD_ASK}\n\n- {TWO[0]}\n- {TWO[1]}\n- {DEFAULT}", Q1_NO_REC):
            text = f"{gap}\n\n**How is a discount rounded?**\n\n{ROUNDING_REC}"
            with self.subTest(gap=gap.splitlines()[0]):
                self.both_detail(text, "recommendation", absent=("options", "default"))

    # T6: prefer and preferred ------------------------------------------------------------------
    def test_oq_t6_prefer_forms_always_recommend(self) -> None:
        for line in ("I prefer to reject expired codes.", "I prefer to strip spaces.",
                     "I'd prefer to reject the code.", "I would prefer to raise UnknownCode.",
                     "We prefer to ignore the code."):
            with self.subTest(line=line):
                self.both(True, question(ASK, *TWO, line, DEFAULT))

    def test_oq_t6_may_prefer_does_not_recommend(self) -> None:
        for line in ("The author may prefer to reject the code.", "Shoppers prefer a low price."):
            with self.subTest(line=line):
                self.both_detail(question(ASK, *TWO, line, DEFAULT), "recommendation",
                                 absent=("options", "default"))

    def test_oq_t6_preferred_before_each_mark_or_word_recommends(self) -> None:
        for line in ("Preferred: (a).", "Raising UnknownCode is preferred.",
                     "Raising UnknownCode is preferred, as the shopper sees why.",
                     "Raising UnknownCode is preferred; the shopper sees why.",
                     "(a) Raise UnknownCode (preferred)", "Preferred answer: (a).",
                     "Preferred option: (a).", "Raising UnknownCode is preferred"):
            with self.subTest(line=line):
                self.both(True, question(ASK, *TWO, line, DEFAULT))

    def test_oq_t6_preferred_before_other_words_does_not_recommend(self) -> None:
        for line in ("The preferred way is not clear.", "A preferred shopper pays less."):
            with self.subTest(line=line):
                self.both_detail(question(ASK, *TWO, line, DEFAULT), "recommendation",
                                 absent=("options", "default"))

    # T7: a mark at the end of an option line ---------------------------------------------------
    def test_oq_t7_recommendation_mark_at_the_end_of_an_option_item(self) -> None:
        for item in ("(a) Reject, preferred.", "(a) Reject it, recommended.",
                     "(a) Reject it (recommended)."):
            with self.subTest(item=item):
                self.both(True, question(ASK, item, "(b) Ignore it.", DEFAULT))

    def test_oq_t7_default_mark_at_the_end_of_an_option_item(self) -> None:
        for item in ("(a) Reject it (default).", "(a) Reject it, default."):
            with self.subTest(item=item):
                self.both(True, question(ASK, item, "(b) Ignore it.", REC))

    def test_oq_t7_mark_at_the_end_of_an_option_label_line(self) -> None:
        text = (f"**Q1. {ASK}**\n\n(a) Reject it, preferred.\n\n(b) Ignore it.\n\n"
                "(b) is the default until G2.")
        self.both(True, text)
        text = f"**Q1. {ASK}**\n\n(a) Reject it (default).\n\n(b) Ignore it.\n\n{REC}"
        self.both(True, text)

    def test_oq_t7_mark_items_without_the_other_part_still_fail(self) -> None:
        self.both_detail(question(ASK, "(a) Reject, preferred.", "(b) Ignore it."), "default",
                         absent=("options", "recommendation"))
        self.both_detail(question(ASK, "(a) Reject it (default).", "(b) Ignore it."),
                         "recommendation", absent=("options", "default"))

    # T8: suggest -------------------------------------------------------------------------------
    def test_oq_t8_suggest_before_an_option_label_or_word_recommends(self) -> None:
        for line in ("I suggest a) reject the code.", "I suggest a. reject the code.",
                     "I suggest a: reject the code.", "We suggest (b).", "I suggest (b).",
                     "I suggest option B.", "We suggest answer (a)."):
            with self.subTest(line=line):
                self.both(True, question(ASK, *TWO, line, DEFAULT))

    def test_oq_t8_suggest_before_other_words_does_not_recommend(self) -> None:
        for line in ("We suggest optional rounding.", "We suggest a new ExpiredCode error.",
                     "I suggest answering this later.", "We suggest an error.",
                     "I suggest a new rule for it."):
            with self.subTest(line=line):
                self.both_detail(question(ASK, *TWO, line, DEFAULT), "recommendation",
                                 absent=("options", "default"))

    # T9: the earlier forms still pass ----------------------------------------------------------
    def test_oq_t9_earlier_forms_still_pass(self) -> None:
        for name, text in (("list", OQ_LIST), ("inline", OQ_INLINE), ("table", OQ_TABLE),
                           ("numbered bold", ex_numbered()), ("bold q", ex_bold_q()),
                           ("s11 bold", ex_s11_bold())):
            with self.subTest(form=name):
                self.both(True, text)


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
            "not_applied": {"path": DELTA},
            "open_question": {"path": "docs/plans/*.md", "pattern": GAP}}

    def full(self, committed: bool = False) -> Path:
        files = {PLAN: plan("1. shopper.J2.", questions=OQ_LIST),
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

    def test_oq_c11_a_regex_that_is_not_valid_gives_a_json_failure(self) -> None:
        ws = self.full()
        base = {"path": "docs/plans/*.md", "pattern": GAP, "delta": "docs/plans/*.spec.md"}
        for key in ("pattern", "delta_pattern"):
            for bad in ("(expir", "[a-", "*expir"):
                with self.subTest(key=key, regex=bad):
                    self.expect(False, "open_question", ws, {**base, key: bad},
                                report=f"Open questions:\n{OQ_LIST}\n")

    def test_oq_c11_bad_input_gives_a_json_failure(self) -> None:
        ws = self.full()
        base = {"path": "docs/plans/*.md", "pattern": GAP}
        for args in ({**base, "path": 3}, {**base, "path": None}, {**base, "pattern": None},
                     {**base, "pattern": 3}, {**base, "delta": 3}, {**base, "delta": None},
                     {**base, "delta": f"{ws.as_posix()}/docs/plans/*.spec.md"},
                     {**base, "path": f"{ws.as_posix()}/docs/plans/*.md"}):
            with self.subTest(args=args):
                self.expect(False, "open_question", ws, args)

    def test_oq_c11_a_delta_that_is_not_utf8_gives_json(self) -> None:
        ws = self.full()
        (ws / "docs/plans/SHOP-14.spec.md").write_bytes(b"## ADDED checkout.R1: \xff\xfe\n")
        self.grade("open_question", ws, {"path": "docs/plans/*.md", "pattern": GAP,
                                         "delta": "docs/plans/SHOP-14*.spec.md"})

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
    FORMAT_GRADERS = {"job_story_ids", "not_applied", "open_question"}

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

    def test_oq_c10_p3_has_an_open_question_contract_check(self) -> None:
        names = [i["name"] for i in grader_checks(SCENARIOS["P3"])]
        self.assertEqual(names.count("open_question"), 1, names)
        item = self.item("P3", "open_question")
        gap = self.item("P3", "names_gap")
        self.assertEqual(item.get("kind"), "contract")
        self.assertEqual(gap.get("kind", "outcome"), "outcome")
        self.assertEqual(item["pattern"], gap["pattern"])
        self.assertEqual(item["delta"], "docs/plans/SHOP-14*.spec.md")
        self.assertIsInstance(item.get("delta_pattern"), str)
        self.assertTrue(item["delta_pattern"])

    def test_oq_c10_p3_open_question_passes_each_form_in_the_plan_and_the_report(self) -> None:
        args = grader_args(self.item("P3", "open_question"))
        for form in (OQ_LIST, OQ_INLINE, OQ_TABLE):
            with self.subTest(form=form[:20], source="plan"):
                files = {"docs/plans/SHOP-14.md": plan("1. shopper.J3.", questions=form)}
                self.expect(True, "open_question", self.workspace(files), args,
                            report="Plan written at docs/plans/SHOP-14.md.")
            with self.subTest(form=form[:20], source="report"):
                self.expect(True, "open_question", self.workspace(), args,
                            report=f"I wrote no plan.\n\nOpen questions:\n{form}\n")
        self.expect(True, "open_question", self.workspace(), args,
                    report="The ticket does not say what an expired code does: (a) refuse it, "
                           "(b) ignore it. I recommend (a). The default until G2 is (a).")

    def test_oq_c8_p3_weak_and_partial_outputs_fail_and_name_what_is_missing(self) -> None:
        args = grader_args(self.item("P3", "open_question"))
        p14 = "docs/plans/SHOP-14.md"

        def in_plan(questions: str) -> dict[str, str]:
            return {p14: plan("1. shopper.J3.", questions=questions)}

        weak = [
            ("only other questions", in_plan(question(
                "Must the checkout page show the code?", "(a) Show it.", "(b) Hide it.",
                "Recommendation: (a).", "Default until G2: the plan shows it.")), "", "gap"),
            ("None", in_plan("None. Expired codes raise UnknownCode."), "", "gap"),
            ("None in the report", {}, "None. Expired codes raise UnknownCode.", "gap"),
            ("no options", in_plan(question(ASK, REC, DEFAULT)), "", "options"),
            ("1 option", in_plan(question(ASK, "(a) Raise UnknownCode.", REC, DEFAULT)), "",
             "options"),
            ("no recommendation", in_plan(question(ASK, *TWO, DEFAULT)), "", "recommendation"),
            ("no default", in_plan(question(ASK, *TWO, REC)), "", "default"),
            ("default in the delta",
             {**in_plan(OQ_LIST), "docs/plans/SHOP-14.spec.md": requirement(
                 "ADDED", "checkout.R1", "Codes at checkout",
                 "amount_due MUST raise UnknownCode for an expired code.")}, "", "checkout.R1"),
        ]
        for name, files, report, missing in weak:
            with self.subTest(case=name):
                detail = self.expect(False, "open_question", self.workspace(files), args,
                                     report=report)
                self.assertIn(missing, detail)

    def test_oq_c10_p3_delta_pattern_catches_an_ended_code_in_the_delta(self) -> None:
        args = grader_args(self.item("P3", "open_question"))
        files = {"docs/plans/SHOP-14.md": plan("1. shopper.J3.", questions=OQ_LIST),
                 "docs/plans/SHOP-14.spec.md": requirement(
                     "ADDED", "checkout.R1", "A code that has ended raises UnknownCode")}
        self.expect(False, "open_question", self.workspace(files), args)

    def test_p5_delta_with_r3_passes_and_with_r2_fails(self) -> None:
        args = grader_args(self.item("P5", "new_ids"))
        self.expect(True, "new_ids", self.workspace({DELTA: added("cart.R3", "A gift note")}),
                    args)
        self.expect(False, "new_ids", self.workspace({DELTA: added("cart.R2", "A gift note")}),
                    args)


if __name__ == "__main__":
    unittest.main()
