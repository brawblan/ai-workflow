"""Golden-file test for `stone render` with two profiles that share one trigger label (D43, #55).

The test renders the profile into a temporary repo and compares each written file, byte for byte,
with its fixture. The compare and the update are in `golden_helpers.py`. A fixture is in
`golden/shared-label/` or, if other profiles render the same bytes, in `golden/_shared/` (D64).
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

PROFILES = ["debugging", "single-ticket"]
LABEL = "agent-ready"
FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
GOLDEN = Path(__file__).resolve().parent / "golden" / "shared-label"
CONFIG = f"""framework_version: 0.8.0
harness: claude-code
model_profile: claude-5
profiles: [{", ".join(PROFILES)}]
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

WORKFLOWS = {profile: f".github/workflows/cornerstone-{profile}-label.yml" for profile in PROFILES}


class GoldenSharedLabelTest(unittest.TestCase):
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

    def workflow(self, profile: str) -> str:
        return self.files[WORKFLOWS[profile]].decode("utf-8")

    def test_golden_shared_label_files_match(self) -> None:
        if updating():
            update_golden(GOLDEN, self.files)
        differences = golden_differences(GOLDEN, self.files)
        self.assertEqual(differences, [], "\n".join(differences))

    def test_golden_shared_label_render_exits_0_with_no_skipped_profile(self) -> None:
        self.assertEqual(self.result.exit_code, 0, self.log)
        self.assertEqual(self.result.drift, [])
        self.assertNotIn("skipped profile", self.log)
        self.assertEqual(sorted(self.result.wrote), sorted(self.files))

    def test_golden_shared_label_writes_two_separate_workflows(self) -> None:
        labels = sorted(path for path in self.files
                        if path.startswith(".github/workflows/") and path.endswith("-label.yml"))
        self.assertEqual(labels, sorted(WORKFLOWS.values()))
        self.assertNotEqual(self.files[WORKFLOWS["debugging"]],
                            self.files[WORKFLOWS["single-ticket"]])

    def test_golden_shared_label_each_workflow_selects_its_own_profile(self) -> None:
        for profile, other in (("debugging", "single-ticket"), ("single-ticket", "debugging")):
            with self.subTest(profile=profile):
                text = self.workflow(profile)
                self.assertIn(f"github.event.label.name == '{LABEL}'", text)
                self.assertIn(f"'profile:{profile}'", text)
                self.assertNotIn(f"profile:{other}", text)

    def test_golden_shared_label_manifest_has_one_trigger_component_for_each_profile(self) -> None:
        ids = [c["id"] for c in self.manifest()["components"]
               if c["id"].startswith("trigger.label")]
        self.assertEqual(sorted(ids), sorted(f"trigger.label.{p}" for p in PROFILES))

    def test_golden_shared_label_difference_names_the_file(self) -> None:
        golden = Path(self.folder.name) / "golden"
        write_tree(golden, self.files)
        self.assertEqual(golden_differences(golden, self.files), [])
        changed = WORKFLOWS["debugging"]
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
