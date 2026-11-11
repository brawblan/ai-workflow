"""Golden-file test for `stone render` with the OpenCode adapter and all six roles (issue #326).

The test renders four profiles into a temporary repo and compares each written file, byte for
byte, with its fixture. The compare and the update are in `golden_helpers.py`. The fixtures are in
`golden/opencode/`. The OpenCode files are not shared with other golden tests (D64).
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import yaml

from golden_helpers import (TODAY, golden_differences, tree_files, update_golden, updating)
from stone import render

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
GOLDEN = Path(__file__).resolve().parent / "golden" / "opencode"
REVIEW_BY = "2027-04-18"  # TODAY plus 6 months (P5)
ROLES = ["shaper", "planner", "implementer", "tester", "reviewer", "investigator"]
CONFIG = """framework_version: 0.8.0
harness: opencode
model_profile: opencode-default
profiles: [single-ticket, spike, full-project, bug-triage]
protect_instruction_files: true
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
"""
CONFIG_PATH = ".cornerstone/config.yaml"
MANIFEST = ".cornerstone/manifest.yaml"
CI_ROLES = ["shaper", "investigator"]  # the first role of a profile with a trigger (#327)
WORKFLOWS = [".github/workflows/cornerstone-single-ticket-label.yml",
             ".github/workflows/cornerstone-bug-triage-issue-opened.yml",
             ".github/workflows/cornerstone-bug-triage-schedule.yml"]
FILES = sorted([f".opencode/agents/{role}.md" for role in ROLES]
               + [f".opencode/agents/{role}-ci.md" for role in CI_ROLES]
               + WORKFLOWS + ["opencode.json", MANIFEST])
COMPONENTS = sorted(["config.permissions"] + [f"role.{role}" for role in ROLES]
                    + [f"role-ci.{role}" for role in CI_ROLES]
                    + ["trigger.label.single-ticket", "trigger.issue-opened.bug-triage",
                       "trigger.schedule.bug-triage"])


class GoldenOpenCodeTest(unittest.TestCase):
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

    def test_golden_opencode_files_match(self) -> None:
        if updating():
            update_golden(GOLDEN, self.files)
        differences = golden_differences(GOLDEN, self.files)
        self.assertEqual(differences, [], "\n".join(differences))

    def test_golden_opencode_render_exits_0_and_writes_the_pinned_files(self) -> None:
        self.assertEqual(self.result.exit_code, 0, self.log)
        self.assertEqual(self.result.drift, [])
        self.assertEqual(sorted(self.files), FILES)
        self.assertEqual(sorted(self.result.wrote), FILES)

    def test_golden_opencode_manifest_has_the_pinned_components(self) -> None:
        components = self.manifest()["components"]
        self.assertEqual(sorted(c["id"] for c in components), COMPONENTS)
        for component in components:
            with self.subTest(component=component["id"]):
                self.assertEqual(str(component["added"]), TODAY.isoformat())
                self.assertEqual(str(component["review_by"]), REVIEW_BY)
                if not component["id"].startswith("role-ci."):  # a derived copy has no eval
                    self.assertTrue(component["eval"])

    def test_golden_opencode_each_role_file_denies_all_first(self) -> None:
        for role in ROLES:
            with self.subTest(role=role):
                text = self.files[f".opencode/agents/{role}.md"].decode("utf-8")
                front = yaml.safe_load(text.split("---\n", 2)[1])
                self.assertEqual(front["permissions"][0],
                                 {"action": "*", "resource": "*", "effect": "deny"})
                self.assertEqual(front["steps"], 60)


if __name__ == "__main__":
    unittest.main()
