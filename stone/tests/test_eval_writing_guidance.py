"""Tests for the real eval folder evals/writing-guidance/ and its grader (EVAL-GUIDANCE-1, D69).

No model starts. The grader runs as a subprocess, as `stone eval` runs it.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

import re

from stone import cli, evals

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "evals" / "writing-guidance"
GRADE = EVAL / "grade.py"
CHECKS = ["k17_errors", "sentence_length", "vague_words", "paragraph_length",
          "answer_first", "no_filler_close", "max_words"]
WEAK_FAILS = ("k17_errors", "sentence_length", "vague_words", "answer_first", "no_filler_close")
LONG_PARAGRAPH = ("The cart is empty. The user adds a line. The line has a name. The line has a "
                  "price. The user saves the line. The saved line leaves the cart. The total "
                  "changes.\n")

STRONG = """Add a cart feature to save a line for later.

The change adds Cart.save_for_later(name). It moves a line from the cart to a saved list.
A saved line does not count in the total.

The unit tests pass. To undo the change, revert the merge commit.
"""
WEAK = ("Sure! Let me write that for you.\n\n"
        "We simply leverage a robust cart so that the saved list is used when the user wants to "
        "move a line out of the cart and then later on bring the same line back into the cart "
        "again without any loss of the price or of the name or of the count of the items in it.\n\n"
        "Let me know if you need anything else!\n")


def grade(name: str, report: str, args: str = "{}") -> tuple[int, dict]:
    with tempfile.TemporaryDirectory() as ws:
        env = {**os.environ, "STONE_EVAL_REPORT": report}
        done = subprocess.run([sys.executable, str(GRADE), name, "--workspace", ws, "--args", args],
                              capture_output=True, text=True, env=env)
    lines = done.stdout.strip().splitlines()
    return done.returncode, (json.loads(lines[-1]) if lines else {})


class RealEvalFolderTest(unittest.TestCase):
    def test_ac7_variants_are_none_always_current_short(self) -> None:
        data = evals.load_scenarios(EVAL)
        self.assertEqual(list(data["variants"]), ["none", "always", "current", "short"])
        self.assertEqual(data["variants"]["none"], [])

    def test_ac7_every_copy_file_exists(self) -> None:
        data = yaml.safe_load((EVAL / "scenarios.yaml").read_text(encoding="utf-8"))
        for name, files in data["variants"].items():
            for item in files:
                self.assertTrue((EVAL / item["copy"]).is_file(), f"{name}: {item['copy']}")

    def test_ac7_find_component_finds_guidance_writing(self) -> None:
        entry = evals.find_component(REPO / "framework", "claude-code", "guidance.writing", REPO)
        self.assertEqual(entry["kind"], "guidance")
        self.assertEqual(entry["eval"], "evals/writing-guidance/")

    def test_ac7_check_only_exits_0_and_lists_four_scenarios_with_12_runs(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["eval", "guidance.writing", "--check-only", "--model",
                             "claude-sonnet-5-5", "--trials", "3", "--root", str(REPO)])
        text = out.getvalue()
        self.assertEqual(code, 0, text)
        for sid in ("W1", "W2", "W3", "W4"):
            self.assertIn(sid, text)
        self.assertEqual(text.count("12 run"), 4, text)

    def test_acE_fixture_has_pyproject(self) -> None:
        self.assertTrue((EVAL / "fixtures/shop/pyproject.toml").is_file())

    def test_acA_real_eval_yaml_has_a_read_only_guidance_command(self) -> None:
        config = yaml.safe_load((REPO / "framework/adapters/claude-code/eval.yaml")
                                .read_text(encoding="utf-8"))
        command = config["run"]["guidance"]
        self.assertIsInstance(command, list)
        self.assertNotIn("--agent", command)
        self.assertEqual(command[command.index("--permission-mode") + 1], "default")
        self.assertIn("$prompt", command)
        for banned in ("Edit", "Write", "MultiEdit"):
            self.assertNotIn(banned, config["tools"]["writer"])
        self.assertIsInstance(evals.load_run_config(REPO / "framework/adapters/claude-code/eval.yaml")
                              ["run"]["guidance"], list)

    def test_acA_role_and_hook_commands_are_unchanged(self) -> None:
        config = yaml.safe_load((REPO / "framework/adapters/claude-code/eval.yaml")
                                .read_text(encoding="utf-8"))
        self.assertIn("--agent", config["run"]["with"])
        self.assertNotIn("--agent", config["run"]["without"])
        self.assertEqual(config["run"]["with"][config["run"]["with"].index("--permission-mode") + 1],
                         "acceptEdits")

    def test_acD_scenarios_do_not_use_dictionary_terms(self) -> None:
        text = (EVAL / "scenarios.yaml").read_text(encoding="utf-8")
        self.assertNotIn("dictionary_terms", text)

    def test_acD_w2_pattern_needs_the_cause(self) -> None:
        data = yaml.safe_load((EVAL / "scenarios.yaml").read_text(encoding="utf-8"))
        w2 = next(s for s in data["scenarios"] if s["id"] == "W2")
        pattern = next(c["pattern"] for c in w2["expect"] if c["check"] == "matches")
        find = lambda text: re.search(pattern, text, re.I | re.M)  # noqa: E731
        self.assertTrue(find("Cart.total() clamps the sum at zero."))
        self.assertFalse(find("The discount line has a negative price."))

    def test_ac7_scenarios_use_only_known_graders(self) -> None:
        data = yaml.safe_load((EVAL / "scenarios.yaml").read_text(encoding="utf-8"))
        names = {c["name"] for s in data["scenarios"] for c in s["expect"]
                 if c.get("check") == "grader"}
        self.assertTrue(names)
        self.assertLessEqual(names, set(CHECKS))


class GraderTest(unittest.TestCase):
    def test_ac8_strong_text_passes_every_check(self) -> None:
        for name in CHECKS:
            with self.subTest(name=name):
                code, result = grade(name, STRONG, '{"limit": 200}')
                self.assertEqual(code, 0)
                self.assertTrue(result["pass"], result)
                self.assertIn("detail", result)

    def test_ac8_weak_text_fails_the_matching_checks(self) -> None:
        for name in WEAK_FAILS:
            with self.subTest(name=name):
                code, result = grade(name, WEAK)
                self.assertEqual(code, 0)
                self.assertFalse(result["pass"], result)

    def test_acD_dictionary_terms_grader_is_removed(self) -> None:
        code, _ = grade("dictionary_terms", STRONG)
        self.assertNotEqual(code, 0)

    FENCES = ("```", "~~~", "```markdown", "~~~text", "````")

    def fenced(self, text: str, fence: str, tail: str) -> str:
        return f"{fence}\n{text}{fence.rstrip('abcdefghijklmnopqrstuvwxyz')}{tail}"

    def test_acD_fenced_weak_text_fails_like_the_unfenced_one(self) -> None:
        for fence in self.FENCES:
            for name in WEAK_FAILS:
                with self.subTest(fence=fence, name=name):
                    _, result = grade(name, self.fenced(WEAK, fence, ""))
                    self.assertFalse(result["pass"], result)

    def test_acD_fenced_weak_text_with_a_final_newline_fails_too(self) -> None:
        # A reply from a harness often ends with a newline after the closing fence.
        for fence in self.FENCES:
            for name in WEAK_FAILS:
                with self.subTest(fence=fence, name=name):
                    _, result = grade(name, self.fenced(WEAK, fence, "\n"))
                    self.assertFalse(result["pass"], result)

    def test_acD_fenced_strong_text_passes(self) -> None:
        for name in CHECKS:
            with self.subTest(name=name):
                _, result = grade(name, f"```\n{STRONG}```", '{"limit": 200}')
                self.assertTrue(result["pass"], result)

    def test_acD_fence_removal_changes_the_word_count(self) -> None:
        self.assertTrue(grade("max_words", "```\none two\n```", '{"limit": 2}')[1]["pass"])

    def test_acD_fence_around_only_part_of_the_text_is_kept(self) -> None:
        part = "Sure! Let me help.\n```\ncode\n```\nDone."
        self.assertFalse(grade("answer_first", part)[1]["pass"])
        tail = "The total is 5.\n```\nLet me know if you need more\n```"
        self.assertEqual(grade("max_words", tail, '{"limit": 7}')[1]["pass"], False)
        self.assertTrue(grade("max_words", tail, '{"limit": 100}')[1]["pass"])

    def test_acD_paragraph_of_seven_short_sentences_fails(self) -> None:
        self.assertFalse(grade("paragraph_length", LONG_PARAGRAPH)[1]["pass"])
        self.assertTrue(grade("paragraph_length", STRONG)[1]["pass"])

    def test_ac8_empty_report_fails_every_check(self) -> None:
        for name in CHECKS:
            for report in ("", "  \n\n "):
                with self.subTest(name=name, report=report):
                    code, result = grade(name, report, '{"limit": 100}')
                    self.assertEqual(code, 0)
                    self.assertFalse(result["pass"], result)

    def test_ac8_max_words_uses_the_limit(self) -> None:
        text = "one two three four five"
        self.assertTrue(grade("max_words", text, '{"limit": 5}')[1]["pass"])
        self.assertFalse(grade("max_words", text, '{"limit": 4}')[1]["pass"])

    def test_ac8_last_output_line_is_json_with_pass_and_detail(self) -> None:
        _, result = grade("answer_first", STRONG)
        self.assertEqual(set(result), {"pass", "detail"})
        self.assertIsInstance(result["pass"], bool)

    def test_ac8_answer_first_and_filler_close_look_at_the_right_line(self) -> None:
        self.assertFalse(grade("answer_first", "Certainly. The total is 5.")[1]["pass"])
        self.assertTrue(grade("answer_first", "The total is 5.\nHope this helps")[1]["pass"])
        self.assertFalse(grade("no_filler_close", "The total is 5.\nFeel free to ask.")[1]["pass"])
        self.assertTrue(grade("no_filler_close", "Let me know is a phrase.\nThe total is 5.")[1]["pass"])

    def test_ac8_unknown_grader_name_exits_non_zero(self) -> None:
        code, _ = grade("not_a_grader", STRONG)
        self.assertNotEqual(code, 0)

    def test_ac8_grader_does_not_change_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as ws:
            subprocess.run([sys.executable, str(GRADE), "k17_errors", "--workspace", ws,
                            "--args", "{}"], capture_output=True, text=True,
                           env={**os.environ, "STONE_EVAL_REPORT": STRONG})
            self.assertEqual(list(Path(ws).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
