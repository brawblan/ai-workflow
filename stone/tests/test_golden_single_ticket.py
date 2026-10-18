"""Golden-file test for `stone render` with the single-ticket profile alone (roadmap item 6).

The test renders the profile into a temporary repo and compares each written file, byte for byte,
with the fixture in `golden/single-ticket/`. To write the fixtures again after an intended change,
run:

    STONE_UPDATE_GOLDEN=1 python -m unittest discover -s stone/tests -p "test_golden_*.py"

Then read the fixture diff before you commit it. This file is self-contained on purpose: each
profile has its own golden test file.
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
from unittest import mock

import yaml

from stone import render

PROFILE = "single-ticket"
FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
GOLDEN = Path(__file__).resolve().parent / "golden" / PROFILE
UPDATE_ENV = "STONE_UPDATE_GOLDEN"
TODAY = dt.date(2026, 10, 18)
REVIEW_BY = "2027-04-18"  # TODAY plus 6 months (P5)
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
  tests: [tests/]
  checks: [.github/workflows/, .cornerstone/checks/]
  plans: docs/plans/
owners: {{default: octocat}}
"""
CONFIG_PATH = ".cornerstone/config.yaml"
MANIFEST = ".cornerstone/manifest.yaml"
WORKFLOW = ".github/workflows/cornerstone-checks.yml"
LABEL_WORKFLOW = f".github/workflows/cornerstone-{PROFILE}-label.yml"
HINT = f"If the change is intended, run with {UPDATE_ENV}=1 to write the fixtures again."

# Pins from framework/profiles/single-ticket.md: roles [shaper, implementer, tester, reviewer],
# trigger label:agent-ready, G3 required, K6 and K7 in checks, no K15 and no K16.
FILES = [".claude/agents/implementer.md", ".claude/agents/reviewer.md",
         ".claude/agents/shaper.md", ".claude/agents/tester.md", ".claude/settings.json",
         ".cornerstone/checks/change_size.py", ".cornerstone/checks/protected_paths.py",
         ".cornerstone/hooks/protect-paths.py", MANIFEST, WORKFLOW, LABEL_WORKFLOW]
NOT_WRITTEN = [".claude/agents/planner.md", ".claude/agents/investigator.md",
               ".cornerstone/checks/instruction_size.py", ".github/workflows/cornerstone-k16.yml"]
COMPONENTS = ["check.k6", "check.k7", "ci-job.checks", "hook.protect-paths", "hook.settings",
              "role.implementer", "role.reviewer", "role.shaper", "role.tester",
              f"trigger.label.{PROFILE}"]


def tree_files(folder: Path, skip: frozenset[str] = frozenset()) -> dict[str, bytes]:
    """Return each file under `folder` (relative POSIX path) and its bytes."""
    if not folder.is_dir():
        return {}
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob("*"))
            if path.is_file() and path.relative_to(folder).as_posix() not in skip}


def golden_differences(golden: Path, files: dict[str, bytes]) -> list[str]:
    """Return one message for each fixture file that is missing, extra, or not equal."""
    fixtures = tree_files(golden)
    messages = [f"missing file {path}: the fixture has it, but render did not write it. " + HINT
                for path in sorted(set(fixtures) - set(files))]
    messages += [f"extra file {path}: render wrote it, but there is no fixture. " + HINT
                 for path in sorted(set(files) - set(fixtures))]
    messages += [f"changed file {path}: the render output is not equal to {golden / path}. "
                 + HINT for path in sorted(set(files) & set(fixtures))
                 if files[path] != fixtures[path]]
    return messages


def update_golden(golden: Path, files: dict[str, bytes]) -> None:
    """Make the fixture folder equal to `files`. Delete the stale fixture files."""
    if golden.exists():
        shutil.rmtree(golden)
    for path, content in files.items():
        (golden / path).parent.mkdir(parents=True, exist_ok=True)
        (golden / path).write_bytes(content)


def render_profile(root: Path, today: dt.date = TODAY) -> tuple[render.Result, str]:
    """Write the repo config, render into `root`, and return the result and the log."""
    (root / ".cornerstone").mkdir(parents=True, exist_ok=True)
    (root / CONFIG_PATH).write_text(CONFIG, encoding="utf-8")
    log = io.StringIO()
    with contextlib.redirect_stderr(log):
        result = render.render(root, FRAMEWORK, today=today)
    return result, log.getvalue()


class GoldenSingleTicketTest(unittest.TestCase):
    golden = GOLDEN

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / "repo"
        self.result, self.log = render_profile(self.root)
        self.files = tree_files(self.root, frozenset({CONFIG_PATH}))

    def manifest(self) -> dict:
        return yaml.safe_load(self.files[MANIFEST].decode("utf-8"))

    # AC1: the render output is equal to the fixtures.

    def test_golden_single_ticket_files_match(self) -> None:
        if os.environ.get(UPDATE_ENV) == "1":
            update_golden(self.golden, self.files)
        differences = golden_differences(self.golden, self.files)
        self.assertEqual(differences, [], "\n".join(differences))

    def test_golden_single_ticket_render_exits_0_with_no_warning(self) -> None:
        self.assertEqual(self.result.exit_code, 0, self.log)
        self.assertEqual(self.result.drift, [])
        self.assertEqual(self.result.skipped, [])
        self.assertNotIn("skipped profile", self.log)
        # The only allowed warning is the status of the model profile in the fixed config.
        warnings = [line for line in self.log.splitlines() if line.startswith("warning:")
                    and "model profile" not in line]
        self.assertEqual(warnings, [])
        self.assertEqual(sorted(self.result.wrote), sorted(self.files))

    def test_golden_single_ticket_writes_the_pinned_files(self) -> None:
        self.assertEqual(sorted(self.files), sorted(FILES))
        for path in NOT_WRITTEN:
            with self.subTest(path=path):
                self.assertNotIn(path, self.files)

    def test_golden_single_ticket_manifest_has_the_pinned_components(self) -> None:
        components = self.manifest()["components"]
        self.assertEqual([c["id"] for c in components], COMPONENTS)
        for component in components:
            with self.subTest(component=component["id"]):
                self.assertEqual(str(component["added"]), TODAY.isoformat())
                self.assertEqual(str(component["review_by"]), REVIEW_BY)
                self.assertIn("eval", component)

    def test_golden_single_ticket_g3_workflow_runs_k6_and_k7(self) -> None:
        steps = yaml.safe_load(self.files[WORKFLOW].decode("utf-8"))["jobs"]["checks"]["steps"]
        runs = {step["name"]: step.get("run", "") for step in steps if "name" in step}
        self.assertTrue(any(name.startswith("K6") and ".cornerstone/checks/protected_paths.py"
                            in run for name, run in runs.items()), list(runs))
        self.assertTrue(any(name.startswith("K7") and ".cornerstone/checks/change_size.py"
                            in run for name, run in runs.items()), list(runs))

    def test_golden_single_ticket_fixtures_hold_the_manifest(self) -> None:
        if os.environ.get(UPDATE_ENV) == "1":
            self.skipTest("the fixtures are being rewritten")
        self.assertIn(MANIFEST, tree_files(GOLDEN))
        self.assertNotIn(CONFIG_PATH, tree_files(GOLDEN))

    # AC2: the golden test fails if one rendered file changes.

    def run_golden_test(self, golden: Path) -> unittest.TestResult:
        case = type("TempGoldenTest", (GoldenSingleTicketTest,), {"golden": golden})
        suite = unittest.TestSuite([case("test_golden_single_ticket_files_match")])
        with mock.patch.dict(os.environ):
            os.environ.pop(UPDATE_ENV, None)
            return unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)

    def test_golden_single_ticket_fails_if_one_rendered_file_changes(self) -> None:
        for path in sorted(self.files):
            with self.subTest(path=path):
                golden = Path(self.folder.name) / "golden" / path.replace("/", "_")
                update_golden(golden, self.files)
                (golden / path).write_bytes(self.files[path] + b" ")
                messages = golden_differences(golden, self.files)
                self.assertEqual(len(messages), 1, messages)
                self.assertIn(f"changed file {path}", messages[0])
                result = self.run_golden_test(golden)
                self.assertEqual(len(result.failures), 1, result.errors)
                self.assertIn(path, result.failures[0][1])

    def test_golden_single_ticket_difference_names_the_file(self) -> None:
        golden = Path(self.folder.name) / "golden"
        update_golden(golden, self.files)
        self.assertEqual(golden_differences(golden, self.files), [])
        (golden / "only-in-fixture.txt").write_bytes(b"x\n")
        (golden / MANIFEST).unlink()
        (golden / WORKFLOW).write_bytes(self.files[WORKFLOW].replace(b"\n", b"\r\n"))
        messages = golden_differences(golden, self.files)
        self.assertEqual(len(messages), 3, messages)
        self.assertTrue(any("missing" in m and "only-in-fixture.txt" in m for m in messages))
        self.assertTrue(any("extra" in m and MANIFEST in m for m in messages))
        self.assertTrue(any("changed" in m and WORKFLOW in m for m in messages))

    # AC3: a second render writes nothing.

    def test_golden_single_ticket_second_render_writes_nothing(self) -> None:
        for today in (TODAY, TODAY + dt.timedelta(days=30)):
            with self.subTest(today=today.isoformat()):
                result, log = render_profile(self.root, today)
                self.assertEqual(result.wrote, [], log)
                self.assertEqual(result.drift, [], log)
                self.assertEqual(sorted(result.skipped), sorted(self.files))
                self.assertEqual(tree_files(self.root, frozenset({CONFIG_PATH})), self.files)


if __name__ == "__main__":
    unittest.main()
