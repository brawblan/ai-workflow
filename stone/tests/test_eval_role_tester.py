"""Tests for the role.tester eval in evals/role-tester/ (roadmap item 4b).

Each test builds a workspace as the runner does: the fixture, a base commit, and the `change` diff
as a second commit. Then it writes a test suite and runs grade.py as a subprocess, as `stone eval`
does. No model or harness starts. Each grade.py call also checks criterion 4 (no workspace change)
and criterion 5 (the last line is JSON with a boolean `pass` and a string `detail`).
"""

from __future__ import annotations

import contextlib
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

from stone import cli

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "evals" / "role-tester"
GRADE = EVAL / "grade.py"
SCENARIOS = {s["id"]: s for s in
             yaml.safe_load((EVAL / "scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]}
GIT_ENV = {"GIT_AUTHOR_NAME": "tester", "GIT_AUTHOR_EMAIL": "tester@example.com",
           "GIT_COMMITTER_NAME": "tester", "GIT_COMMITTER_EMAIL": "tester@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
SLUG = [f"mutants/slugify-m{n}.diff" for n in
        ("1-no-lower", "2-underscore", "3-keeps-plus", "4-edge-dashes")]

WEAK = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_true(self):\n" \
       "        self.assertTrue(True)\n"


def suite(imports: str, *bodies: str) -> str:
    """A unittest file: the import line, then one test method for each body."""
    methods = "".join(f"\n    def {body}\n" for body in bodies)
    return f"import unittest\n{imports}\n\n\nclass T(unittest.TestCase):{methods}"


SLUG_C1 = 'test_c1(self):\n        self.assertEqual(slugify("Hello World"), "hello-world")'
SLUG_STRONG = suite(
    "from src.text import slugify", SLUG_C1,
    'test_c2(self):\n        self.assertEqual(slugify("C++ & Rust!"), "c-rust")',
    'test_c3(self):\n        self.assertEqual(slugify("  --Hi--  "), "hi")')
PRICE_C1 = "test_c1(self):\n        self.assertAlmostEqual(total([(2.5, 2), (1.0, 3)]), {})"
PRICE_C2 = "test_c2(self):\n        self.assertAlmostEqual(total([(100.0, 1)], 10), {})"
PRICE_C3 = ("test_c3(self):\n        for pct in (-1, 101):\n"
            "            with self.assertRaises(ValueError):\n                total([(1.0, 1)], pct)")
PRICE_STRONG = suite("from src.prices import total", PRICE_C1.format(8.0), PRICE_C2.format(90.0),
                     PRICE_C3)
MEDIAN_STRONG = suite(
    "from src.stats import median",
    "test_odd(self):\n        self.assertEqual(median([3, 1, 2]), 2)",
    "test_even(self):\n        self.assertEqual(median([4, 1, 3, 2]), 2.5)",
    "test_input_not_changed(self):\n        values = [3, 1, 2]\n        median(values)\n"
    "        self.assertEqual(values, [3, 1, 2])")
CART_STRONG = suite(
    "from src.cart import Cart",
    'test_cart_r1_add_same_item_two_times(self):\n        cart = Cart()\n'
    '        cart.add("pen", 2)\n        cart.add("pen", 3)\n'
    '        self.assertEqual(cart.quantity("pen"), 5)',
    'test_cart_r2_remove_item(self):\n        cart = Cart()\n        cart.add("pen", 2)\n'
    '        cart.remove("pen")\n        self.assertEqual(cart.quantity("pen"), 0)',
    'test_cart_r2_remove_missing_raises_key_error(self):\n'
    '        with self.assertRaises(KeyError):\n            Cart().remove("ink")')
STRONG = {"T1": SLUG_STRONG, "T2": PRICE_STRONG, "T3": MEDIAN_STRONG, "T4": CART_STRONG}


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                            env={**os.environ, **GIT_ENV})
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {result.stderr}")
    return result.stdout


def commit(cwd: Path, message: str) -> None:
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "--allow-empty", "-m", message)


def grader_checks(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in scenario["expect"] if item["check"] == "grader"]


class GraderCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def workspace(self, scenario_id: str, files: dict[str, str] | None = None,
                  committed: bool = True) -> Path:
        """The fixture and the change of the scenario, then `files` (path: text)."""
        scenario = SCENARIOS[scenario_id]
        ws = self.tmp / scenario_id
        shutil.copytree(EVAL / scenario["fixture"], ws)
        git(ws, "init", "-q", "-b", "main")
        commit(ws, "chore: fixture base")
        git(ws, "apply", str(EVAL / scenario["change"]))
        commit(ws, "feat: the change under test")
        for rel, text in (files or {}).items():
            (ws / rel).parent.mkdir(parents=True, exist_ok=True)
            (ws / rel).write_text(text, encoding="utf-8")
        if files and committed:
            commit(ws, "test: tests")
        return ws

    def with_tests(self, scenario_id: str, text: str, committed: bool = True) -> Path:
        return self.workspace(scenario_id, {"tests/__init__.py": "", "tests/test_x.py": text},
                              committed)

    def grade(self, name: str, ws: Path, args: dict[str, Any]) -> tuple[bool, str]:
        before = git(ws, "status", "--porcelain")
        result = subprocess.run(
            [sys.executable, str(GRADE), name, "--workspace", str(ws), "--args", json.dumps(args)],
            cwd=EVAL, capture_output=True, text=True, timeout=600)
        self.assertEqual(git(ws, "status", "--porcelain"), before, f"{name} changed the workspace")
        lines = result.stdout.strip().splitlines()
        self.assertTrue(lines, f"no output: {result.stderr}")
        data = json.loads(lines[-1])
        self.assertIsInstance(data.get("pass"), bool, data)
        self.assertIsInstance(data.get("detail"), str, data)
        return data["pass"], data["detail"]


class KillsMutantsTest(GraderCase):
    def test_ac1_strong_suite_kills_all_mutants(self) -> None:
        passed, detail = self.grade("kills_mutants", self.with_tests("T1", SLUG_STRONG),
                                    {"mutants": SLUG})
        self.assertTrue(passed, detail)
        self.assertIn("4 of 4", detail)

    def test_ac1_default_min_is_all_and_detail_names_each_alive_mutant(self) -> None:
        ws = self.with_tests("T1", suite("from src.text import slugify", SLUG_C1))
        passed, detail = self.grade("kills_mutants", ws, {"mutants": SLUG})
        self.assertFalse(passed, detail)
        self.assertIn("2 of 4", detail)
        for alive in ("slugify-m3-keeps-plus", "slugify-m4-edge-dashes"):
            self.assertIn(alive, detail)
        for killed in ("slugify-m1-no-lower", "slugify-m2-underscore"):
            self.assertNotIn(killed, detail)

    def test_ac1_min_is_the_number_of_mutants_to_kill(self) -> None:
        ws = self.with_tests("T1", suite("from src.text import slugify", SLUG_C1))
        for minimum, expected in ((2, True), (3, False)):
            with self.subTest(min=minimum):
                passed, detail = self.grade("kills_mutants", ws, {"mutants": SLUG, "min": minimum})
                self.assertEqual(passed, expected, detail)

    def test_ac1_tests_that_fail_on_the_code_fail_the_check(self) -> None:
        ws = self.with_tests("T1", SLUG_STRONG.replace('"hello-world"', '"Hello-World"'))
        passed, detail = self.grade("kills_mutants", ws, {"mutants": SLUG, "min": 0})
        self.assertFalse(passed, detail)

    def test_ac1_mutant_that_does_not_apply_is_named(self) -> None:
        ws = self.with_tests("T1", SLUG_STRONG)
        bad = "mutants/median-m1-no-sort.diff"
        passed, detail = self.grade("kills_mutants", ws, {"mutants": [SLUG[0], bad], "min": 1})
        self.assertFalse(passed, detail)
        self.assertIn("median-m1-no-sort", detail)


class PassesWithPatchTest(GraderCase):
    FIX = {"patch": "fixtures/prices-fix.diff"}

    def test_ac2_tests_that_find_the_bug_pass(self) -> None:
        passed, detail = self.grade("passes_with_patch", self.with_tests("T2", PRICE_STRONG), self.FIX)
        self.assertTrue(passed, detail)

    def test_ac2_tests_that_pass_on_the_code_with_the_bug_fail(self) -> None:
        locked = suite("from src.prices import total", PRICE_C1.format(8.0), PRICE_C2.format(10.0))
        passed, detail = self.grade("passes_with_patch", self.with_tests("T2", locked), self.FIX)
        self.assertFalse(passed, detail)

    def test_ac2_tests_that_still_fail_after_the_fix_fail(self) -> None:
        wrong = suite("from src.prices import total", PRICE_C1.format(9.0), PRICE_C2.format(90.0))
        passed, detail = self.grade("passes_with_patch", self.with_tests("T2", wrong), self.FIX)
        self.assertFalse(passed, detail)

    def test_ac2_patch_that_does_not_apply_fails_and_is_named(self) -> None:
        ws = self.with_tests("T2", PRICE_STRONG)
        passed, detail = self.grade("passes_with_patch", ws, {"patch": SLUG[0]})
        self.assertFalse(passed, detail)
        self.assertIn("slugify-m1-no-lower", detail)


class TestNamesTest(GraderCase):
    def names(self, *names: str, path: str = "tests/test_x.py") -> Path:
        body = "".join(f"\n    def {name}(self):\n        pass\n" for name in names)
        return self.workspace("T4", {path: f"import unittest\n\n\nclass T(unittest.TestCase):{body}"})

    def check(self, ws: Path, ids: list[str]) -> tuple[bool, str]:
        return self.grade("test_names", ws, {"ids": ids})

    def test_ac3_id_as_a_word_of_a_test_name_passes(self) -> None:
        for name in ("test_cart_r1_add", "test_r1", "test_add_r1", "test_CART_R1_add"):
            with self.subTest(name=name):
                shutil.rmtree(self.tmp / "T4", ignore_errors=True)
                passed, detail = self.check(self.names(name), ["r1"])
                self.assertTrue(passed, detail)

    def test_ac3_id_case_does_not_matter(self) -> None:
        passed, detail = self.check(self.names("test_cart_r1_add"), ["R1"])
        self.assertTrue(passed, detail)

    def test_ac3_id_inside_a_longer_word_does_not_count(self) -> None:
        passed, detail = self.check(self.names("test_r10", "test_error1", "testr1"), ["r1"])
        self.assertFalse(passed, detail)
        self.assertIn("r1", detail)

    def test_ac3_detail_names_only_the_missing_ids(self) -> None:
        passed, detail = self.check(self.names("test_cart_r1_add"), ["r1", "r2"])
        self.assertFalse(passed, detail)
        self.assertIn("r2", detail)
        self.assertNotIn("r1", detail)

    def test_ac3_a_function_that_is_not_a_test_does_not_count(self) -> None:
        passed, detail = self.check(self.names("helper_r1", "check_r1"), ["r1"])
        self.assertFalse(passed, detail)

    def test_ac3_test_files_in_subfolders_of_tests_count(self) -> None:
        passed, detail = self.check(self.names("test_r1", path="tests/unit/test_y.py"), ["r1"])
        self.assertTrue(passed, detail)

    def test_ac3_python_files_outside_tests_do_not_count(self) -> None:
        passed, detail = self.check(self.names("test_r1", path="src/test_y.py"), ["r1"])
        self.assertFalse(passed, detail)

    def test_ac3_no_tests_folder_fails_with_json(self) -> None:
        passed, detail = self.check(self.workspace("T4"), ["r1"])
        self.assertFalse(passed, detail)


class NoChangeAndOutputTest(GraderCase):
    def test_ac4_graders_do_not_change_a_workspace_with_uncommitted_tests(self) -> None:
        ws = self.with_tests("T2", PRICE_STRONG, committed=False)
        self.assertIn("tests/", git(ws, "status", "--porcelain"))
        self.grade("passes_with_patch", ws, {"patch": "fixtures/prices-fix.diff"})
        self.grade("kills_mutants", ws, {"mutants": []})
        self.grade("test_names", ws, {"ids": ["r1"]})

    def test_ac5_run_arg_replaces_the_default_test_command(self) -> None:
        ws = self.workspace("T1", {"checks/__init__.py": "", "checks/test_x.py": SLUG_STRONG})
        passed, detail = self.grade("kills_mutants", ws, {"mutants": SLUG})
        self.assertFalse(passed, "the default command must not find checks/: " + detail)
        run = "python -m unittest discover -s checks -t ."
        passed, detail = self.grade("kills_mutants", ws, {"mutants": SLUG, "run": run})
        self.assertTrue(passed, detail)

    def test_ac5_run_arg_that_fails_fails_the_check(self) -> None:
        ws = self.with_tests("T1", SLUG_STRONG)
        passed, detail = self.grade("kills_mutants", ws, {"mutants": SLUG,
                                                          "run": "python -c 'raise SystemExit(1)'"})
        self.assertFalse(passed, detail)


class EvalValidTest(unittest.TestCase):
    def test_ac6_check_only_exits_0(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["eval", "role.tester", "--root", str(REPO), "--check-only"])
        self.assertEqual(code, 0, out.getvalue())


class FixturesTest(GraderCase):
    def test_ac7_each_patch_applies_to_the_fixture_with_its_change(self) -> None:
        for sid, scenario in SCENARIOS.items():
            ws = self.workspace(sid)
            patches = [p for item in grader_checks(scenario)
                       for p in item.get("mutants", []) + ([item["patch"]] if "patch" in item else [])]
            for patch in patches:
                with self.subTest(scenario=sid, patch=patch):
                    git(ws, "apply", "--check", str(EVAL / patch))

    def test_ac7_correct_suite_passes_each_grader_check(self) -> None:
        self.assertEqual(sorted(SCENARIOS), sorted(STRONG))
        for sid, scenario in SCENARIOS.items():
            ws = self.with_tests(sid, STRONG[sid])
            for item in grader_checks(scenario):
                args = {k: v for k, v in item.items() if k not in {"check", "kind", "name"}}
                with self.subTest(scenario=sid, grader=item["name"]):
                    passed, detail = self.grade(item["name"], ws, args)
                    self.assertTrue(passed, detail)
            shutil.rmtree(ws)

    def test_ac7_trivial_suite_fails_each_kills_mutants_and_passes_with_patch_check(self) -> None:
        for sid, scenario in SCENARIOS.items():
            ws = self.with_tests(sid, WEAK)
            for item in grader_checks(scenario):
                if item["name"] not in {"kills_mutants", "passes_with_patch"}:
                    continue
                args = {k: v for k, v in item.items() if k not in {"check", "kind", "name"}}
                with self.subTest(scenario=sid, grader=item["name"]):
                    passed, detail = self.grade(item["name"], ws, args)
                    self.assertFalse(passed, detail)
            shutil.rmtree(ws)


if __name__ == "__main__":
    unittest.main()
