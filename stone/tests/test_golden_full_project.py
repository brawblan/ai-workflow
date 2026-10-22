"""Golden-file test: `stone render` for the full-project profile.

The test renders full-project with a fixed config and a fixed date into a temporary repo. It
compares each written file byte for byte with its fixture in `golden/full-project/`. The fixtures
are the rendered files at their target paths, with `.cornerstone/manifest.yaml`.

To write the fixtures again after an intended change, run:

    STONE_UPDATE_GOLDEN=1 python -m unittest discover -s stone/tests -p test_golden_full_project.py

Then read the fixture diff before you commit it. This file is self-contained on purpose: other
profiles have their own golden test file with the same form.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from stone import render

PROFILE = "full-project"
FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
GOLDEN = Path(__file__).resolve().parent / "golden" / PROFILE
TODAY = dt.date(2026, 10, 18)
CONFIG_PATH = ".cornerstone/config.yaml"
CONFIG = f"""framework_version: 0.8.0
harness: claude-code
model_profile: claude-5
profiles: [{PROFILE}]
branches: {{integration: dev, main: main}}
commands:
  install: pip install .
  test_unit: python -m unittest
  all_checks: make check
paths:
  tests: [tests/, "**/*.test.js"]
  checks: [.github/workflows/, .cornerstone/checks/]
  plans: docs/plans/
owners: {{default: octocat}}
"""


def updating() -> bool:
    return os.environ.get("STONE_UPDATE_GOLDEN") == "1"


def tree_files(folder: Path, skip: set[str] = frozenset()) -> list[str]:
    """Return the relative paths of the files under the folder, in sorted order."""
    if not folder.is_dir():
        return []
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*")
                  if path.is_file() and path.relative_to(folder).as_posix() not in skip)


def compare_trees(rendered: Path, golden: Path) -> list[str]:
    """Return one problem for each missing, extra, or changed file. An empty list is a match."""
    got = set(tree_files(rendered, {CONFIG_PATH}))
    want = set(tree_files(golden))
    problems = [f"missing file: {path} has a fixture, but render did not write it"
                for path in sorted(want - got)]
    problems += [f"extra file: render wrote {path}, but it has no fixture"
                 for path in sorted(got - want)]
    problems += [f"changed file: {path} is not the same as its fixture"
                 for path in sorted(got & want)
                 if (rendered / path).read_bytes() != (golden / path).read_bytes()]
    return problems


def update_fixtures(rendered: Path, golden: Path) -> None:
    """Make the fixture folder the same as the rendered files. Remove old fixtures."""
    if golden.exists():
        shutil.rmtree(golden)
    for path in tree_files(rendered, {CONFIG_PATH}):
        target = golden / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((rendered / path).read_bytes())


def render_profile(root: Path) -> render.Result:
    (root / ".cornerstone").mkdir(parents=True)
    (root / CONFIG_PATH).write_text(CONFIG, encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()):
        return render.render(root, FRAMEWORK, today=TODAY)


class GoldenFullProjectTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name) / "repo"

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_golden_full_project_matches_the_fixtures(self) -> None:
        result = render_profile(self.root)
        self.assertEqual(result.exit_code, 0)
        if updating():
            update_fixtures(self.root, GOLDEN)
        self.assertTrue(tree_files(GOLDEN), f"{GOLDEN} has no fixtures. Run the test with "
                        "STONE_UPDATE_GOLDEN=1 to write them.")
        problems = compare_trees(self.root, GOLDEN)
        self.assertEqual(problems, [], "\n".join(problems))
        files = tree_files(GOLDEN)
        self.assertIn(".cornerstone/manifest.yaml", files)
        self.assertIn(".cornerstone/checks/instruction_size.py", files)
        self.assertNotIn(CONFIG_PATH, files)

    def test_golden_compare_names_a_missing_file(self) -> None:
        rendered, golden = self.two_trees()
        (golden / "b.txt").write_text("b\n", encoding="utf-8")
        problems = compare_trees(rendered, golden)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("missing", problems[0])
        self.assertIn("b.txt", problems[0])

    def test_golden_compare_names_an_extra_file(self) -> None:
        rendered, golden = self.two_trees()
        (rendered / "sub").mkdir()
        (rendered / "sub" / "c.txt").write_text("c\n", encoding="utf-8")
        problems = compare_trees(rendered, golden)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("extra", problems[0])
        self.assertIn("sub/c.txt", problems[0])

    def test_golden_compare_is_byte_for_byte(self) -> None:
        rendered, golden = self.two_trees()
        (rendered / "a.txt").write_bytes(b"a\r\n")
        problems = compare_trees(rendered, golden)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("a.txt", problems[0])

    def test_golden_compare_ignores_the_input_config(self) -> None:
        rendered, golden = self.two_trees()
        (rendered / ".cornerstone").mkdir()
        (rendered / CONFIG_PATH).write_text("x: 1\n", encoding="utf-8")
        self.assertEqual(compare_trees(rendered, golden), [])

    def test_golden_update_removes_an_old_fixture(self) -> None:
        rendered, golden = self.two_trees()
        (golden / "old.txt").write_text("old\n", encoding="utf-8")
        update_fixtures(rendered, golden)
        self.assertEqual(tree_files(golden), ["a.txt"])
        self.assertEqual(compare_trees(rendered, golden), [])

    def two_trees(self) -> tuple[Path, Path]:
        rendered = Path(self.folder.name) / "rendered"
        golden = Path(self.folder.name) / "golden"
        for folder in (rendered, golden):
            folder.mkdir()
            (folder / "a.txt").write_text("a\n", encoding="utf-8")
        return rendered, golden


if __name__ == "__main__":
    unittest.main()
