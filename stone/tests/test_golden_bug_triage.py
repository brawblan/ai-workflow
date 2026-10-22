"""Golden-file test for `stone render` with the bug-triage profile alone (roadmap item 6e).

The test renders the profile into a temporary repo and compares each written file, byte for byte,
with its fixture. The compare and the update are in `golden_helpers.py`. A fixture is in
`golden/bug-triage/` or, if other profiles render the same bytes, in `golden/_shared/` (D64).
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import yaml

from golden_helpers import (TODAY, golden_differences, tree_files, update_golden, updating,
                            write_tree)
from stone import render

PROFILE = "bug-triage"
FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
GOLDEN = Path(__file__).resolve().parent / "golden" / PROFILE
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

# Pins from framework/profiles/bug-triage.md: roles [investigator], G3 skip, checks [K17],
# triggers [ci:issue-opened, schedule:daily, command]. D31: render writes one workflow for each
# trigger that is not `command`, so render writes the issue-opened and the schedule workflows.
FILES = [".claude/agents/investigator.md", ".claude/settings.json",
         ".cornerstone/hooks/protect-paths.py", ".cornerstone/lib/path_match.py", MANIFEST,
         f".github/workflows/cornerstone-{PROFILE}-issue-opened.yml",
         f".github/workflows/cornerstone-{PROFILE}-schedule.yml"]
NOT_WRITTEN = [".github/workflows/cornerstone-checks.yml",
               ".github/workflows/cornerstone-k16.yml",
               ".cornerstone/checks/protected_paths.py"]
COMPONENTS = ["hook.path-match", "hook.protect-paths", "hook.settings", "role.investigator",
              f"trigger.issue-opened.{PROFILE}", f"trigger.schedule.{PROFILE}"]


class GoldenBugTriageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / "repo"
        (self.root / ".cornerstone").mkdir(parents=True)
        (self.root / CONFIG_PATH).write_text(CONFIG, encoding="utf-8")
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            self.result = render.render(self.root, FRAMEWORK, today=TODAY)
        self.log = log.getvalue()
        self.files = tree_files(self.root, frozenset({CONFIG_PATH}))

    def manifest(self) -> dict:
        return yaml.safe_load(self.files[MANIFEST].decode("utf-8"))

    def test_golden_bug_triage_files_match(self) -> None:
        if updating():
            update_golden(GOLDEN, self.files)
        differences = golden_differences(GOLDEN, self.files)
        self.assertEqual(differences, [], "\n".join(differences))

    def test_golden_bug_triage_render_exits_0_with_no_skipped_profile(self) -> None:
        self.assertEqual(self.result.exit_code, 0, self.log)
        self.assertEqual(self.result.drift, [])
        self.assertNotIn("skipped profile", self.log)
        self.assertEqual(sorted(self.result.wrote), sorted(self.files))

    def test_golden_bug_triage_writes_the_pinned_files(self) -> None:
        self.assertEqual(sorted(self.files), sorted(FILES))
        for path in NOT_WRITTEN:
            with self.subTest(path=path):
                self.assertNotIn(path, self.files)

    def test_golden_bug_triage_manifest_has_the_pinned_components(self) -> None:
        components = self.manifest()["components"]
        self.assertEqual([c["id"] for c in components], COMPONENTS)
        for component in components:
            with self.subTest(component=component["id"]):
                self.assertEqual(str(component["added"]), TODAY.isoformat())
                self.assertEqual(str(component["review_by"]), REVIEW_BY)
                self.assertTrue(component["eval"])

    def test_golden_bug_triage_fixtures_hold_the_manifest(self) -> None:
        if updating():
            self.skipTest("the fixtures are being rewritten")
        self.assertIn(MANIFEST, tree_files(GOLDEN))
        self.assertNotIn(CONFIG_PATH, tree_files(GOLDEN))

    def test_golden_bug_triage_difference_names_the_file(self) -> None:
        golden = Path(self.folder.name) / "golden"
        write_tree(golden, self.files)
        self.assertEqual(golden_differences(golden, self.files), [])
        changed = sorted(self.files)[0]
        (golden / changed).write_bytes(b"changed\n")
        (golden / "only-in-fixture.txt").write_bytes(b"x\n")
        (golden / MANIFEST).unlink()
        messages = golden_differences(golden, self.files)
        self.assertEqual(len(messages), 3, messages)
        self.assertTrue(any("missing" in m and "only-in-fixture.txt" in m for m in messages))
        self.assertTrue(any("extra" in m and MANIFEST in m for m in messages))
        self.assertTrue(any("changed" in m and changed in m for m in messages))


if __name__ == "__main__":
    unittest.main()
