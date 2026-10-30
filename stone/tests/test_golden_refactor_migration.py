"""Golden-file test for `stone render` with the refactor-migration profile (D29, roadmap 6d).

Convention for all profiles:

- The input `config.yaml` is in `stone/tests/golden/<profile>/`. The expected output tree is under
  `expected/`. A file that other profiles render with the same bytes is in `golden/_shared/` (D64).
- One test file for each profile: `stone/tests/test_golden_<profile>.py`.
- The compare and the update are in `golden_helpers.py`. With `STONE_UPDATE_GOLDEN=1`, the test
  writes the expected files again before it compares. Read the diff before you commit it.
  Command: `STONE_UPDATE_GOLDEN=1 python -m unittest discover -s stone/tests -p 'test_golden_*.py'`
- Render uses a fixed date, so the manifest is stable.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path

import yaml

from golden_helpers import (TODAY, golden_differences, tree_files, update_golden, updating,
                            write_tree)
from stone import render

TESTS = Path(__file__).resolve().parent
FRAMEWORK = TESTS.parents[1] / "framework"
GOLDEN = TESTS / "golden" / "refactor-migration" / "expected"
CONFIG = (GOLDEN.parent / "config.yaml").read_text(encoding="utf-8")
CONFIG_PATH = ".cornerstone/config.yaml"
WORKFLOW = ".github/workflows/cornerstone-checks.yml"


class GoldenMixin:
    """Render the fixture config of one profile and compare the output with `expected/`.

    Use it as `class <Profile>GoldenTest(GoldenMixin, unittest.TestCase)`. The mixin is not a
    TestCase, so discovery does not run it alone.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name) / "repo"
        (cls.root / ".cornerstone").mkdir(parents=True)
        (cls.root / CONFIG_PATH).write_text(CONFIG, encoding="utf-8")
        cls.log = io.StringIO()
        with contextlib.redirect_stderr(cls.log):
            cls.result = render.render(cls.root, FRAMEWORK, today=TODAY)
        cls.actual = tree_files(cls.root, frozenset({CONFIG_PATH}))
        if updating():
            update_golden(GOLDEN, cls.actual)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.folder.cleanup()

    def test_render_exits_0(self) -> None:
        self.assertEqual(self.result.exit_code, 0, self.log.getvalue())
        self.assertEqual(self.result.drift, [])

    def test_expected_folder_exists(self) -> None:
        self.assertTrue(GOLDEN.is_dir(),
                        f"No {GOLDEN}. Run the test with STONE_UPDATE_GOLDEN=1.")

    def test_render_writes_the_same_set_of_files(self) -> None:
        differences = golden_differences(GOLDEN, self.actual)
        self.assertEqual([m for m in differences if not m.startswith("changed")], [],
                         "\n".join(differences))

    def test_render_reports_each_file_that_it_writes(self) -> None:
        self.assertEqual(sorted(self.result.wrote), sorted(self.actual))

    def test_each_file_is_byte_identical(self) -> None:
        differences = golden_differences(GOLDEN, self.actual)
        self.assertEqual([m for m in differences if m.startswith("changed")], [],
                         "\n".join(differences))

    def test_manifest_is_compared(self) -> None:
        self.assertIn(".cornerstone/manifest.yaml", tree_files(GOLDEN))


class RefactorMigrationGoldenTest(GoldenMixin, unittest.TestCase):
    def steps(self) -> list[dict]:
        return yaml.safe_load(self.actual[WORKFLOW])["jobs"]["checks"]["steps"]

    def test_render_gives_no_check_warning(self) -> None:
        lines = [line for line in self.log.getvalue().splitlines()
                 if line.startswith("warning:") and "commands." in line]
        self.assertEqual(lines, [])

    def test_workflow_has_the_k8_k12_and_k10_steps_in_order(self) -> None:
        names = [step.get("name") for step in self.steps()]
        self.assertEqual(names[names.index("All checks") + 1:],
                         ["K23 new dependencies", "K8 architecture fitness",
                          "K12 differential tests", "K10 mutation score"])

    def test_k10_step_gets_the_limit(self) -> None:
        step = next(s for s in self.steps() if s.get("name") == "K10 mutation score")
        self.assertEqual(step["run"], "scripts/mutation-score.sh")
        self.assertEqual(str(step["env"]["MUTATION_SCORE_MIN"]), "0.6")
        self.assertIn("BASE_REF", step["env"])

    def test_manifest_dates_come_from_the_fixed_date(self) -> None:
        manifest = yaml.safe_load(self.actual[".cornerstone/manifest.yaml"])
        for entry in manifest["components"]:
            with self.subTest(component=entry["id"]):
                self.assertEqual(str(entry["added"]), "2026-10-18")
                self.assertEqual(str(entry["review_by"]), "2027-04-18")

    def test_second_render_writes_nothing(self) -> None:
        # self.actual is equal to the fixtures (test_each_file_is_byte_identical).
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repo"
            write_tree(root, self.actual)
            (root / CONFIG_PATH).write_text(CONFIG, encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                result = render.render(root, FRAMEWORK, today=TODAY + dt.timedelta(days=30))
            self.assertEqual(result.wrote, [])
            self.assertEqual(result.drift, [])
            self.assertEqual(tree_files(root, frozenset({CONFIG_PATH})), self.actual)


if __name__ == "__main__":
    unittest.main()
