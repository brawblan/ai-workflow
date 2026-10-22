"""Tests for the hook.protect-paths eval in evals/hook-protect-paths/ (D39).

Each test makes a workspace with the runner's own setup (`evals.prepare`): the fixture, the render
commit, and the "without" variant if a test asks for it. Then it runs grade.py as a subprocess, as
`stone eval` does. No model or harness starts. A test runs the shell command of a scenario itself
when it must act as the model.
"""

from __future__ import annotations

import contextlib
import errno
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import yaml

from stone import cli, evals

REPO = Path(__file__).resolve().parents[2]
FRAMEWORK = REPO / "framework"
EVAL = REPO / "evals" / "hook-protect-paths"
GRADE = EVAL / "grade.py"
HOOK_FILE = ".cornerstone/hooks/protect-paths.py"
SCENARIOS = {s["id"]: s for s in
             yaml.safe_load((EVAL / "scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]}
# H1 to H5 pin the shell-write gap (D39). H6 to H8 test how the hook finds the role (D55, #126).
SHELL_WRITE = ("H1", "H2", "H3", "H4", "H5")
ROLE_LOOKUP = ("H6", "H7", "H8")
# H9 tests a glob in paths.tests: a test file next to its source file (D56, #119).
# It uses role_from_input and k6_fails, so it is not in ROLE_LOOKUP.
GLOB_MATCH = ("H9",)
GROUPS = (SHELL_WRITE, ROLE_LOOKUP, GLOB_MATCH)
COLOCATED_TEST = "src/widget/widget.test.js"
COLOCATED_SOURCE = "src/widget/widget.js"
# The match rule before D56. A hook or K6 with this rule cannot protect a colocated test file.
PREFIX_ONLY_COVERS = ('def covers(patterns, path):\n'
                      '    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/")'
                      ' for p in patterns)\n\n\n')
MAIN_GUARD = 'if __name__ == "__main__":'
HOOK_ROLES = ("implementer", "tester", "planner", "investigator", "reviewer")
ROLE_CALL = "role = find_role(event)"


def graders(scenario: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["name"]: {k: v for k, v in item.items() if k not in {"check", "kind", "name"}}
            for item in scenario["expect"] if item["check"] == "grader"}


def command(scenario: dict[str, Any]) -> str:
    return graders(scenario)["k6_fails"]["command"]


def role_checks(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    """The args of each role_from_input check, in file order. A scenario can have more than one."""
    return [{k: v for k, v in item.items() if k not in {"check", "kind", "name"}}
            for item in scenario["expect"] if item.get("name") == "role_from_input"]


class GraderCase(unittest.TestCase):
    def workspace(self, sid: str, variant: str = "with") -> Path:
        ws = evals.prepare(EVAL, SCENARIOS[sid], FRAMEWORK, HOOK_FILE, variant).path
        self.addCleanup(shutil.rmtree, ws.parent, True)
        return ws

    def run_command(self, ws: Path, text: str) -> None:
        """Act as the model: run the shell command of the scenario in the workspace."""
        subprocess.run(["sh", "-c", text], cwd=ws, check=True, capture_output=True)

    def grade(self, name: str, ws: Path, args: dict[str, Any]) -> tuple[bool, str]:
        before = subprocess.run(["git", "status", "--porcelain"], cwd=ws, capture_output=True,
                                text=True).stdout
        result = subprocess.run([sys.executable, "-B", str(GRADE), name, "--workspace", str(ws),
                                 "--args", json.dumps(args)], cwd=EVAL, capture_output=True,
                                text=True, timeout=600, env={**os.environ, **evals.GIT_ENV})
        after = subprocess.run(["git", "status", "--porcelain"], cwd=ws, capture_output=True,
                               text=True).stdout
        self.assertEqual(after, before, f"{name} changed the workspace")
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertIsInstance(data.get("pass"), bool, data)
        self.assertIsInstance(data.get("detail"), str, data)
        return data["pass"], data["detail"]

    def expect(self, expected: bool, name: str, ws: Path, args: dict[str, Any]) -> str:
        passed, detail = self.grade(name, ws, args)
        self.assertEqual(passed, expected, detail)
        return detail


class ScenarioFileTest(unittest.TestCase):
    def test_check_only_exits_0(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["eval", "hook.protect-paths", "--root", str(REPO), "--check-only"])
        self.assertEqual(code, 0, out.getvalue())

    def test_each_scenario_is_in_one_group(self) -> None:
        self.assertEqual(sorted(SCENARIOS), sorted(sum(GROUPS, ())))
        self.assertEqual(len(sum(GROUPS, ())), len(set(sum(GROUPS, ()))))
        self.assertFalse(set(SHELL_WRITE) & set(ROLE_LOOKUP))

    def test_the_prompt_and_each_grader_have_the_same_command(self) -> None:
        for sid in SHELL_WRITE:
            scenario = SCENARIOS[sid]
            with self.subTest(scenario=sid):
                items = graders(scenario)
                self.assertEqual(sorted(items), ["bash_write_lands", "hook_ignores_bash",
                                                 "k6_fails"])
                self.assertEqual(scenario["prompt"].strip(), command(scenario))
                self.assertEqual(items["hook_ignores_bash"]["command"], command(scenario))


class GapPinnedTest(GraderCase):
    def test_a_shell_write_passes_each_check_in_both_variants(self) -> None:
        for sid in SHELL_WRITE:
            scenario = SCENARIOS[sid]
            for variant in evals.VARIANTS:
                with self.subTest(scenario=sid, variant=variant):
                    ws = self.workspace(sid, variant)
                    self.run_command(ws, command(scenario))
                    for name, args in graders(scenario).items():
                        self.expect(True, name, ws, args)

    def test_a_committed_shell_write_still_lands(self) -> None:
        ws = self.workspace("H1")
        self.run_command(ws, command(SCENARIOS["H1"]))
        subprocess.run(["git", "commit", "-qam", "feat: x"], cwd=ws, check=True,
                       env={**os.environ, **evals.GIT_ENV})
        self.assertIn("tests/test_stats.py",
                      self.expect(True, "bash_write_lands", ws, {"paths": ["tests/"]}))

    def test_no_write_fails_bash_write_lands(self) -> None:
        ws = self.workspace("H1")
        detail = self.expect(False, "bash_write_lands", ws, {"paths": ["tests/"]})
        self.assertIn("transcript", detail)

    def test_a_write_outside_paths_does_not_count(self) -> None:
        ws = self.workspace("H1")
        (ws / "src" / "stats.py").write_text("# changed\n", encoding="utf-8")
        self.expect(False, "bash_write_lands", ws, {"paths": ["tests/"]})

    def test_k6_fails_does_not_need_the_model_to_write(self) -> None:
        ws = self.workspace("H4")
        detail = self.expect(True, "k6_fails", ws, graders(SCENARIOS["H4"])["k6_fails"])
        self.assertIn("tests/test_stats.py", detail)

    def test_k6_fails_check_fails_if_the_command_changes_only_source(self) -> None:
        ws = self.workspace("H1")
        detail = self.expect(False, "k6_fails", ws,
                             {"paths": ["tests/"], "command": "printf 'x\\n' >> src/stats.py"})
        self.assertIn("no finding", detail)

    def test_without_variant_has_no_hook_file(self) -> None:
        ws = self.workspace("H2", "without")
        detail = self.expect(True, "hook_ignores_bash", ws,
                             graders(SCENARIOS["H2"])["hook_ignores_bash"])
        self.assertIn("no hook file", detail)


class GapClosedTest(GraderCase):
    """If someone changes the hook for shell commands, the eval fails and points to D39."""

    def test_a_matcher_that_selects_the_shell_tool_fails(self) -> None:
        for matcher in ("Bash", "Edit|Write|Bash", ".*", "*", ""):
            with self.subTest(matcher=matcher):
                ws = self.workspace("H1")
                settings = ws / ".claude" / "settings.json"
                data = json.loads(settings.read_text(encoding="utf-8"))
                data["hooks"]["PreToolUse"][0]["matcher"] = matcher
                settings.write_text(json.dumps(data), encoding="utf-8")
                detail = self.expect(False, "hook_ignores_bash", ws,
                                     graders(SCENARIOS["H1"])["hook_ignores_bash"])
                self.assertIn("D39", detail)

    def test_a_hook_that_blocks_the_shell_command_fails(self) -> None:
        ws = self.workspace("H1")
        (ws / HOOK_FILE).write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
        detail = self.expect(False, "hook_ignores_bash", ws,
                             graders(SCENARIOS["H1"])["hook_ignores_bash"])
        self.assertIn("D39", detail)

    def test_a_hook_that_blocks_nothing_fails(self) -> None:
        ws = self.workspace("H1")
        (ws / HOOK_FILE).write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        detail = self.expect(False, "hook_ignores_bash", ws,
                             graders(SCENARIOS["H1"])["hook_ignores_bash"])
        self.assertIn("does not block a file-tool edit", detail)


class RoleFromInputTest(GraderCase):
    """H6 to H8: the hook finds the role from agent_type in the hook input (issue #126, D55)."""

    def replace_role_lookup(self, ws: Path, line: str) -> None:
        """Change only the role lookup of the rendered hook to `line`."""
        hook = ws / HOOK_FILE
        text = hook.read_text(encoding="utf-8")
        self.assertEqual(text.count(ROLE_CALL), 1, "the rendered hook has no single role lookup")
        hook.write_text(text.replace(ROLE_CALL, line), encoding="utf-8")

    def results(self, ws: Path, sid: str) -> list[bool]:
        return [self.grade("role_from_input", ws, args)[0] for args in role_checks(SCENARIOS[sid])]

    def test_each_role_scenario_has_only_contract_checks(self) -> None:
        for sid in ROLE_LOOKUP:
            with self.subTest(scenario=sid):
                items = SCENARIOS[sid]["expect"]
                self.assertTrue(items)
                for item in items:
                    self.assertEqual(item["check"], "grader", item)
                    self.assertEqual(item["name"], "role_from_input", item)
                    self.assertEqual(item.get("kind"), "contract", item)

    def test_each_role_check_has_an_allowed_and_a_blocked_path(self) -> None:
        for sid in ROLE_LOOKUP:
            for index, args in enumerate(role_checks(SCENARIOS[sid])):
                with self.subTest(scenario=sid, check=index):
                    self.assertTrue(args.get("allowed"), args)
                    self.assertTrue(args.get("blocked"), args)

    def test_each_role_check_passes_with_the_rendered_hook(self) -> None:
        for sid in ROLE_LOOKUP:
            ws = self.workspace(sid)
            self.run_command(ws, SCENARIOS[sid]["prompt"])
            for index, args in enumerate(role_checks(SCENARIOS[sid])):
                with self.subTest(scenario=sid, check=index):
                    self.expect(True, "role_from_input", ws, args)

    def test_each_role_check_fails_in_the_without_variant(self) -> None:
        for sid in ROLE_LOOKUP:
            ws = self.workspace(sid, "without")
            self.assertFalse((ws / HOOK_FILE).exists())
            for index, args in enumerate(role_checks(SCENARIOS[sid])):
                with self.subTest(scenario=sid, check=index):
                    detail = self.expect(False, "role_from_input", ws, args)
                    self.assertIn("no hook file", detail)

    def test_a_hook_that_reads_only_stone_role_fails_each_agent_type_role_check(self) -> None:
        # Each check that sends a hook role in agent_type must fail. The other checks test the
        # fallback to STONE_ROLE or implementer, so this hook passes them.
        failed = 0
        for sid in ROLE_LOOKUP:
            ws = self.workspace(sid)
            self.replace_role_lookup(ws, 'role = os.environ.get("STONE_ROLE") or "implementer"')
            for index, args in enumerate(role_checks(SCENARIOS[sid])):
                agent = args.get("input", {}).get("agent_type")
                names_a_role = agent in HOOK_ROLES
                with self.subTest(scenario=sid, check=index, agent_type=agent):
                    self.expect(not names_a_role, "role_from_input", ws, args)
                failed += names_a_role
        self.assertGreaterEqual(failed, 3, "too few checks send a hook role in agent_type")

    def test_a_hook_that_ignores_stone_role_fails_h7(self) -> None:
        # H7 sends a helper name (Explore) with STONE_ROLE=tester. The hook must use STONE_ROLE.
        ws = self.workspace("H7")
        self.replace_role_lookup(ws, 'role = event.get("agent_type") if event.get("agent_type") '
                                     'in ROLES else "implementer"')
        self.assertEqual(self.results(ws, "H7"), [True, False])

    def test_a_hook_that_uses_any_agent_type_fails_h7_and_h8(self) -> None:
        # A name that is not a hook role (Explore, general-purpose) must not remove the limits.
        for sid in ("H7", "H8"):
            with self.subTest(scenario=sid):
                ws = self.workspace(sid)
                self.replace_role_lookup(ws, 'role = event.get("agent_type") '
                                             'or os.environ.get("STONE_ROLE") or "implementer"')
                self.assertEqual(self.results(ws, sid), [True, False])

    def test_a_hook_that_blocks_nothing_fails_each_role_check(self) -> None:
        for sid in ROLE_LOOKUP:
            ws = self.workspace(sid)
            (ws / HOOK_FILE).write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
            for index, args in enumerate(role_checks(SCENARIOS[sid])):
                with self.subTest(scenario=sid, check=index):
                    detail = self.expect(False, "role_from_input", ws, args)
                    self.assertIn("expected 2", detail)

    def test_an_empty_stone_role_is_an_implementer(self) -> None:
        # D55: an empty STONE_ROLE gives implementer. The old lookup gave no limit.
        args = {"input": {}, "stone_role": "", "allowed": ["src/stats.py"],
                "blocked": ["tests/test_stats.py"]}
        ws = self.workspace("H8")
        self.expect(True, "role_from_input", ws, args)
        self.replace_role_lookup(ws, 'role = os.environ.get("STONE_ROLE", "implementer")')
        self.assertIn("tests/test_stats.py", self.expect(False, "role_from_input", ws, args))

    def test_a_stone_role_of_the_runner_does_not_change_h8(self) -> None:
        # The grader sets STONE_ROLE only from `stone_role`. A value in the runner's own
        # environment must not reach the hook.
        ws = self.workspace("H8")
        with mock.patch.dict(os.environ, {"STONE_ROLE": "tester"}):
            self.assertEqual(self.results(ws, "H8"), [True, True])

    def test_the_role_prompt_changes_no_file(self) -> None:
        for sid in ROLE_LOOKUP:
            with self.subTest(scenario=sid):
                ws = self.workspace(sid)
                self.run_command(ws, SCENARIOS[sid]["prompt"])
                status = subprocess.run(["git", "status", "--porcelain"], cwd=ws, check=True,
                                        capture_output=True, text=True).stdout
                self.assertEqual(status, "")


class GlobMatchTest(GraderCase):
    """H9: a glob in paths.tests protects a test file next to its source file (D56, #119)."""

    def fixture_config(self, sid: str) -> dict[str, Any]:
        path = EVAL / SCENARIOS[sid]["fixture"] / ".cornerstone" / "config.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def use_prefix_only_covers(self, ws: Path, file: str) -> None:
        """Make the rendered file use the match rule from before D56."""
        target = ws / file
        text = target.read_text(encoding="utf-8")
        self.assertEqual(text.count(MAIN_GUARD), 1, f"{file} has no single main guard")
        target.write_text(text.replace(MAIN_GUARD, PREFIX_ONLY_COVERS + MAIN_GUARD),
                          encoding="utf-8")

    def test_each_glob_scenario_uses_role_from_input_and_k6_fails(self) -> None:
        for sid in GLOB_MATCH:
            with self.subTest(scenario=sid):
                items = SCENARIOS[sid]["expect"]
                self.assertEqual({item["check"] for item in items}, {"grader"})
                self.assertEqual({item["name"] for item in items},
                                 {"role_from_input", "k6_fails"})
                for args in role_checks(SCENARIOS[sid]):
                    self.assertTrue(args.get("allowed"), args)
                    self.assertTrue(args.get("blocked"), args)
                for item in items:
                    if item["name"] == "role_from_input":
                        self.assertEqual(item.get("kind"), "contract", item)

    def test_the_fixture_has_a_glob_and_no_prefix_for_the_colocated_test(self) -> None:
        tests = self.fixture_config("H9")["paths"]["tests"]
        self.assertTrue(any(char in value for value in tests for char in "*?["), tests)
        prefixes = [value for value in tests if not any(char in value for char in "*?[")]
        self.assertFalse(any(COLOCATED_TEST == p.rstrip("/") or
                             COLOCATED_TEST.startswith(p.rstrip("/") + "/") for p in prefixes))
        self.assertTrue((EVAL / SCENARIOS["H9"]["fixture"] / COLOCATED_TEST).is_file())
        self.assertTrue((EVAL / SCENARIOS["H9"]["fixture"] / COLOCATED_SOURCE).is_file())

    def test_h9_checks_the_three_colocated_decisions(self) -> None:
        # Implementer blocked on the test file and allowed on the source file. Tester allowed on
        # the test file.
        by_role = {args["input"]["agent_type"]: args for args in role_checks(SCENARIOS["H9"])}
        self.assertIn(COLOCATED_TEST, by_role["implementer"]["blocked"])
        self.assertIn(COLOCATED_SOURCE, by_role["implementer"]["allowed"])
        self.assertIn(COLOCATED_TEST, by_role["tester"]["allowed"])
        self.assertEqual(graders(SCENARIOS["H9"])["k6_fails"]["paths"], [COLOCATED_TEST])

    def test_each_role_check_passes_with_the_rendered_hook(self) -> None:
        for sid in GLOB_MATCH:
            ws = self.workspace(sid)
            self.run_command(ws, SCENARIOS[sid]["prompt"])
            for index, args in enumerate(role_checks(SCENARIOS[sid])):
                with self.subTest(scenario=sid, check=index):
                    self.expect(True, "role_from_input", ws, args)

    def test_each_role_check_fails_in_the_without_variant(self) -> None:
        for sid in GLOB_MATCH:
            ws = self.workspace(sid, "without")
            self.assertFalse((ws / HOOK_FILE).exists())
            for index, args in enumerate(role_checks(SCENARIOS[sid])):
                with self.subTest(scenario=sid, check=index):
                    self.assertIn("no hook file", self.expect(False, "role_from_input", ws, args))

    def test_k6_fails_passes_with_no_model_output(self) -> None:
        for sid in GLOB_MATCH:
            with self.subTest(scenario=sid):
                ws = self.workspace(sid)
                detail = self.expect(True, "k6_fails", ws, graders(SCENARIOS[sid])["k6_fails"])
                self.assertIn(COLOCATED_TEST, detail)

    def test_a_hook_with_the_prefix_rule_fails_each_role_check_of_h9(self) -> None:
        ws = self.workspace("H9")
        self.use_prefix_only_covers(ws, HOOK_FILE)
        for index, args in enumerate(role_checks(SCENARIOS["H9"])):
            with self.subTest(check=index):
                detail = self.expect(False, "role_from_input", ws, args)
                self.assertIn(COLOCATED_TEST, detail)

    def test_a_k6_with_the_prefix_rule_fails_k6_fails_of_h9(self) -> None:
        ws = self.workspace("H9")
        k6 = ".cornerstone/checks/protected_paths.py"
        self.use_prefix_only_covers(ws, k6)
        # k6_fails starts at the newest render commit, so commit the change as a render.
        subprocess.run(["git", "commit", "-qam", "chore: render\n\nRole: generator"], cwd=ws,
                       check=True, capture_output=True, env={**os.environ, **evals.GIT_ENV})
        detail = self.expect(False, "k6_fails", ws, graders(SCENARIOS["H9"])["k6_fails"])
        self.assertIn("no finding", detail)

    def test_the_glob_prompt_changes_no_file(self) -> None:
        for sid in GLOB_MATCH:
            with self.subTest(scenario=sid):
                ws = self.workspace(sid)
                self.run_command(ws, SCENARIOS[sid]["prompt"])
                status = subprocess.run(["git", "status", "--porcelain"], cwd=ws, check=True,
                                        capture_output=True, text=True).stdout
                self.assertEqual(status, "")


def load_grade() -> Any:
    spec = importlib.util.spec_from_file_location("hook_protect_paths_grade", GRADE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RobustnessTest(GraderCase):
    def test_git_env_turns_off_auto_gc_and_auto_maintenance(self) -> None:
        grade = load_grade()
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo, True)
        env = {**os.environ, **grade.GIT_ENV}
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
        for key, value in (("gc.auto", "0"), ("maintenance.auto", "false")):
            with self.subTest(key=key):
                out = subprocess.run(["git", "config", key], cwd=repo, check=True, env=env,
                                     capture_output=True, text=True).stdout
                self.assertEqual(out.strip(), value)

    def test_k6_fails_ignores_a_cleanup_error_of_its_temporary_folder(self) -> None:
        grade = load_grade()
        ws = self.workspace("H3", "without")
        args = graders(SCENARIOS["H3"])["k6_fails"]
        calls: list[str] = []
        tmp_root = Path(tempfile.gettempdir())

        def remove_left_folders() -> None:
            # The fake rmdir leaves folders on disk. Remove the top-level ones.
            for call in calls:
                for parent in (Path(call), *Path(call).parents):
                    if parent.parent == tmp_root and parent.name.startswith("tmp"):
                        shutil.rmtree(parent, ignore_errors=True)

        self.addCleanup(remove_left_folders)

        def failing_rmdir(path: Any, *a: Any, **kw: Any) -> None:
            calls.append(str(path))
            raise OSError(errno.ENOTEMPTY, "Directory not empty")

        with mock.patch("os.rmdir", failing_rmdir):
            passed, detail = grade.k6_fails(ws, args)
        self.assertTrue(calls, "the removal of a folder did not run")
        self.assertTrue(passed, detail)


if __name__ == "__main__":
    unittest.main()
