"""Tests for `stone render`. They render with the real framework in this repo."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import render

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
TODAY = dt.date(2026, 10, 17)
CONFIG = """framework_version: 0.1.0
harness: claude-code
model_profile: claude-5
profiles: [single-ticket]
branches: {integration: dev, main: main}
commands:
  test_unit: python -m unittest
  all_checks: make check
paths:
  tests: [tests/]
  checks: [.github/workflows/, .cornerstone/checks/]
  plans: docs/plans/
owners: {default: octocat}
"""
ROLE_FILES = [".claude/agents/implementer.md", ".claude/agents/reviewer.md",
              ".claude/agents/shaper.md", ".claude/agents/tester.md"]


class RenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()
        self.write_config(CONFIG)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def write_config(self, text: str) -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")

    def render(self, today: dt.date = TODAY, dry_run: bool = False) -> render.Result:
        with contextlib.redirect_stderr(io.StringIO()):
            return render.render(self.root, FRAMEWORK, dry_run=dry_run, today=today)

    def manifest(self) -> dict:
        return yaml.safe_load((self.root / render.MANIFEST).read_text(encoding="utf-8"))

    def test_writes_role_files_and_manifest(self) -> None:
        result = self.render()
        self.assertEqual(sorted(result.wrote), [*ROLE_FILES, ".cornerstone/manifest.yaml"])
        tester = (self.root / ".claude/agents/tester.md").read_text(encoding="utf-8")
        self.assertIn("model: claude-opus-5-5", tester)
        self.assertIn("Write tests only here: `tests/`", tester)
        self.assertIn("Run `python -m unittest`", tester)
        entry = self.manifest()["components"][2]
        self.assertEqual(entry["id"], "role.shaper")
        self.assertEqual((entry["owner"], entry["added"], entry["review_by"]),
                         ("octocat", "2026-10-17", "2027-04-17"))

    def test_second_render_writes_nothing(self) -> None:
        self.render()
        before = self.manifest()
        result = self.render(today=TODAY + dt.timedelta(days=30))
        self.assertEqual(result.wrote, [])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.manifest(), before)

    def test_drift_is_reported_and_not_overwritten(self) -> None:
        self.render()
        tester = self.root / ".claude/agents/tester.md"
        tester.write_text("my edit\n", encoding="utf-8")
        result = self.render()
        self.assertEqual(result.drift, [".claude/agents/tester.md"])
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(tester.read_text(encoding="utf-8"), "my edit\n")

    def test_a_file_that_a_human_wrote_is_drift(self) -> None:
        reviewer = self.root / ".claude/agents/reviewer.md"
        reviewer.parent.mkdir(parents=True)
        reviewer.write_text("mine\n", encoding="utf-8")
        result = self.render()
        self.assertEqual(result.drift, [".claude/agents/reviewer.md"])
        self.assertNotIn("role.reviewer", [c["id"] for c in self.manifest()["components"]])

    def test_new_input_updates_an_unchanged_file(self) -> None:
        self.render()
        self.write_config(CONFIG.replace("python -m unittest", "pytest"))
        result = self.render()
        self.assertEqual(result.drift, [])
        self.assertIn(".claude/agents/tester.md", result.wrote)
        tester = (self.root / ".claude/agents/tester.md").read_text(encoding="utf-8")
        self.assertIn("Run `pytest`", tester)

    def test_dry_run_writes_nothing(self) -> None:
        result = self.render(dry_run=True)
        self.assertEqual(len(result.wrote), 5)
        self.assertFalse((self.root / ".claude").exists())
        self.assertFalse((self.root / render.MANIFEST).exists())

    def test_todo_value_stops_before_any_write(self) -> None:
        self.write_config(CONFIG.replace("make check", "TODO(octocat)"))
        with self.assertRaisesRegex(render.RenderError, r"commands\.all_checks"):
            self.render()
        self.assertFalse((self.root / ".claude").exists())

    def test_missing_required_field(self) -> None:
        self.write_config(CONFIG.replace("owners: {default: octocat}\n", ""))
        with self.assertRaisesRegex(render.RenderError, "'owners.default' has no value"):
            self.render()

    def test_config_waiver_cannot_remove_g3(self) -> None:
        self.write_config(CONFIG + "waivers:\n  - gate: G3\n")
        with self.assertRaisesRegex(render.RenderError, "No waiver can remove G3"):
            self.render()

    def test_unsupported_profile_is_skipped(self) -> None:
        self.write_config(CONFIG.replace("[single-ticket]", "[single-ticket, bug-triage]"))
        self.assertEqual(self.render().exit_code, 0)


if __name__ == "__main__":
    unittest.main()
