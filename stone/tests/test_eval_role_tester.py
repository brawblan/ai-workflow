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
import py_compile
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
FIX = {"patch": "fixtures/prices-fix.diff"}
GRADERS = ("kills_mutants", "passes_with_patch", "test_names")


def suite(imports: str, *bodies: str) -> str:
    """A unittest file: the import line, then one test method for each body."""
    methods = "".join(f"\n    def {body}\n" for body in bodies)
    return f"import unittest\n{imports}\n\n\nclass T(unittest.TestCase):{methods}"


TRUE = "test_true(self):\n        self.assertTrue(True)"
WEAK = suite("", TRUE)
SLUG_IMPORT = "from src.text import slugify"
SLUG_C1 = 'test_c1(self):\n        self.assertEqual(slugify("Hello World"), "hello-world")'
SLUG_C2 = 'test_c2(self):\n        self.assertEqual(slugify("C++ & Rust!"), "c-rust")'
SLUG_C3 = 'test_c3(self):\n        self.assertEqual(slugify("  --Hi--  "), "hi")'
SLUG_WRONG = SLUG_C1.replace('"hello-world"', '"Hello-World"')  # fails on the code
SLUG_FINDING = 'test_finding(self):\n        self.assertEqual(slugify("Café"), "café")'  # fails
SLUG_STRONG = suite(SLUG_IMPORT, SLUG_C1, SLUG_C2, SLUG_C3)
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


def grader_args(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in {"check", "kind", "name"}}


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

    def grade(self, name: str, ws: Path, args: dict[str, Any] | str,
              env: dict[str, str] | None = None) -> tuple[bool, str]:
        """Run grade.py. A str `args` goes to --args as it is. grade.py itself writes no .pyc."""
        before = git(ws, "status", "--porcelain")
        raw = args if isinstance(args, str) else json.dumps(args)
        result = subprocess.run(
            [sys.executable, "-B", str(GRADE), name, "--workspace", str(ws), "--args", raw],
            cwd=EVAL, capture_output=True, text=True, timeout=600,
            env={**os.environ, **(env or {})})
        self.assertEqual(git(ws, "status", "--porcelain"), before, f"{name} changed the workspace")
        lines = result.stdout.strip().splitlines()
        self.assertTrue(lines, f"no output: {result.stderr}")
        data = json.loads(lines[-1])
        self.assertIsInstance(data.get("pass"), bool, data)
        self.assertIsInstance(data.get("detail"), str, data)
        return data["pass"], data["detail"]

    def expect(self, expected: bool, name: str, ws: Path, args: dict[str, Any] | str,
               env: dict[str, str] | None = None) -> str:
        """Grade, assert the `pass` value, and return the detail."""
        passed, detail = self.grade(name, ws, args, env)
        self.assertEqual(passed, expected, detail)
        return detail


class KillsMutantsTest(GraderCase):
    def test_ac1_strong_suite_kills_all_mutants(self) -> None:
        ws = self.with_tests("T1", SLUG_STRONG)
        self.assertIn("4 of 4", self.expect(True, "kills_mutants", ws, {"mutants": SLUG}))

    def test_ac1_default_min_is_all_and_detail_names_each_alive_mutant(self) -> None:
        ws = self.with_tests("T1", suite(SLUG_IMPORT, SLUG_C1))
        detail = self.expect(False, "kills_mutants", ws, {"mutants": SLUG})
        self.assertIn("2 of 4", detail)
        for alive in ("slugify-m3-keeps-plus", "slugify-m4-edge-dashes"):
            self.assertIn(alive, detail)
        for killed in ("slugify-m1-no-lower", "slugify-m2-underscore"):
            self.assertNotIn(killed, detail)

    def test_ac1_min_is_the_number_of_mutants_to_kill(self) -> None:
        ws = self.with_tests("T1", suite(SLUG_IMPORT, SLUG_C1))
        for minimum, expected in ((2, True), (3, False)):
            with self.subTest(min=minimum):
                self.expect(expected, "kills_mutants", ws, {"mutants": SLUG, "min": minimum})

    def test_ac1_a_test_that_fails_on_the_code_is_a_finding_and_kills_nothing(self) -> None:
        ws = self.with_tests("T1", suite(SLUG_IMPORT, SLUG_WRONG, TRUE))
        self.assertIn("0 of 4", self.expect(False, "kills_mutants", ws, {"mutants": SLUG}))
        self.expect(True, "kills_mutants", ws, {"mutants": SLUG, "min": 0})

    def test_ac1_no_test_passes_on_the_code_fails_the_check(self) -> None:
        ws = self.with_tests("T1", suite(SLUG_IMPORT, SLUG_WRONG))
        self.expect(False, "kills_mutants", ws, {"mutants": SLUG, "min": 0})

    def test_ac1_a_test_that_does_not_run_on_a_mutant_kills_it(self) -> None:
        # On m2 the module does not import, so test_true does not run. m3 changes nothing here.
        guard = f'{SLUG_IMPORT}\nif slugify("a b") != "a-b":\n    raise ImportError("m2")'
        ws = self.with_tests("T1", suite(guard, TRUE))
        detail = self.expect(True, "kills_mutants", ws, {"mutants": SLUG[1:3], "min": 1})
        self.assertIn("1 of 2", detail)
        self.assertIn("slugify-m3-keeps-plus", detail)

    def test_ac1_mutant_that_does_not_apply_is_named(self) -> None:
        ws = self.with_tests("T1", SLUG_STRONG)
        args = {"mutants": [SLUG[0], "mutants/median-m1-no-sort.diff"], "min": 1}
        self.assertIn("median-m1-no-sort", self.expect(False, "kills_mutants", ws, args))

    def test_ac10_t1_correct_suite_without_a_criterion_3_test_leaves_m4_alive(self) -> None:
        ws = self.with_tests("T1", suite(SLUG_IMPORT, SLUG_C1, SLUG_C2))
        args = grader_args(grader_checks(SCENARIOS["T1"])[0])
        detail = self.expect(False, "kills_mutants", ws, args)
        self.assertIn("3 of 4", detail)
        self.assertIn("slugify-m4-edge-dashes", detail)

    def test_ac10_t1_correct_suite_with_a_kept_failing_test_passes(self) -> None:
        ws = self.with_tests("T1", suite(SLUG_IMPORT, SLUG_C1, SLUG_C2, SLUG_C3, SLUG_FINDING))
        args = grader_args(grader_checks(SCENARIOS["T1"])[0])
        self.assertIn("4 of 4", self.expect(True, "kills_mutants", ws, args))


class PassesWithPatchTest(GraderCase):
    def check(self, expected: bool, *bodies: str) -> None:
        ws = self.with_tests("T2", suite("from src.prices import total", *bodies))
        self.expect(expected, "passes_with_patch", ws, FIX)

    def test_ac2_tests_that_find_the_bug_pass(self) -> None:
        self.expect(True, "passes_with_patch", self.with_tests("T2", PRICE_STRONG), FIX)

    def test_ac2_no_test_fails_on_the_code_with_the_bug_fails(self) -> None:
        self.check(False, PRICE_C1.format(8.0), PRICE_C2.format(10.0))

    def test_ac2_other_tests_that_fail_after_the_patch_do_not_fail_the_check(self) -> None:
        self.check(True, PRICE_C1.format(9.0), PRICE_C2.format(90.0))

    def test_ac2_the_test_that_fails_on_the_code_must_pass_after_the_patch(self) -> None:
        # c1 fails before and after the fix. c2 passes before the fix and fails after it.
        self.check(False, PRICE_C1.format(9.0), PRICE_C2.format(10.0))

    def test_ac2_patch_that_does_not_apply_fails_and_is_named(self) -> None:
        ws = self.with_tests("T2", PRICE_STRONG)
        detail = self.expect(False, "passes_with_patch", ws, {"patch": SLUG[0]})
        self.assertIn("slugify-m1-no-lower", detail)


class TestNamesTest(GraderCase):
    def names(self, *names: str, path: str = "tests/test_x.py") -> Path:
        body = "".join(f"\n    def {name}(self):\n        pass\n" for name in names)
        return self.workspace("T4", {path: f"import unittest\n\n\nclass T(unittest.TestCase):{body}"})

    def check(self, expected: bool, ws: Path, ids: list[str]) -> str:
        return self.expect(expected, "test_names", ws, {"ids": ids})

    def test_ac3_id_as_a_word_of_a_test_name_passes(self) -> None:
        for name in ("test_cart_r1_add", "test_r1", "test_add_r1", "test_CART_R1_add"):
            with self.subTest(name=name):
                shutil.rmtree(self.tmp / "T4", ignore_errors=True)
                self.check(True, self.names(name), ["r1"])

    def test_ac3_id_case_does_not_matter(self) -> None:
        self.check(True, self.names("test_cart_r1_add"), ["R1"])

    def test_ac3_id_inside_a_longer_word_does_not_count(self) -> None:
        self.assertIn("r1", self.check(False, self.names("test_r10", "test_error1", "testr1"),
                                       ["r1"]))

    def test_ac3_detail_names_only_the_missing_ids(self) -> None:
        detail = self.check(False, self.names("test_cart_r1_add"), ["r1", "r2"])
        self.assertIn("r2", detail)
        self.assertNotIn("r1", detail)

    def test_ac3_a_function_that_is_not_a_test_does_not_count(self) -> None:
        self.check(False, self.names("helper_r1", "check_r1"), ["r1"])

    def test_ac3_test_files_in_subfolders_of_tests_count(self) -> None:
        self.check(True, self.names("test_r1", path="tests/unit/test_y.py"), ["r1"])

    def test_ac3_python_files_outside_tests_do_not_count(self) -> None:
        self.check(False, self.names("test_r1", path="src/test_y.py"), ["r1"])

    def test_ac3_no_tests_folder_fails_with_json(self) -> None:
        self.check(False, self.workspace("T4"), ["r1"])

    def test_ac8_names_in_comments_and_strings_do_not_count(self) -> None:
        text = ('import unittest\n# def test_r1(self):\nDOC = """\ndef test_r1(self):\n"""\n\n\n'
                'class T(unittest.TestCase):\n    def test_other(self):\n'
                '        "def test_r1(self): pass"\n')
        self.check(False, self.workspace("T4", {"tests/test_x.py": text}), ["r1"])

    def test_ac8_a_file_that_does_not_parse_has_no_names(self) -> None:
        ws = self.workspace("T4", {"tests/test_bad.py": "def test_r1(self):\n    return (\n",
                                   "tests/test_ok.py": "def test_r2():\n    pass\n"})
        self.check(False, ws, ["r1"])
        self.check(True, ws, ["r2"])


class NoChangeAndOutputTest(GraderCase):
    def test_ac4_graders_do_not_change_a_workspace_with_uncommitted_tests(self) -> None:
        ws = self.with_tests("T2", PRICE_STRONG, committed=False)
        self.assertIn("tests/", git(ws, "status", "--porcelain"))
        self.grade("passes_with_patch", ws, FIX)
        self.grade("kills_mutants", ws, {"mutants": []})
        self.grade("test_names", ws, {"ids": ["r1"]})

    def test_ac5_missing_key_or_args_that_are_not_json_give_a_json_failure(self) -> None:
        ws = self.with_tests("T2", PRICE_STRONG)  # c2 fails on the code, so the patch is read
        for name in GRADERS:
            for args in ({}, "{not json"):
                with self.subTest(name=name, args=args):
                    self.expect(False, name, ws, args)

    def test_ac5_args_that_are_not_a_json_object_give_a_json_failure(self) -> None:
        ws = self.with_tests("T2", PRICE_STRONG)
        for name in GRADERS:
            with self.subTest(name=name):
                self.expect(False, name, ws, "[]")

    def test_ac5_tests_arg_gives_the_unittest_start_folder(self) -> None:
        ws = self.workspace("T1", {"checks/__init__.py": "", "checks/test_x.py": SLUG_STRONG})
        self.expect(False, "kills_mutants", ws, {"mutants": SLUG})
        self.expect(True, "kills_mutants", ws, {"mutants": SLUG, "tests": "checks"})

    def test_ac5_top_arg_gives_the_unittest_top_folder(self) -> None:
        # A relative import in tests/ works only if the top folder is above tests/.
        test = suite(f"{SLUG_IMPORT}\nfrom .cases import C1",
                     'test_c1(self):\n        self.assertEqual(slugify("Hello World"), C1)')
        ws = self.workspace("T1", {"tests/__init__.py": "", "tests/test_x.py": test,
                                   "tests/cases.py": 'C1 = "hello-world"\n'})
        self.expect(True, "kills_mutants", ws, {"mutants": SLUG[:2]})
        self.expect(False, "kills_mutants", ws, {"mutants": SLUG[:2], "top": "tests"})

    def test_ac5_run_arg_is_gone(self) -> None:
        ws = self.with_tests("T1", SLUG_STRONG)
        args = {"mutants": SLUG, "run": "python -c 'raise SystemExit(1)'"}
        self.expect(True, "kills_mutants", ws, args)

    def test_ac9_a_bytecode_cache_in_the_workspace_is_not_used(self) -> None:
        # Python never checks an unchecked-hash .pyc against its source, as with a stale .pyc
        # from the same second. If the copy kept it, the one-character mutant m2 would live.
        ws = self.with_tests("T1", suite(SLUG_IMPORT, SLUG_C1))
        source = ws / "src" / "text.py"
        cache = source.parent / "__pycache__" / f"text.{sys.implementation.cache_tag}.pyc"
        py_compile.compile(str(source), cfile=str(cache), doraise=True,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        self.expect(True, "kills_mutants", ws, {"mutants": [SLUG[1]]})

    def test_ac9_the_graders_write_no_bytecode(self) -> None:
        ws = self.with_tests("T2", PRICE_STRONG)
        prefix = self.tmp / "pycache-prefix"
        env = {"PYTHONPYCACHEPREFIX": str(prefix)}
        self.grade("kills_mutants", ws, {"mutants": []}, env)
        self.grade("passes_with_patch", ws, FIX, env)
        self.assertEqual(sorted(prefix.rglob("*.pyc")) if prefix.exists() else [], [])


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
                with self.subTest(scenario=sid, grader=item["name"]):
                    self.expect(True, item["name"], ws, grader_args(item))
            shutil.rmtree(ws)

    def test_ac7_trivial_suite_fails_each_kills_mutants_and_passes_with_patch_check(self) -> None:
        for sid, scenario in SCENARIOS.items():
            ws = self.with_tests(sid, WEAK)
            for item in grader_checks(scenario):
                if item["name"] in {"kills_mutants", "passes_with_patch"}:
                    with self.subTest(scenario=sid, grader=item["name"]):
                        self.expect(False, item["name"], ws, grader_args(item))
            shutil.rmtree(ws)


if __name__ == "__main__":
    unittest.main()
