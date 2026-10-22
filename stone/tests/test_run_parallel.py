"""Tests for run_parallel.py, the runner that runs each test class in its own subprocess.

Each test makes a temporary folder with tiny test modules, so it does not run the real suite.
The module names start with `test_rp_` so they do not collide with the real test modules.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

import run_parallel

PASSING = """import unittest


class Passing(unittest.TestCase):
    def test_one(self):
        self.assertTrue(True)

    def test_two(self):
        self.assertEqual(1 + 1, 2)
"""

FAILING = """import unittest


class Failing(unittest.TestCase):
    def test_fails(self):
        self.assertEqual(1, 2, "MARKER-expected-failure")
"""

# Two classes with tests, and one mixin class with no tests. The mixin must not become a unit.
TWO_CLASSES = """import unittest


class Mixin:
    def helper(self):
        return 1


class Small(Mixin, unittest.TestCase):
    def test_a(self):
        self.assertEqual(self.helper(), 1)


class Large(unittest.TestCase):
    def test_a(self):
        pass

    def test_b(self):
        pass

    def test_c(self):
        pass


class NoTests(unittest.TestCase):
    def helper(self):
        return 2
"""

# One test, but a large file: the order must follow the test count, not the file size.
ONE_TEST_LARGE_FILE = "import unittest\n\n" + "# padding\n" * 500 + """

class Lonely(unittest.TestCase):
    def test_only(self):
        pass
"""

IMPORT_ERROR = """import unittest
import test_rp_no_such_module_xyz  # ImportError


class NeverLoaded(unittest.TestCase):
    def test_x(self):
        pass
"""

RUNTIME_ERROR_AT_IMPORT = """import unittest

raise RuntimeError("MARKER-import-crash")


class NeverLoaded(unittest.TestCase):
    def test_x(self):
        pass
"""


@contextlib.contextmanager
def make_folder(files: dict[str, str]) -> Iterator[Path]:
    """Write `files` into a temporary folder and yield the folder."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for name, text in files.items():
            (folder / name).write_text(text, encoding="utf-8")
        yield folder


def run_in(files: dict[str, str], quiet: bool = False) -> tuple[int, str]:
    """Write `files` into a temporary folder, run the runner on it, and return (exit code, output)."""
    with make_folder(files) as folder:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_parallel.main(folder, jobs=2, quiet=quiet)
        return code, out.getvalue()


def discover_count(folder: Path) -> int:
    """Return the number of tests that `unittest discover -s folder` finds. Restore the import state."""
    saved_path = list(sys.path)
    saved_modules = dict(sys.modules)
    try:
        return unittest.TestLoader().discover(str(folder), top_level_dir=str(folder)).countTestCases()
    finally:
        sys.path[:] = saved_path
        for name in set(sys.modules) - set(saved_modules):
            del sys.modules[name]


class RunParallelTest(unittest.TestCase):
    def test_one_failing_class_gives_exit_1_and_names_the_class(self) -> None:
        code, output = run_in({"test_rp_good.py": PASSING, "test_rp_bad.py": FAILING})
        self.assertEqual(code, 1)
        self.assertRegex(output, r"test_rp_bad\.Failing\s+\S+s\s+FAIL")
        self.assertRegex(output, r"test_rp_good\.Passing\s+\S+s\s+ok")
        self.assertIn("MARKER-expected-failure", output)  # the captured output of the failed unit
        self.assertIn("FAILED units: test_rp_bad.Failing", output)
        self.assertIn("Ran 3 tests in 2 units", output)

    def test_quiet_prints_only_the_failed_units_and_the_summary(self) -> None:
        code, output = run_in({"test_rp_good.py": PASSING, "test_rp_bad.py": FAILING}, quiet=True)
        self.assertEqual(code, 1)
        self.assertRegex(output, r"test_rp_bad\.Failing\s+\S+s\s+FAIL")
        self.assertNotRegex(output, r"test_rp_good\.Passing")
        self.assertIn("Ran 3 tests in 2 units", output)

    def test_quiet_with_no_failure_prints_only_the_summary(self) -> None:
        code, output = run_in({"test_rp_a.py": PASSING}, quiet=True)
        self.assertEqual(code, 0)
        self.assertNotIn("test_rp_a", output)
        self.assertIn("OK", output)

    def test_all_passing_units_give_exit_0(self) -> None:
        code, output = run_in({"test_rp_a.py": PASSING, "test_rp_b.py": PASSING, "helper.py": FAILING})
        self.assertEqual(code, 0)
        self.assertIn("Ran 4 tests in 2 units", output)  # helper.py does not match test*.py
        self.assertNotIn("FAIL", output)
        self.assertIn("OK", output)


class ClassSchedulingTest(unittest.TestCase):
    def test_each_test_class_is_one_unit(self) -> None:
        with make_folder({"test_rp_multi.py": TWO_CLASSES}) as folder:
            units = run_parallel.find_units(folder)
        names = [unit.name for unit in units]
        self.assertEqual(names, ["test_rp_multi.Large", "test_rp_multi.Small"])  # no Mixin, no NoTests
        self.assertEqual([unit.tests for unit in units], [3, 1])

    def test_units_are_ordered_by_test_count_not_file_size(self) -> None:
        files = {"test_rp_big_file.py": ONE_TEST_LARGE_FILE, "test_rp_multi.py": TWO_CLASSES,
                 "test_rp_pass.py": PASSING}
        with make_folder(files) as folder:
            self.assertGreater((folder / "test_rp_big_file.py").stat().st_size,
                               (folder / "test_rp_multi.py").stat().st_size)
            units = run_parallel.find_units(folder)
        self.assertEqual([unit.name for unit in units],
                         ["test_rp_multi.Large", "test_rp_pass.Passing",
                          "test_rp_big_file.Lonely", "test_rp_multi.Small"])  # equal counts: by name
        self.assertEqual([unit.tests for unit in units], [3, 2, 1, 1])

    def test_each_class_runs_in_its_own_subprocess_and_prints_one_line(self) -> None:
        code, output = run_in({"test_rp_multi.py": TWO_CLASSES})
        self.assertEqual(code, 0)
        self.assertRegex(output, r"test_rp_multi\.Large\s+\S+s\s+ok")
        self.assertRegex(output, r"test_rp_multi\.Small\s+\S+s\s+ok")
        self.assertNotIn("Mixin", output)
        self.assertNotIn("NoTests", output)
        self.assertIn("Ran 4 tests in 2 units", output)

    def test_find_units_does_not_keep_modules_from_an_earlier_folder(self) -> None:
        with make_folder({"test_rp_same.py": PASSING}) as folder:
            first = run_parallel.find_units(folder)
        with make_folder({"test_rp_same.py": TWO_CLASSES}) as folder:
            second = run_parallel.find_units(folder)
        self.assertEqual([unit.name for unit in first], ["test_rp_same.Passing"])
        self.assertEqual([unit.name for unit in second], ["test_rp_same.Large", "test_rp_same.Small"])
        self.assertNotIn("test_rp_same", sys.modules)

    def test_total_matches_discover_count(self) -> None:
        files = {"test_rp_multi.py": TWO_CLASSES, "test_rp_pass.py": PASSING, "test_rp_bad.py": FAILING,
                 "test_rp_broken.py": IMPORT_ERROR, "test_rp_crash.py": RUNTIME_ERROR_AT_IMPORT}
        with make_folder(files) as folder:
            expected = discover_count(folder)
            planned = sum(unit.tests for unit in run_parallel.find_units(folder))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = run_parallel.main(folder, jobs=2)
        self.assertEqual(expected, 9)  # 4 + 2 + 1 + 1 failed import + 1 failed import
        self.assertEqual(planned, expected)
        self.assertEqual(code, 1)
        self.assertIn(f"Ran {expected} tests in 6 units", out.getvalue())


class ImportErrorTest(unittest.TestCase):
    def test_module_with_import_error_gives_exit_1(self) -> None:
        code, output = run_in({"test_rp_good.py": PASSING, "test_rp_broken.py": IMPORT_ERROR})
        self.assertEqual(code, 1)
        self.assertRegex(output, r"test_rp_broken\s+\S+s\s+FAIL")
        self.assertIn("test_rp_no_such_module_xyz", output)  # the import error is shown
        self.assertIn("FAILED units: test_rp_broken", output)
        self.assertIn("Ran 3 tests in 2 units", output)  # the import error counts as one test

    def test_module_that_raises_at_import_gives_exit_1(self) -> None:
        code, output = run_in({"test_rp_good.py": PASSING, "test_rp_crash.py": RUNTIME_ERROR_AT_IMPORT})
        self.assertEqual(code, 1)
        self.assertRegex(output, r"test_rp_crash\s+\S+s\s+FAIL")
        self.assertIn("MARKER-import-crash", output)
        self.assertIn("FAILED units: test_rp_crash", output)

    def test_import_error_module_is_one_unit_with_one_test(self) -> None:
        with make_folder({"test_rp_broken.py": IMPORT_ERROR}) as folder:
            units = run_parallel.find_units(folder)
        self.assertEqual(units, [run_parallel.Unit("test_rp_broken", 1)])


if __name__ == "__main__":
    unittest.main()
