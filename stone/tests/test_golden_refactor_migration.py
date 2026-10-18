"""Golden-file test for `stone render` with the refactor-migration profile (D29, roadmap 6d).

Convention for all profiles:

- Fixtures are in `stone/tests/golden/<profile>/`: the input `config.yaml`, and the expected
  output tree under `expected/`.
- One test file for each profile: `stone/tests/test_golden_<profile>.py`.
- With `STONE_UPDATE_GOLDEN=1`, the test writes the expected files again and does not compare.
  Read the diff of `expected/` before you commit it.
- Render uses a fixed date, so the manifest is stable.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import shutil
import tempfile
import unittest
from collections.abc import Collection
from pathlib import Path

import yaml

from stone import render

TESTS = Path(__file__).resolve().parent
FRAMEWORK = TESTS.parents[1] / "framework"
TODAY = dt.date(2026, 10, 18)
CONFIG = ".cornerstone/config.yaml"
WORKFLOW = ".github/workflows/cornerstone-checks.yml"


def update_golden() -> bool:
    return os.environ.get("STONE_UPDATE_GOLDEN") == "1"


def tree(folder: Path, skip: Collection[str] = ()) -> dict[str, str]:
    """Return {relative path: text} for each file under the folder."""
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(folder.rglob("*"))
            if p.is_file() and p.relative_to(folder).as_posix() not in skip}


class GoldenMixin:
    """Render the fixture config of one profile and compare the output with `expected/`.

    Use it as `class <Profile>GoldenTest(GoldenMixin, unittest.TestCase)` with `profile` set.
    The mixin is not a TestCase, so discovery does not run it alone.
    """

    profile: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = TESTS / "golden" / cls.profile
        cls.expected = cls.fixture / "expected"
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name) / "repo"
        (cls.root / ".cornerstone").mkdir(parents=True)
        shutil.copyfile(cls.fixture / "config.yaml", cls.root / CONFIG)
        cls.log = io.StringIO()
        with contextlib.redirect_stderr(cls.log):
            cls.result = render.render(cls.root, FRAMEWORK, today=TODAY)
        cls.actual = tree(cls.root, skip={CONFIG})
        if update_golden():
            shutil.rmtree(cls.expected, ignore_errors=True)
            for path, text in cls.actual.items():
                target = cls.expected / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.folder.cleanup()

    def test_render_exits_0(self) -> None:
        self.assertEqual(self.result.exit_code, 0, self.log.getvalue())
        self.assertEqual(self.result.drift, [])

    def test_expected_folder_exists(self) -> None:
        self.assertTrue(self.expected.is_dir(),
                        f"No {self.expected}. Run the test with STONE_UPDATE_GOLDEN=1.")

    def test_render_writes_the_same_set_of_files(self) -> None:
        self.assertEqual(sorted(self.actual), sorted(tree(self.expected)))

    def test_render_reports_each_file_that_it_writes(self) -> None:
        self.assertEqual(sorted(self.result.wrote), sorted(tree(self.expected)))

    def test_each_file_is_byte_identical(self) -> None:
        expected = tree(self.expected)
        for path in sorted(expected):
            with self.subTest(path=path):
                self.assertIn(path, self.actual)
                self.assertEqual(self.actual[path], expected[path])

    def test_manifest_is_compared(self) -> None:
        self.assertIn(".cornerstone/manifest.yaml", tree(self.expected))


class RefactorMigrationGoldenTest(GoldenMixin, unittest.TestCase):
    profile = "refactor-migration"

    def steps(self) -> list[dict]:
        return yaml.safe_load(self.actual[WORKFLOW])["jobs"]["checks"]["steps"]

    def test_render_gives_no_check_warning(self) -> None:
        lines = [line for line in self.log.getvalue().splitlines()
                 if line.startswith("warning:") and "commands." in line]
        self.assertEqual(lines, [])

    def test_workflow_has_the_k8_k12_and_k10_steps_in_order(self) -> None:
        names = [step.get("name") for step in self.steps()]
        self.assertEqual(names[names.index("All checks") + 1:],
                         ["K8 architecture fitness", "K12 differential tests",
                          "K10 mutation score"])

    def test_k10_step_gets_the_limit(self) -> None:
        step = next(s for s in self.steps() if s.get("name") == "K10 mutation score")
        self.assertEqual(step["run"], "mutmut run --paths-to-mutate src/")
        self.assertEqual(str(step["env"]["MUTATION_SCORE_MIN"]), "0.6")
        self.assertIn("BASE_REF", step["env"])

    def test_manifest_dates_come_from_the_fixed_date(self) -> None:
        manifest = yaml.safe_load(self.actual[".cornerstone/manifest.yaml"])
        for entry in manifest["components"]:
            with self.subTest(component=entry["id"]):
                self.assertEqual(str(entry["added"]), "2026-10-18")
                self.assertEqual(str(entry["review_by"]), "2027-04-18")

    def test_second_render_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repo"
            shutil.copytree(self.expected, root)
            (root / ".cornerstone").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.fixture / "config.yaml", root / CONFIG)
            with contextlib.redirect_stderr(io.StringIO()):
                result = render.render(root, FRAMEWORK, today=TODAY + dt.timedelta(days=30))
            self.assertEqual(result.wrote, [])
            self.assertEqual(result.drift, [])
            self.assertEqual(tree(root, skip={CONFIG}), tree(self.expected))



if __name__ == "__main__":
    unittest.main()
