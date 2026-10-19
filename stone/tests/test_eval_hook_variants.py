"""Tests for the variants of a hook eval (issue #80, D44).

The "without" variant of hook.protect-paths must be a clean baseline: no hook file, no settings
entry for it, and the same role file and harness command as "with". The workspace tests use the
runner's own setup (`evals.prepare`) with the real framework and the real eval folder. The launch
tests use the fake harness of test_evals.py. No model starts.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

import test_evals as base
from stone import evals

REPO = Path(__file__).resolve().parents[2]
FRAMEWORK = REPO / "framework"
EVAL = REPO / "evals" / "hook-protect-paths"
HOOK_FILE = ".cornerstone/hooks/protect-paths.py"
IMPLEMENTER = ".claude/agents/implementer.md"
TESTER = ".claude/agents/tester.md"
SETTINGS = ".claude/settings.json"
MATCHER = "Edit|Write|MultiEdit|NotebookEdit"
SCENARIO = {"id": "V1", "fixture": "fixtures/stats"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def entries(settings: Any) -> list[dict[str, Any]]:
    return (settings.get("hooks") or {}).get("PreToolUse") or []


def git_status(path: Path) -> str:
    return subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=path,
                          capture_output=True, text=True, check=True).stdout


class WorkspaceCase(unittest.TestCase):
    def workspace(self, variant: str, folder: Path = EVAL, role_file: str = HOOK_FILE,
                  scenario: dict[str, Any] | None = None) -> Path:
        ws = evals.prepare(folder, scenario or SCENARIO, FRAMEWORK, role_file, variant).path
        self.addCleanup(shutil.rmtree, ws.parent, True)
        return ws


class HookWorkspaceTest(WorkspaceCase):
    def test_without_has_no_hook_file(self) -> None:
        self.assertFalse((self.workspace("without") / HOOK_FILE).exists())

    def test_without_settings_name_no_hook_path_and_have_no_pretooluse_matcher(self) -> None:
        text = (self.workspace("without") / SETTINGS).read_text(encoding="utf-8")
        self.assertNotIn(HOOK_FILE, text)
        data = json.loads(text)
        self.assertIsInstance(data, dict)
        self.assertEqual(entries(data), [])
        self.assertNotIn("matcher", text)

    def test_without_keeps_the_implementer_role_file(self) -> None:
        self.assertTrue((self.workspace("without") / IMPLEMENTER).is_file())

    def test_without_setup_commit_is_clean(self) -> None:
        self.assertEqual(git_status(self.workspace("without")), "")

    def test_with_has_the_hook_file_the_settings_entry_and_the_role_file(self) -> None:
        ws = self.workspace("with")
        self.assertTrue((ws / HOOK_FILE).is_file())
        self.assertTrue((ws / IMPLEMENTER).is_file())
        found = entries(read_json(ws / SETTINGS))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["matcher"], MATCHER)
        self.assertIn(HOOK_FILE, json.dumps(found[0]))
        self.assertEqual(git_status(ws), "")

    def test_the_two_variants_differ_only_in_the_hook(self) -> None:
        with_ws, without_ws = self.workspace("with"), self.workspace("without")

        def files(ws: Path) -> set[str]:
            return {p.relative_to(ws).as_posix() for p in ws.rglob("*")
                    if p.is_file() and ".git" not in p.relative_to(ws).parts}

        self.assertEqual(files(with_ws) - files(without_ws), {HOOK_FILE})
        self.assertEqual(files(without_ws) - files(with_ws), set())
        self.assertEqual((with_ws / IMPLEMENTER).read_text(encoding="utf-8"),
                         (without_ws / IMPLEMENTER).read_text(encoding="utf-8"))


class OtherSettingsTest(WorkspaceCase):
    """The fixture already has a settings file. Render merges the hook entry into it."""

    OTHER = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo other-hook"}]}

    def folder(self, settings: dict[str, Any]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        copy = Path(tmp.name) / "hook-protect-paths"
        shutil.copytree(EVAL, copy)
        target = copy / "fixtures" / "stats" / SETTINGS
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(settings), encoding="utf-8")
        return copy

    def test_without_keeps_another_pretooluse_entry_a_permissions_key_and_another_hook(self) -> None:
        fixture = {"permissions": {"allow": ["Read"]},
                   "hooks": {"PreToolUse": [self.OTHER],
                             "PostToolUse": [{"matcher": "Write", "hooks": [
                                 {"type": "command", "command": "echo post"}]}]}}
        ws = self.workspace("without", self.folder(fixture))
        data = read_json(ws / SETTINGS)
        self.assertNotIn(HOOK_FILE, json.dumps(data))
        self.assertEqual(data["permissions"], {"allow": ["Read"]})
        self.assertEqual(data["hooks"]["PreToolUse"], [self.OTHER])
        self.assertEqual(data["hooks"]["PostToolUse"], fixture["hooks"]["PostToolUse"])
        self.assertEqual(git_status(ws), "")

    def test_with_keeps_the_other_entry_and_adds_the_hook_entry(self) -> None:
        ws = self.workspace("with", self.folder({"hooks": {"PreToolUse": [self.OTHER]}}))
        found = entries(read_json(ws / SETTINGS))
        self.assertIn(self.OTHER, found)
        self.assertEqual(sum(HOOK_FILE in json.dumps(item) for item in found), 1)

    def test_unregister_removes_only_the_entry_that_names_the_target(self) -> None:
        mine = {"matcher": MATCHER, "hooks": [{"type": "command", "command": f"python3 {HOOK_FILE}"}]}
        data = {"permissions": {"deny": ["Bash(rm*)"]},
                "hooks": {"PreToolUse": [self.OTHER, mine],
                          "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}]}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            evals.unregister(path, HOOK_FILE)
            result = read_json(path)
        self.assertEqual(result["permissions"], data["permissions"])
        self.assertEqual(result["hooks"]["PreToolUse"], [self.OTHER])
        self.assertEqual(result["hooks"]["Stop"], data["hooks"]["Stop"])


class UnregisterTest(unittest.TestCase):
    def write(self, data: Any) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "settings.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_a_second_call_changes_nothing(self) -> None:
        path = self.write({"permissions": {"allow": ["Read"]}, "hooks": {"PreToolUse": [
            {"matcher": MATCHER, "hooks": [{"type": "command", "command": HOOK_FILE}]},
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo x"}]}]}})
        evals.unregister(path, HOOK_FILE)
        once = path.read_text(encoding="utf-8")
        evals.unregister(path, HOOK_FILE)
        self.assertEqual(path.read_text(encoding="utf-8"), once)
        self.assertNotIn(HOOK_FILE, once)

    def test_a_file_with_no_matching_entry_keeps_the_same_data(self) -> None:
        data = {"permissions": {"allow": ["Read"], "deny": []}, "env": {"A": "1"},
                "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "echo x"}]}], "Stop": []}}
        path = self.write(data)
        evals.unregister(path, HOOK_FILE)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), data)

    def test_an_empty_object_stays_a_valid_json_object(self) -> None:
        path = self.write({})
        evals.unregister(path, HOOK_FILE)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {})


class RegisteredInTest(unittest.TestCase):
    def test_the_hook_path_is_registered_in_the_settings_file(self) -> None:
        self.assertEqual(evals.registered_in(FRAMEWORK, "claude-code", HOOK_FILE), [SETTINGS])

    def test_a_role_file_is_registered_in_no_shared_file(self) -> None:
        self.assertEqual(evals.registered_in(FRAMEWORK, "claude-code", TESTER), [])


class RoleWorkspaceTest(WorkspaceCase):
    def test_without_removes_the_role_file_and_keeps_the_settings_of_with(self) -> None:
        folder = REPO / "evals" / "role-tester"
        scenario = {"id": "V2", "fixture": "fixtures/slugify"}
        with_ws = self.workspace("with", folder, TESTER, scenario)
        without_ws = self.workspace("without", folder, TESTER, scenario)
        self.assertTrue((with_ws / TESTER).is_file())
        self.assertFalse((without_ws / TESTER).exists())
        self.assertTrue((with_ws / SETTINGS).is_file())
        self.assertEqual((without_ws / SETTINGS).read_text(encoding="utf-8"),
                         (with_ws / SETTINGS).read_text(encoding="utf-8"))
        self.assertEqual(git_status(without_ws), "")


class LaunchTest(base.EvalTestCase):
    """The command and environment that start the harness, for a hook and for a role."""

    def setUp(self) -> None:
        super().setUp()
        self.tools = {"implementer": ["Read", "Edit"], "tester": ["Read"]}

    def hook_repo(self) -> None:
        """Use the real hook component and a copy of the real eval folder and its fixture."""
        shutil.copytree(EVAL / "fixtures", self.root / "evals" / "hook-protect-paths" / "fixtures")
        self.write("evals/hook-protect-paths/scenarios.yaml", yaml.safe_dump({
            "component": "hook.protect-paths", "role": "implementer",
            "scenarios": [{"id": "H1", "fixture": "fixtures/stats", "prompt": "Do it.",
                           "expect": [{"check": "file_exists", "path": "src/stats.py"}]}]},
            sort_keys=False))
        self.write_run_config(
            env={"with": {"FAKE_ROLE": "with-$role", "FAKE_KIND": "env-with"},
                 "without": {"FAKE_ROLE": "without-$role", "FAKE_KIND": "env-without"}},
            tools=self.tools)
        self.plan({"read": [SETTINGS]})

    def run_hook(self) -> dict[str, dict]:
        """Run both variants. Return the two calls by variant, found from the workspace files.

        The fake harness names a call by the first argument of the command. If the runner uses
        the `run.with` command for both runs, both calls say "with". So the test tells the runs
        apart by the hook file in the workspace.
        """
        self.hook_repo()
        code, out = self.eval_component("hook.protect-paths")
        self.assertEqual(code, 0, out)
        calls = self.calls()
        self.assertEqual([call["variant"] for call in calls], ["with", "with"])
        found = {("with" if HOOK_FILE in call["files"] else "without"): call for call in calls}
        self.assertEqual(sorted(found), ["with", "without"])
        return found

    def eval_component(self, component: str) -> tuple[int, str]:
        import contextlib
        import io

        from stone import cli
        argv = ["eval", component, "--root", str(self.root), "--framework", str(base.FRAMEWORK),
                "--run-config", str(self.run_yaml)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(argv)
        return code, out.getvalue()

    def test_hook_without_run_uses_the_with_argv_that_has_the_agent_flag(self) -> None:
        calls = self.run_hook()
        self.assertEqual(calls["without"]["argv"], calls["with"]["argv"])
        self.assertEqual(base.arg(calls["without"], "--role"), "implementer")

    def test_hook_without_run_uses_the_with_environment(self) -> None:
        calls = self.run_hook()
        self.assertEqual(calls["with"]["env"]["FAKE_KIND"], "env-with")
        self.assertEqual(calls["without"]["env"], calls["with"]["env"])
        self.assertEqual(calls["without"]["env"]["FAKE_ROLE"], "with-implementer")

    def test_hook_without_settings_have_no_hook_entry_when_the_harness_starts(self) -> None:
        calls = self.run_hook()
        with_settings = json.loads(calls["with"]["texts"][SETTINGS])
        without_settings = json.loads(calls["without"]["texts"][SETTINGS])
        self.assertIn(HOOK_FILE, json.dumps(with_settings))
        self.assertNotIn(HOOK_FILE, json.dumps(without_settings))
        self.assertEqual(entries(without_settings), [])
        self.assertNotIn(HOOK_FILE, calls["without"]["files"])
        self.assertIn(IMPLEMENTER, calls["without"]["files"])

    def test_role_without_run_still_uses_the_without_argv_and_environment(self) -> None:
        self.write_run_config(tools=self.tools)
        self.scenarios(self.scenario(fixture="fixtures/rendered"))
        code, out = self.eval("--trials", "1")
        self.assertEqual(code, 0, out)
        calls = {call["variant"]: call for call in self.calls()}
        self.assertEqual(sorted(calls), ["with", "without"])
        self.assertEqual(calls["with"]["env"]["FAKE_ROLE"], "tester")
        self.assertEqual(calls["without"]["env"], {"FAKE_ROLE": "without-tester"})
        self.assertNotIn(base.ROLE_FILE, calls["without"]["files"])
        self.assertIn(base.ROLE_FILE, calls["with"]["files"])


if __name__ == "__main__":
    unittest.main()
