"""Tests for `stone render`. They render with the real framework in this repo."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import subprocess
import sys
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
  install: pip install .
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
OTHER_FILES = [".claude/settings.json", ".cornerstone/checks/protected_paths.py",
               ".cornerstone/hooks/protect-paths.py", ".cornerstone/manifest.yaml",
               ".github/workflows/cornerstone-checks.yml"]


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
        self.assertEqual(sorted(result.wrote), sorted(ROLE_FILES + OTHER_FILES))
        tester = (self.root / ".claude/agents/tester.md").read_text(encoding="utf-8")
        self.assertIn("model: claude-opus-5-5", tester)
        self.assertIn("Write tests only here: `tests/`", tester)
        self.assertIn("Run `python -m unittest`", tester)
        entry = self.manifest()["components"][-2]
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
        self.assertEqual(len(result.wrote), 9)
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

    def test_settings_merge_keeps_other_keys(self) -> None:
        settings = self.root / ".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"permissions": {"allow": ["Bash(ls)"]}}', encoding="utf-8")
        self.render()
        data = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(data["permissions"], {"allow": ["Bash(ls)"]})
        self.assertEqual(data["hooks"]["PreToolUse"][0]["matcher"],
                         "Edit|Write|MultiEdit|NotebookEdit")
        self.assertIn(".claude/settings.json", self.render().skipped)

    def test_removed_hook_entry_is_drift(self) -> None:
        self.render()
        (self.root / ".claude/settings.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.render().drift, [".claude/settings.json"])

    def run_hook(self, path: str, role: str) -> int:
        event = json.dumps({"tool_input": {"file_path": str(self.root / path)}})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root), "STONE_ROLE": role}
        return subprocess.run([sys.executable, ".cornerstone/hooks/protect-paths.py"],
                              cwd=self.root, input=event, env=env, capture_output=True,
                              text=True).returncode

    def test_hook_blocks_by_role(self) -> None:
        self.render()
        self.assertEqual(self.run_hook("tests/test_a.py", "implementer"), 2)
        self.assertEqual(self.run_hook(".cornerstone/checks/protected_paths.py", "implementer"), 2)
        self.assertEqual(self.run_hook("src/a.py", "implementer"), 0)
        self.assertEqual(self.run_hook("tests/test_a.py", "tester"), 0)
        self.assertEqual(self.run_hook("src/a.py", "tester"), 2)
        self.assertEqual(self.run_hook("src/a.py", "reviewer"), 2)

    def test_hook_uses_the_main_checkout_root(self) -> None:
        self.render()
        self.git("init", "-q")
        self.assertEqual(self.run_hook("src/a.py", "implementer"), 0)
        self.assertEqual(self.run_hook("tests/test_a.py", "implementer"), 2)
        self.assertEqual(self.run_hook("tests/test_a.py", "tester"), 0)
        self.assertEqual(self.run_hook("src/a.py", "tester"), 2)

    def test_hook_uses_the_worktree_root(self) -> None:
        self.render()
        self.git("init", "-q")
        self.commit("README.md", "base")
        self.git("worktree", "add", "-q", "-b", "wt", ".claude/worktrees/wt")
        tree = ".claude/worktrees/wt/"
        self.assertEqual(self.run_hook(tree + "src/a.py", "implementer"), 0)
        self.assertEqual(self.run_hook(tree + "src/new/a.py", "implementer"), 0)
        self.assertEqual(self.run_hook(tree + "tests/test_a.py", "implementer"), 2)
        self.assertEqual(self.run_hook(tree + ".claude/settings.json", "implementer"), 2)
        self.assertEqual(self.run_hook(tree + "tests/test_a.py", "tester"), 0)
        self.assertEqual(self.run_hook(tree + "src/a.py", "tester"), 2)
        self.assertEqual(self.run_hook(".claude/settings.json", "implementer"), 2)

    def test_hook_allows_a_file_outside_the_project_repo(self) -> None:
        self.render()
        self.git("init", "-q")
        with tempfile.TemporaryDirectory() as other:
            subprocess.run(["git", "init", "-q"], cwd=other, check=True)
            for folder in (other, tempfile.gettempdir()):
                outside = os.path.relpath(Path(folder) / "tests" / "test_a.py", self.root)
                self.assertEqual(self.run_hook(outside, "implementer"), 0)
                self.assertEqual(self.run_hook(outside, "reviewer"), 0)

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                       cwd=self.root, check=True, capture_output=True)

    def commit(self, path: str, message: str) -> None:
        (self.root / path).parent.mkdir(parents=True, exist_ok=True)
        (self.root / path).write_text(message, encoding="utf-8")
        self.git("add", path)
        self.git("commit", "-m", message)

    def test_k6_fails_on_an_implementer_commit_to_tests(self) -> None:
        self.render()
        self.git("init", "-q")
        self.commit("README.md", "base")
        self.commit("tests/test_a.py", "add a test\n\nRole: tester")
        self.commit("src/a.py", "change code")
        k6 = [sys.executable, ".cornerstone/checks/protected_paths.py", "HEAD~2"]
        self.assertEqual(subprocess.run(k6, cwd=self.root, capture_output=True).returncode, 0)
        self.commit("tests/test_b.py", "change a test\n\nRole: implementer")
        run = subprocess.run([*k6[:2], "HEAD~3"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)
        self.assertIn("changes tests/test_b.py, a protected path", run.stdout)


if __name__ == "__main__":
    unittest.main()
