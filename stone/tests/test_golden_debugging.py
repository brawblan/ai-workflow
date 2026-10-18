"""Golden-file test for `stone render` with the debugging profile (roadmap item 6f).

The test renders the profile into a temporary repo and compares each written file, byte for byte,
with the fixture in `golden/debugging/`. To write the fixtures again after an intended change, run:

    STONE_UPDATE_GOLDEN=1 python -m unittest discover -s stone/tests

This file is self-contained on purpose: each profile has its own golden test file.
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
from stone.markdown import split_frontmatter

PROFILE = "debugging"
FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
GOLDEN = Path(__file__).resolve().parent / "golden" / PROFILE
UPDATE_ENV = "STONE_UPDATE_GOLDEN"
TODAY = dt.date(2026, 10, 18)
REVIEW_BY = "2027-04-18"  # TODAY plus 6 months (P5)
CONFIG = """framework_version: 0.8.0
harness: claude-code
model_profile: claude-5
profiles: [single-ticket]
branches: {integration: dev, main: main}
commands:
  install: pip install .
  test_unit: python -m unittest
  all_checks: make check
paths:
  tests: [tests/]
  checks: [.github/workflows/, .cornerstone/checks/]
  plans: docs/plans/
owners: {default: octocat}
""".replace("[single-ticket]", f"[{PROFILE}]")
CONFIG_PATH = ".cornerstone/config.yaml"
MANIFEST = ".cornerstone/manifest.yaml"
WORKFLOW = ".github/workflows/cornerstone-checks.yml"
K6 = ".cornerstone/checks/protected_paths.py"
HOOK = ".cornerstone/hooks/protect-paths.py"
SETTINGS = ".claude/settings.json"
ROLES = ["implementer", "investigator", "reviewer", "tester"]  # the profile `roles`, sorted
HINT = f"If the change is intended, run with {UPDATE_ENV}=1 to write the fixtures again."


def profile_frontmatter() -> dict:
    text = (FRAMEWORK / "profiles" / f"{PROFILE}.md").read_text(encoding="utf-8")
    return split_frontmatter(text)[0]


def render_profile(root: Path) -> tuple[render.Result, str]:
    """Write the repo config, render into `root`, and return the result and the log."""
    (root / ".cornerstone").mkdir(parents=True, exist_ok=True)
    (root / CONFIG_PATH).write_text(CONFIG, encoding="utf-8")
    log = io.StringIO()
    with contextlib.redirect_stderr(log):
        result = render.render(root, FRAMEWORK, today=TODAY)
    return result, log.getvalue()


def tree_files(folder: Path, skip: frozenset[str] = frozenset()) -> dict[str, bytes]:
    """Return each file under `folder` (relative POSIX path) and its bytes."""
    if not folder.is_dir():
        return {}
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob("*"))
            if path.is_file() and path.relative_to(folder).as_posix() not in skip}


def written_files(root: Path) -> dict[str, bytes]:
    return tree_files(root, frozenset({CONFIG_PATH}))


def golden_differences(golden: Path, files: dict[str, bytes]) -> list[str]:
    """Return one message for each fixture file that is missing, extra, or not equal."""
    fixtures = tree_files(golden)
    messages = []
    for path in sorted(set(fixtures) - set(files)):
        messages.append(f"missing file {path}: the fixture has it, but render did not write it. "
                        + HINT)
    for path in sorted(set(files) - set(fixtures)):
        messages.append(f"extra file {path}: render wrote it, but there is no fixture. " + HINT)
    for path in sorted(set(files) & set(fixtures)):
        if files[path] != fixtures[path]:
            messages.append(f"changed file {path}: the render output is not equal to "
                            f"{golden / path}. " + HINT)
    return messages


def update_golden(golden: Path, files: dict[str, bytes]) -> None:
    """Make the fixture folder equal to `files`. Delete the stale fixture files."""
    if golden.exists():
        shutil.rmtree(golden)
    for path, content in files.items():
        target = golden / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


class RenderedRepo(unittest.TestCase):
    """Render the profile once into a temporary repo for each test."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / "repo"
        self.result, self.log = render_profile(self.root)
        self.files = written_files(self.root)

    def text(self, path: str) -> str:
        return self.files[path].decode("utf-8")


class GoldenTest(RenderedRepo):
    """AC1 to AC4: the render output is equal to the fixtures."""

    golden = GOLDEN

    def test_golden_files_match(self) -> None:
        if os.environ.get(UPDATE_ENV) == "1":
            update_golden(self.golden, self.files)
        differences = golden_differences(self.golden, self.files)
        self.assertEqual(differences, [], "\n".join(differences))


# AC1: render exits with code 0, with no drift and no skipped file.

class RenderResultTest(RenderedRepo):
    def test_ac1_exit_code_is_0(self) -> None:
        self.assertEqual(self.result.exit_code, 0, self.log)

    def test_ac1_no_drift(self) -> None:
        self.assertEqual(self.result.drift, [], self.log)

    def test_ac1_no_skipped_file_and_no_skipped_profile(self) -> None:
        self.assertEqual(self.result.skipped, [], self.log)
        self.assertNotIn("skipped profile", self.log)

    def test_ac1_wrote_list_is_the_files_on_disk(self) -> None:
        self.assertEqual(sorted(self.result.wrote), sorted(self.files))


# AC2 to AC4: the comparison names each file and the update variable.

class GoldenComparisonTest(RenderedRepo):
    def setUp(self) -> None:
        super().setUp()
        self.golden = Path(self.folder.name) / "golden"
        update_golden(self.golden, self.files)

    def test_ac2_written_set_leaves_out_only_the_config(self) -> None:
        self.assertNotIn(CONFIG_PATH, self.files)
        self.assertNotIn(CONFIG_PATH, tree_files(GOLDEN))
        self.assertIn(MANIFEST, self.files)

    def test_ac2_equal_folders_have_no_difference(self) -> None:
        self.assertEqual(golden_differences(self.golden, self.files), [])

    def test_ac2_missing_file_fails_and_names_the_file(self) -> None:
        (self.golden / "docs" / "only-in-fixture.md").parent.mkdir(parents=True)
        (self.golden / "docs" / "only-in-fixture.md").write_bytes(b"x\n")
        messages = golden_differences(self.golden, self.files)
        self.assertEqual(len(messages), 1, messages)
        self.assertIn("docs/only-in-fixture.md", messages[0])
        self.assertIn("missing", messages[0])

    def test_ac2_extra_file_fails_and_names_the_file(self) -> None:
        (self.golden / SETTINGS).unlink()
        messages = golden_differences(self.golden, self.files)
        self.assertEqual(len(messages), 1, messages)
        self.assertIn(SETTINGS, messages[0])
        self.assertIn("extra", messages[0])

    def test_ac3_one_changed_byte_fails_and_names_the_file(self) -> None:
        path = self.golden / HOOK
        path.write_bytes(path.read_bytes() + b" ")
        messages = golden_differences(self.golden, self.files)
        self.assertEqual(len(messages), 1, messages)
        self.assertIn(HOOK, messages[0])
        self.assertIn(f"{UPDATE_ENV}=1", messages[0])

    def test_ac3_line_ending_change_fails(self) -> None:
        path = self.golden / MANIFEST
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        messages = golden_differences(self.golden, self.files)
        self.assertEqual(len(messages), 1, messages)
        self.assertIn(MANIFEST, messages[0])

    def test_ac3_each_difference_tells_the_reader_to_update(self) -> None:
        (self.golden / K6).unlink()
        (self.golden / "stale.txt").write_bytes(b"old\n")
        (self.golden / WORKFLOW).write_bytes(b"changed\n")
        messages = golden_differences(self.golden, self.files)
        self.assertEqual(len(messages), 3, messages)
        for message in messages:
            self.assertIn(f"{UPDATE_ENV}=1", message)

    def run_golden_test(self, golden: Path, env: dict[str, str]) -> unittest.TestResult:
        case = type("TempGoldenTest", (GoldenTest,), {"golden": golden})
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(case)
        with mock.patch.dict(os.environ, env):
            if UPDATE_ENV not in env:
                os.environ.pop(UPDATE_ENV, None)
            return unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)

    def test_ac3_golden_test_fails_with_the_file_and_the_hint(self) -> None:
        (self.golden / HOOK).write_bytes(b"changed\n")
        result = self.run_golden_test(self.golden, {})
        self.assertEqual(len(result.failures), 1)
        message = result.failures[0][1]
        self.assertIn(HOOK, message)
        self.assertIn(f"{UPDATE_ENV}=1", message)

    def test_ac4_update_regenerates_and_a_second_normal_run_passes(self) -> None:
        golden = Path(self.folder.name) / "regenerated"
        (golden / "stale" / "old.md").parent.mkdir(parents=True)
        (golden / "stale" / "old.md").write_bytes(b"stale\n")
        (golden / MANIFEST).parent.mkdir(parents=True)
        (golden / MANIFEST).write_bytes(b"old manifest\n")
        first = self.run_golden_test(golden, {UPDATE_ENV: "1"})
        self.assertTrue(first.wasSuccessful(), first.failures + first.errors)
        self.assertFalse((golden / "stale").exists())
        self.assertEqual(tree_files(golden), self.files)
        second = self.run_golden_test(golden, {})
        self.assertTrue(second.wasSuccessful(), second.failures + second.errors)

    def test_ac4_without_the_variable_the_test_only_compares(self) -> None:
        golden = Path(self.folder.name) / "empty"
        golden.mkdir()
        result = self.run_golden_test(golden, {})
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(tree_files(golden), {})

    def test_ac4_other_values_of_the_variable_do_not_update(self) -> None:
        golden = Path(self.folder.name) / "empty"
        golden.mkdir()
        result = self.run_golden_test(golden, {UPDATE_ENV: "0"})
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(tree_files(golden), {})


# AC5: behavior pins from framework/profiles/debugging.md.

class ProfilePinTest(RenderedRepo):
    def agent_files(self) -> list[str]:
        return sorted(path for path in self.files if path.startswith(".claude/agents/"))

    def test_ac5_profile_roles_are_the_pinned_roles(self) -> None:
        self.assertEqual(sorted(profile_frontmatter()["roles"]), ROLES)

    def test_ac5_agent_files_are_exactly_the_profile_roles(self) -> None:
        roles = sorted(profile_frontmatter()["roles"])
        self.assertEqual(self.agent_files(), [f".claude/agents/{role}.md" for role in roles])

    def test_ac5_no_shaper_and_no_planner_file(self) -> None:
        for role in ("shaper", "planner"):
            with self.subTest(role=role):
                self.assertNotIn(f".claude/agents/{role}.md", self.files)
                self.assertNotIn(f"role.{role}", self.manifest_ids())

    def test_ac5_each_agent_file_names_its_role(self) -> None:
        for role in ROLES:
            with self.subTest(role=role):
                meta = split_frontmatter(self.text(f".claude/agents/{role}.md"))[0]
                self.assertEqual(meta["name"], role)

    def test_ac5_g3_is_required(self) -> None:
        self.assertEqual(profile_frontmatter()["gates"]["G3"], "required")

    def test_ac5_g3_workflow_exists_and_runs_k6_and_k14(self) -> None:
        self.assertIn(WORKFLOW, self.files)
        steps = yaml.safe_load(self.text(WORKFLOW))["jobs"]["checks"]["steps"]
        runs = {step["name"]: step["run"] for step in steps if "name" in step}
        k6 = [run for name, run in runs.items() if name.startswith("K6")]
        k14 = [run for name, run in runs.items() if name.startswith("K14")]
        self.assertEqual(len(k6), 1, list(runs))
        self.assertIn(K6, k6[0])
        self.assertEqual(len(k14), 1, list(runs))
        self.assertIn("check-evidence", k14[0])

    def test_ac5_k6_is_in_checks_and_the_k6_check_exists(self) -> None:
        self.assertIn("K6", profile_frontmatter()["checks"])
        self.assertIn(K6, self.files)

    def manifest(self) -> dict:
        return yaml.safe_load(self.text(MANIFEST))

    def manifest_ids(self) -> list[str]:
        return [component["id"] for component in self.manifest()["components"]]

    def test_ac5_manifest_has_one_component_for_each_file_group(self) -> None:
        want = sorted([f"role.{role}" for role in ROLES]
                      + ["check.k6", "ci-job.checks", "hook.protect-paths", "hook.settings"])
        self.assertEqual(sorted(self.manifest_ids()), want)

    def test_ac5_each_written_file_is_in_exactly_one_component(self) -> None:
        listed = [path for component in self.manifest()["components"]
                  for path in component["files"]]
        self.assertEqual(len(listed), len(set(listed)), listed)
        self.assertEqual(sorted(listed), sorted(path for path in self.files if path != MANIFEST))

    def test_ac5_each_component_has_review_by_6_months_after_today(self) -> None:
        for component in self.manifest()["components"]:
            with self.subTest(component=component["id"]):
                self.assertEqual(str(component["review_by"]), REVIEW_BY)
                self.assertEqual(str(component["added"]), TODAY.isoformat())

    def test_ac5_each_component_has_an_eval_field(self) -> None:
        for component in self.manifest()["components"]:
            with self.subTest(component=component["id"]):
                self.assertIn("eval", component)
                self.assertIsInstance(component["eval"], str)


if __name__ == "__main__":
    unittest.main()
