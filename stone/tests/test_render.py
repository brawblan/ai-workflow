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
import unittest.mock
from pathlib import Path

import yaml

from stone import cli, render
from stone.markdown import split_frontmatter

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
OTHER_FILES = [".claude/settings.json", ".cornerstone/checks/change_size.py",
               ".cornerstone/checks/protected_paths.py",
               ".cornerstone/hooks/protect-paths.py", ".cornerstone/lib/path_match.py",
               ".cornerstone/manifest.yaml", ".github/workflows/cornerstone-checks.yml"]
PLANNER = ".claude/agents/planner.md"
WORKFLOW = ".github/workflows/cornerstone-checks.yml"
# Trigger workflows (D31): single-ticket and app-slice have the trigger label:agent-ready.
ST_LABEL = ".github/workflows/cornerstone-single-ticket-label.yml"
APP_LABEL = ".github/workflows/cornerstone-app-slice-label.yml"


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
        self.assertEqual(sorted(result.wrote), sorted(ROLE_FILES + OTHER_FILES + [ST_LABEL]))
        tester = (self.root / ".claude/agents/tester.md").read_text(encoding="utf-8")
        self.assertIn("model: claude-opus-5-5", tester)
        self.assertIn("Write tests only here: `tests/`", tester)
        self.assertIn("Run `python -m unittest`", tester)
        entry = {c["id"]: c for c in self.manifest()["components"]}["role.shaper"]
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
        self.assertEqual(sorted(result.wrote), sorted(ROLE_FILES + OTHER_FILES + [ST_LABEL]))
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

    # Issue #126, D55: the hook finds the role in agent_type, then STONE_ROLE, then implementer.
    HOOK_ROLES = ("implementer", "tester", "planner", "investigator", "reviewer")
    ROLE_PROBES = ("tests/test_a.py", "src/a.py", "docs/plans/p.md", "docs/reports/r.md")
    # The exit codes for ROLE_PROBES. Each role has a different pattern.
    ROLE_PATTERN = {"implementer": (2, 0, 0, 0), "tester": (0, 2, 2, 2),
                    "planner": (2, 2, 0, 2), "investigator": (2, 2, 2, 0),
                    "reviewer": (2, 2, 2, 2)}
    UNSET = object()
    ABSENT = object()

    def role_seen(self, stone_role: object = UNSET, agent_type: object = ABSENT,
                  agent_id: str | None = None) -> str:
        """Run the hook on each probe path and return the role that its exit codes show."""
        env = {k: v for k, v in os.environ.items() if k != "STONE_ROLE"}
        env["CLAUDE_PROJECT_DIR"] = str(self.root)
        if stone_role is not self.UNSET:
            env["STONE_ROLE"] = stone_role
        codes = []
        for path in self.ROLE_PROBES:
            event: dict = {"hook_event_name": "PreToolUse", "tool_name": "Edit",
                           "tool_input": {"file_path": str(self.root / path)}}
            if agent_type is not self.ABSENT:
                event["agent_type"] = agent_type
            if agent_id is not None:
                event["agent_id"] = agent_id
            run = subprocess.run([sys.executable, ".cornerstone/hooks/protect-paths.py"],
                                 cwd=self.root, input=json.dumps(event), env=env,
                                 capture_output=True, text=True)
            codes.append(run.returncode)
        for role, pattern in self.ROLE_PATTERN.items():
            if tuple(codes) == pattern:
                return role
        return f"no role: {codes}"

    def test_hook_role_patterns_are_distinct(self) -> None:
        self.render()
        self.assertEqual(len(set(self.ROLE_PATTERN.values())), len(self.ROLE_PATTERN))
        for role in self.HOOK_ROLES:
            self.assertEqual(self.role_seen(stone_role=role), role)

    def test_hook_agent_type_role_wins_over_stone_role(self) -> None:
        self.render()
        for role in self.HOOK_ROLES:
            for env_role in self.HOOK_ROLES:
                with self.subTest(agent_type=role, stone_role=env_role):
                    self.assertEqual(self.role_seen(stone_role=env_role, agent_type=role), role)

    def test_hook_agent_type_role_with_no_stone_role(self) -> None:
        self.render()
        for role in self.HOOK_ROLES:
            with self.subTest(agent_type=role):
                self.assertEqual(self.role_seen(agent_type=role), role)
                self.assertEqual(self.role_seen(stone_role="", agent_type=role), role)

    def test_hook_subagent_uses_the_role_in_agent_type(self) -> None:
        # A lead session (STONE_ROLE=implementer) starts a tester subagent.
        self.render()
        self.assertEqual(self.role_seen(stone_role="implementer", agent_type="tester",
                                        agent_id="a1b2c3"), "tester")
        for role in self.HOOK_ROLES:
            with self.subTest(agent_type=role):
                self.assertEqual(self.role_seen(agent_type=role, agent_id="sub-1"), role)
                self.assertEqual(self.role_seen(stone_role="reviewer", agent_type=role,
                                                agent_id="sub-1"), role)

    def test_hook_tester_subagent_can_edit_tests_under_an_implementer_lead(self) -> None:
        self.render()
        event = json.dumps({"agent_type": "tester", "agent_id": "a1b2c3",
                            "tool_input": {"file_path": str(self.root / "tests/test_a.py")}})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root), "STONE_ROLE": "implementer"}
        run = subprocess.run([sys.executable, ".cornerstone/hooks/protect-paths.py"],
                             cwd=self.root, input=event, env=env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_hook_no_agent_type_uses_stone_role(self) -> None:
        self.render()
        for role in self.HOOK_ROLES:
            with self.subTest(stone_role=role):
                self.assertEqual(self.role_seen(stone_role=role), role)

    def test_hook_agent_type_that_is_not_a_hook_role_uses_stone_role(self) -> None:
        self.render()
        for agent in ("Explore", "general-purpose", "statusline-setup", "", None):
            for role in self.HOOK_ROLES:
                with self.subTest(agent_type=agent, stone_role=role):
                    self.assertEqual(self.role_seen(stone_role=role, agent_type=agent), role)
                    self.assertEqual(self.role_seen(stone_role=role, agent_type=agent,
                                                    agent_id="sub-1"), role)

    def test_hook_no_role_anywhere_uses_implementer(self) -> None:
        self.render()
        for stone_role in (self.UNSET, ""):
            with self.subTest(stone_role="unset" if stone_role is self.UNSET else "empty"):
                self.assertEqual(self.role_seen(stone_role=stone_role), "implementer")
                for agent in ("Explore", "general-purpose", "statusline-setup", "", None):
                    with self.subTest(agent_type=agent):
                        self.assertEqual(self.role_seen(stone_role=stone_role, agent_type=agent),
                                         "implementer")
                        self.assertEqual(self.role_seen(stone_role=stone_role, agent_type=agent,
                                                        agent_id="sub-1"), "implementer")

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

    def app_slice(self, plans: str | None = "docs/plans/") -> None:
        text = CONFIG.replace("[single-ticket]", "[app-slice]")
        line = "  plans: docs/plans/\n"
        self.write_config(text.replace(line, f"  plans: {plans}\n" if plans else ""))

    def planner_model(self) -> str:
        profile = FRAMEWORK / "adapters/claude-code/models/claude-5.yaml"
        data = yaml.safe_load(profile.read_text(encoding="utf-8"))
        return data["defaults"]["role_models"]["planner"]

    def test_app_slice_writes_the_planner_role(self) -> None:
        self.app_slice()
        result = self.render()
        self.assertEqual(sorted(result.wrote),
                         sorted(ROLE_FILES + [PLANNER] + OTHER_FILES + [APP_LABEL]))
        planner = (self.root / PLANNER).read_text(encoding="utf-8")
        self.assertIn(f"model: {self.planner_model()}", planner)
        self.assertIn("Write only in `docs/plans/`", planner)
        self.assertIn("`docs/plans/<ticket-id>.md`", planner)
        self.assertIn("`docs/plans/<ticket-id>.progress.json`", planner)
        self.assertNotIn("$", planner)
        entry = {c["id"]: c for c in self.manifest()["components"]}["role.planner"]
        self.assertEqual((entry["owner"], entry["added"], entry["review_by"], entry["files"]),
                         ("octocat", "2026-10-17", "2027-04-17", [PLANNER]))

    def test_planner_uses_a_non_default_plans_path(self) -> None:
        self.app_slice("work/specs/")
        self.render()
        planner = (self.root / PLANNER).read_text(encoding="utf-8")
        self.assertIn("Write only in `work/specs/`", planner)
        self.assertIn("`work/specs/<ticket-id>.md`", planner)
        self.assertIn("`work/specs/<ticket-id>.progress.json`", planner)
        self.assertNotIn("docs/plans", planner)

    def test_planner_uses_the_default_plans_path_when_the_config_has_none(self) -> None:
        self.app_slice(plans=None)
        self.render()
        self.assertIn("Write only in `docs/plans/`",
                      (self.root / PLANNER).read_text(encoding="utf-8"))

    def test_new_plans_path_updates_the_planner_file(self) -> None:
        self.app_slice()
        self.render()
        self.app_slice("work/specs/")
        result = self.render()
        self.assertEqual(result.drift, [])
        self.assertIn(PLANNER, result.wrote)
        self.assertIn(".cornerstone/hooks/protect-paths.py", result.wrote)
        self.assertIn("`work/specs/`", (self.root / PLANNER).read_text(encoding="utf-8"))

    def test_second_app_slice_render_writes_nothing(self) -> None:
        self.app_slice()
        self.render()
        self.assertEqual(self.render().wrote, [])

    def test_app_slice_with_single_ticket_writes_the_planner_once(self) -> None:
        self.write_config(CONFIG.replace("[single-ticket]", "[single-ticket, app-slice]"))
        result = self.render()
        self.assertEqual(sorted(result.wrote),
                         sorted(ROLE_FILES + [PLANNER] + OTHER_FILES + [ST_LABEL, APP_LABEL]))

    def test_hook_limits_the_planner_to_the_plans_path(self) -> None:
        self.app_slice("work/specs/")
        self.render()
        self.assertEqual(self.run_hook("work/specs/T-1.md", "planner"), 0)
        self.assertEqual(self.run_hook("work/specs/T-1.progress.json", "planner"), 0)
        self.assertEqual(self.run_hook("work/specs/sub/T-1.md", "planner"), 0)
        self.assertEqual(self.run_hook("src/a.py", "planner"), 2)
        self.assertEqual(self.run_hook("tests/test_a.py", "planner"), 2)
        self.assertEqual(self.run_hook("docs/plans/T-1.md", "planner"), 2)
        self.assertEqual(self.run_hook("work/specs-old/T-1.md", "planner"), 2)
        self.assertEqual(self.run_hook("work/T-1.md", "planner"), 2)
        self.assertEqual(self.run_hook(".claude/agents/planner.md", "planner"), 2)
        self.assertEqual(self.run_hook(".cornerstone/config.yaml", "planner"), 2)

    def test_hook_tells_the_planner_why_it_blocks(self) -> None:
        self.app_slice()
        self.render()
        event = json.dumps({"tool_input": {"file_path": str(self.root / "src/a.py")}})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root), "STONE_ROLE": "planner"}
        run = subprocess.run([sys.executable, ".cornerstone/hooks/protect-paths.py"],
                             cwd=self.root, input=event, env=env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertIn("src/a.py is not a plan path", run.stderr)
        self.assertIn("docs/plans/", run.stderr)

    def test_hook_limits_the_planner_in_a_worktree(self) -> None:
        self.app_slice()
        self.render()
        self.git("init", "-q")
        self.commit("README.md", "base")
        self.git("worktree", "add", "-q", "-b", "wt", ".claude/worktrees/wt")
        tree = ".claude/worktrees/wt/"
        self.assertEqual(self.run_hook(tree + "docs/plans/T-1.md", "planner"), 0)
        self.assertEqual(self.run_hook(tree + "src/a.py", "planner"), 2)
        self.assertEqual(self.run_hook(tree + "tests/test_a.py", "planner"), 2)

    def rendered_files(self) -> dict[str, str]:
        return {str(p.relative_to(self.root)): p.read_text(encoding="utf-8")
                for p in sorted(self.root.rglob("*")) if p.is_file()
                and p.relative_to(self.root).as_posix() != ".cornerstone/config.yaml"}

    def test_plans_path_with_no_trailing_slash_gets_one(self) -> None:
        self.app_slice("docs/plans")
        self.render()
        planner = (self.root / PLANNER).read_text(encoding="utf-8")
        self.assertIn("Write only in `docs/plans/`", planner)
        self.assertIn("`docs/plans/<ticket-id>.md`", planner)
        self.assertIn("`docs/plans/<ticket-id>.progress.json`", planner)
        self.assertNotIn("docs/plans<", planner)
        self.assertEqual(self.run_hook("docs/plans/x.md", "planner"), 0)
        self.assertEqual(self.run_hook("docs/plans/x.progress.json", "planner"), 0)
        self.assertEqual(self.run_hook("docs/plansx/x.md", "planner"), 2)
        self.assertEqual(self.run_hook("docs/plans.md", "planner"), 2)
        self.assertEqual(self.run_hook("src/a.py", "planner"), 2)

    def test_plans_path_with_and_without_slash_render_the_same(self) -> None:
        self.app_slice("docs/plans/")
        self.render()
        with_slash = self.rendered_files()
        self.folder.cleanup()
        self.setUp()
        self.app_slice("docs/plans")
        self.render()
        self.assertEqual(self.rendered_files(), with_slash)

    def test_plans_list_of_one_folder_renders_the_same_as_the_string(self) -> None:
        self.app_slice("docs/plans/")
        self.render()
        as_string = self.rendered_files()
        self.folder.cleanup()
        self.setUp()
        self.app_slice("[docs/plans/]")
        self.render()
        self.assertEqual(self.rendered_files(), as_string)
        self.assertEqual(self.run_hook("docs/plans/x.md", "planner"), 0)
        self.assertEqual(self.run_hook("src/a.py", "planner"), 2)

    def test_plans_list_of_two_folders_stops_before_any_write(self) -> None:
        for plans in ("[docs/plans/, work/specs/]", "[a/, b/, c/]"):
            with self.subTest(plans=plans):
                self.app_slice(plans)
                with self.assertRaisesRegex(render.RenderError, r"paths\.plans"):
                    self.render()
                self.assertFalse((self.root / ".claude").exists())
                self.assertFalse((self.root / ".github").exists())
                self.assertFalse((self.root / render.MANIFEST).exists())
                self.assertEqual(sorted(p.name for p in (self.root / ".cornerstone").iterdir()),
                                 ["config.yaml"])

    def test_plans_list_of_two_folders_changes_no_rendered_file(self) -> None:
        self.app_slice()
        self.render()
        before = self.rendered_files()
        self.app_slice("[docs/plans/, work/specs/]")
        with self.assertRaisesRegex(render.RenderError, r"paths\.plans"):
            self.render()
        self.assertEqual(self.rendered_files(), before)

    def test_app_slice_hook_keeps_the_other_role_rules(self) -> None:
        self.app_slice()
        self.render()
        self.assertEqual(self.run_hook("tests/test_a.py", "implementer"), 2)
        self.assertEqual(self.run_hook("src/a.py", "implementer"), 0)
        self.assertEqual(self.run_hook("tests/test_a.py", "tester"), 0)
        self.assertEqual(self.run_hook("docs/plans/T-1.md", "tester"), 2)
        self.assertEqual(self.run_hook("docs/plans/T-1.md", "reviewer"), 2)

    def test_single_ticket_does_not_write_the_planner(self) -> None:
        expected = sorted(ROLE_FILES + OTHER_FILES + [ST_LABEL])
        result = self.render()
        self.assertEqual(sorted(result.wrote), expected)
        self.assertFalse((self.root / PLANNER).exists())
        self.assertNotIn("role.planner", [c["id"] for c in self.manifest()["components"]])
        self.assertEqual(sorted(self.render(dry_run=True).skipped), expected)

    def test_single_ticket_hook_keeps_the_role_rules(self) -> None:
        self.render()
        self.assertEqual(self.run_hook("tests/test_a.py", "implementer"), 2)
        self.assertEqual(self.run_hook("docs/plans/T-1.md", "implementer"), 0)
        self.assertEqual(self.run_hook("tests/test_a.py", "tester"), 0)
        self.assertEqual(self.run_hook("docs/plans/T-1.md", "tester"), 2)
        self.assertEqual(self.run_hook("docs/plans/T-1.md", "reviewer"), 2)

    # Specs part 2, AC4: the specs path is protected

    def specs_path(self, value: str | None, profile: str = "[app-slice]") -> None:
        text = CONFIG.replace("[single-ticket]", profile)
        line = "  plans: docs/plans/\n"
        self.write_config(text.replace(line, line + (f"  specs: {value}\n" if value else "")))

    def protected_list(self, path: str) -> list[str]:
        text = (self.root / path).read_text(encoding="utf-8")
        line = next(line for line in text.splitlines() if line.startswith("PROTECTED = "))
        return json.loads(line[len("PROTECTED = "):])

    def test_specs_default_path_is_in_the_hook_and_k6_lists(self) -> None:
        self.specs_path(None)
        self.render()
        for path in (".cornerstone/hooks/protect-paths.py",
                     ".cornerstone/checks/protected_paths.py"):
            with self.subTest(path=path):
                self.assertIn("docs/specs/", self.protected_list(path))

    def test_specs_path_is_protected_in_the_single_ticket_profile(self) -> None:
        self.specs_path(None, "[single-ticket]")
        self.render()
        self.assertIn("docs/specs/", self.protected_list(".cornerstone/hooks/protect-paths.py"))
        self.assertEqual(self.run_hook("docs/specs/export.md", "implementer"), 2)

    def test_hook_blocks_each_writing_role_on_the_specs_path(self) -> None:
        self.specs_path(None)
        self.render()
        for role in ("implementer", "tester", "planner", "reviewer"):
            for path in ("docs/specs/export.md", "docs/specs/sub/a.md"):
                with self.subTest(role=role, path=path):
                    self.assertEqual(self.run_hook(path, role), 2)
        # The roles keep their own paths.
        self.assertEqual(self.run_hook("docs/plans/T-1.spec.md", "planner"), 0)
        self.assertEqual(self.run_hook("tests/test_a.py", "tester"), 0)
        self.assertEqual(self.run_hook("src/a.py", "implementer"), 0)

    def test_hook_tells_the_implementer_why_it_blocks_a_spec(self) -> None:
        self.specs_path(None)
        self.render()
        event = json.dumps({"tool_input": {"file_path": str(self.root / "docs/specs/export.md")}})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root), "STONE_ROLE": "implementer"}
        run = subprocess.run([sys.executable, ".cornerstone/hooks/protect-paths.py"],
                             cwd=self.root, input=event, env=env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertIn("docs/specs/export.md", run.stderr)

    def test_hook_blocks_the_specs_path_in_a_worktree(self) -> None:
        self.specs_path(None)
        self.render()
        self.git("init", "-q")
        self.commit("README.md", "base")
        self.git("worktree", "add", "-q", "-b", "wt", ".claude/worktrees/wt")
        tree = ".claude/worktrees/wt/"
        for role in ("implementer", "tester", "planner"):
            with self.subTest(role=role):
                self.assertEqual(self.run_hook(tree + "docs/specs/export.md", role), 2)

    def test_specs_path_from_the_config_is_protected(self) -> None:
        self.specs_path("product/specs/")
        self.render()
        self.assertIn("product/specs/", self.protected_list(".cornerstone/hooks/protect-paths.py"))
        self.assertNotIn("docs/specs/",
                         self.protected_list(".cornerstone/hooks/protect-paths.py"))
        for role in ("implementer", "tester", "planner"):
            with self.subTest(role=role):
                self.assertEqual(self.run_hook("product/specs/export.md", role), 2)
        self.assertEqual(self.run_hook("docs/specs/export.md", "implementer"), 0)

    def test_specs_path_with_no_trailing_slash_gets_one(self) -> None:
        self.specs_path("product/specs")
        self.render()
        for path in (".cornerstone/hooks/protect-paths.py",
                     ".cornerstone/checks/protected_paths.py"):
            with self.subTest(path=path):
                self.assertIn("product/specs/", self.protected_list(path))
                self.assertNotIn("product/specs", self.protected_list(path))
        self.assertEqual(self.run_hook("product/specs/export.md", "implementer"), 2)
        self.assertEqual(self.run_hook("product/specsx/export.md", "implementer"), 0)
        self.assertEqual(self.run_hook("product/specs.md", "implementer"), 0)

    def test_specs_list_of_one_folder_renders_the_same_as_the_string(self) -> None:
        self.specs_path("product/specs/")
        self.render()
        as_string = self.rendered_files()
        self.folder.cleanup()
        self.setUp()
        self.specs_path("[product/specs/]")
        self.render()
        self.assertEqual(self.rendered_files(), as_string)

    def test_specs_list_of_two_folders_stops_before_any_write(self) -> None:
        self.specs_path("[docs/specs/, product/specs/]")
        with self.assertRaisesRegex(render.RenderError, r"paths\.specs"):
            self.render()
        self.assertFalse((self.root / ".claude").exists())
        self.assertFalse((self.root / render.MANIFEST).exists())

    def test_new_specs_path_updates_the_hook_and_k6(self) -> None:
        self.specs_path(None)
        self.render()
        self.specs_path("product/specs/")
        result = self.render()
        self.assertEqual(result.drift, [])
        self.assertIn(".cornerstone/hooks/protect-paths.py", result.wrote)
        self.assertIn(".cornerstone/checks/protected_paths.py", result.wrote)
        self.assertEqual(self.run_hook("product/specs/export.md", "implementer"), 2)

    def test_hook_blocks_the_planner_on_a_specs_path_in_the_plans_path(self) -> None:
        # Edge: rule 4 says the hook stops the planner on the specs path. That must hold
        # also when the config puts the specs folder in the plans folder.
        self.specs_path("docs/plans/specs/")
        self.render()
        self.assertEqual(self.run_hook("docs/plans/T-1.md", "planner"), 0)
        self.assertEqual(self.run_hook("docs/plans/specs/export.md", "planner"), 2)

    def hook_message(self, path: str, role: str) -> str:
        event = json.dumps({"tool_input": {"file_path": str(self.root / path)}})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root), "STONE_ROLE": role}
        run = subprocess.run([sys.executable, ".cornerstone/hooks/protect-paths.py"],
                             cwd=self.root, input=event, env=env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        return run.stderr

    def test_hook_tells_the_planner_which_rule_blocks(self) -> None:
        self.specs_path("docs/plans/specs/")
        self.render()
        inside = self.hook_message("docs/plans/specs/export.md", "planner")
        self.assertIn("docs/plans/specs/export.md is a protected path", inside)
        self.assertNotIn("is not a plan path", inside)
        outside = self.hook_message("src/a.py", "planner")
        self.assertIn("src/a.py is not a plan path", outside)
        self.assertNotIn("protected path", outside)

    def test_k6_fails_on_an_implementer_commit_to_the_specs_path(self) -> None:
        self.specs_path(None)
        self.render()
        self.git("init", "-q")
        self.commit("README.md", "base")
        self.commit("docs/specs/export.md", "write the specs\n\nRole: generator")
        k6 = [sys.executable, ".cornerstone/checks/protected_paths.py", "HEAD~1"]
        self.assertEqual(subprocess.run(k6, cwd=self.root, capture_output=True).returncode, 0)
        self.commit("docs/specs/export.md", "edit a spec by hand")
        run = subprocess.run([*k6[:2], "HEAD~2"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)
        self.assertIn("changes docs/specs/export.md, a protected path", run.stdout)

    def test_change_to_single_ticket_reports_the_planner_as_stale(self) -> None:
        self.app_slice()
        self.render()
        self.write_config(CONFIG)
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            result = render.render(self.root, FRAMEWORK, today=TODAY)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("stale role.planner", log.getvalue())
        self.assertTrue((self.root / PLANNER).exists())
        self.assertNotIn("role.planner", [c["id"] for c in self.manifest()["components"]])

    # K14 in the rendered G3 workflow (D23).

    def workflow_text(self) -> str:
        return (self.root / WORKFLOW).read_text(encoding="utf-8")

    def workflow_steps(self) -> list[dict]:
        return yaml.safe_load(self.workflow_text())["jobs"]["checks"]["steps"]

    def step(self, name: str) -> dict:
        steps = [s for s in self.workflow_steps() if s.get("name") == name]
        self.assertEqual(len(steps), 1, f"want one step named {name!r}")
        return steps[0]

    def render_log(self, version: str) -> str:
        self.write_config(CONFIG.replace("framework_version: 0.1.0",
                                         f"framework_version: {version}"))
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            result = render.render(self.root, FRAMEWORK, today=TODAY)
        self.assertEqual(result.exit_code, 0)
        self.assertTrue((self.root / WORKFLOW).exists())
        return log.getvalue()

    def test_workflow_installs_stone_from_the_framework_tag(self) -> None:
        for version in ("0.1.0", "0.5.0", "1.2.3"):
            with self.subTest(version=version):
                self.render_log(version)
                install = self.step("Install stone")
                self.assertEqual(install["env"]["STONE_TAG"], f"v{version}")
                self.assertIn("git+https://github.com/brawblan/ai-workflow@${STONE_TAG}"
                              "#subdirectory=stone", install["run"])
                self.assertNotIn("$framework_version", self.workflow_text())

    def test_install_stone_uses_the_package_name_of_the_cli(self) -> None:
        self.render()
        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8")
        name = next(line.split("=", 1)[1].strip().strip('"')
                    for line in pyproject.splitlines() if line.startswith("name"))
        self.assertIn(f'"{name} @ git+', self.step("Install stone")["run"])

    def test_k14_step_reads_the_pr_body_through_env(self) -> None:
        self.render()
        k14 = self.step("K14 PR evidence")
        self.assertEqual(k14["env"]["PR_BODY"], "${{ github.event.pull_request.body }}")
        self.assertNotIn("github.event.pull_request.body", k14["run"])
        self.assertIn("PR_BODY", k14["run"])
        self.assertIn("check-evidence", k14["run"])
        self.assertIn("--mode block", k14["run"])
        self.assertNotIn("--mode warn", k14["run"])

    def test_no_run_text_has_an_expression(self) -> None:
        self.render()
        for step in self.workflow_steps():
            with self.subTest(step=step.get("name", step.get("uses"))):
                self.assertNotIn("${{", step.get("run", ""))

    def test_k14_in_warn_mode_does_not_fail_on_an_empty_body(self) -> None:
        stdout = io.StringIO()
        with (contextlib.redirect_stdout(stdout),
              unittest.mock.patch("sys.stdin", io.StringIO("\n"))):
            code = cli.main(["check-evidence", "-", "--mode", "warn", "--format", "github"])
        self.assertEqual(code, 0)
        self.assertIn("mode warn", stdout.getvalue())

    def test_workflow_parses_and_keeps_the_step_order(self) -> None:
        self.render()
        names = [s["name"] for s in self.workflow_steps() if "name" in s]
        self.assertEqual(len(names), 6, names)
        self.assertTrue(names[0].startswith("K6"), names)
        self.assertTrue(names[1].startswith("K7"), names)
        self.assertEqual(names[2], "Install stone")
        self.assertTrue(names[3].startswith("K14"), names)
        self.assertEqual(names[4:], ["Install", "All checks"])
        self.assertEqual(self.step("Install")["run"], "pip install .")
        self.assertEqual(self.step("All checks")["run"], "make check")

    def test_old_framework_version_warns(self) -> None:
        for version in ("0.1.0", "0.4.9", "0.4.99"):
            with self.subTest(version=version):
                log = self.render_log(version)
                self.assertIn("warning: framework_version", log)
                self.assertIn(version, log)
                self.assertIn("0.5.0", log)

    def test_framework_version_from_0_5_0_does_not_warn(self) -> None:
        for version in ("0.5.0", "0.5.1", "0.6.0", "0.10.0", "1.0.0"):
            with self.subTest(version=version):
                self.assertNotIn("framework_version", self.render_log(version))

    def assert_full_tag_warning(self, log: str, shown: str) -> None:
        self.assertIn(f"warning: framework_version {shown} is not a tag with "
                      "'stone check-evidence'.", log)
        self.assertIn("Use a full tag, 0.5.0 or later.", log)

    def test_old_framework_version_warns_with_the_full_tag_text(self) -> None:
        for version in ("0.1.0", "0.4.9"):
            with self.subTest(version=version):
                self.assert_full_tag_warning(self.render_log(version), version)

    def test_framework_version_0_5_with_two_parts_warns(self) -> None:
        # Owner decision 2026-10-18: v0.5 is not a tag, so '0.5' must warn.
        log = self.render_log("'0.5'")
        self.assert_full_tag_warning(log, "0.5")
        self.assertEqual(log.count("warning: framework_version"), 1, log)

    def test_framework_version_0_5_as_a_yaml_number_warns(self) -> None:
        # Without quotes, YAML reads 0.5 as a float. It must warn the same way.
        self.assert_full_tag_warning(self.render_log("0.5"), "0.5")

    def test_framework_version_with_two_parts_below_0_5_warns(self) -> None:
        for version in ("'0.4'", "'0.1'"):
            with self.subTest(version=version):
                self.assert_full_tag_warning(self.render_log(version), version.strip("'"))

    def test_framework_version_1_0_with_two_parts_does_not_warn(self) -> None:
        # (1, 0) >= (0, 5, 0), so '1.0' does not warn (ticket criterion 2).
        for version in ("'1.0'", "1.0", "'0.6'"):
            with self.subTest(version=version):
                self.assertNotIn("framework_version", self.render_log(version))

    def test_framework_version_that_is_not_numbers_does_not_warn_or_crash(self) -> None:
        for version in ("main", "v0.5.0", "0.5.0-rc1", "'0.x'", "latest"):
            with self.subTest(version=version):
                self.assertNotIn("framework_version", self.render_log(version))

    def test_each_profile_with_g3_lists_k6_and_k14(self) -> None:
        # The rendered G3 workflow runs K6 and K14, so each profile with G3 must list both.
        names = sorted(p.stem for p in (FRAMEWORK / "profiles").glob("*.md")
                       if p.stem not in {"README", "_template"})
        with_g3 = []
        for name in names:
            text = (FRAMEWORK / "profiles" / f"{name}.md").read_text(encoding="utf-8")
            profile = split_frontmatter(text)[0]
            if profile["gates"].get("G3", "skip") == "skip":
                continue
            with_g3.append(name)
            with self.subTest(profile=name):
                self.assertIn("K6", profile["checks"])
                self.assertIn("K14", profile["checks"])
        self.assertIn("single-ticket", with_g3)
        self.assertIn("app-slice", with_g3)


if __name__ == "__main__":
    unittest.main()
