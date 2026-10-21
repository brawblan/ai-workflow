"""Tests for the hook.protect-paths eval in evals/hook-protect-paths/ (D39).

Each test makes a workspace with the runner's own setup (`evals.prepare`): the fixture, the render
commit, and the "without" variant if a test asks for it. Then it runs grade.py as a subprocess, as
`stone eval` does. No model or harness starts. A test runs the shell command of a scenario itself
when it must act as the model.
"""

from __future__ import annotations

import contextlib
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


def graders(scenario: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["name"]: {k: v for k, v in item.items() if k not in {"check", "kind", "name"}}
            for item in scenario["expect"] if item["check"] == "grader"}


def command(scenario: dict[str, Any]) -> str:
    return graders(scenario)["k6_fails"]["command"]


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

    def test_the_prompt_and_each_grader_have_the_same_command(self) -> None:
        for sid, scenario in SCENARIOS.items():
            with self.subTest(scenario=sid):
                items = graders(scenario)
                self.assertEqual(sorted(items), ["bash_write_lands", "hook_ignores_bash",
                                                 "k6_fails"])
                self.assertEqual(scenario["prompt"].strip(), command(scenario))
                self.assertEqual(items["hook_ignores_bash"]["command"], command(scenario))


class GapPinnedTest(GraderCase):
    def test_a_shell_write_passes_each_check_in_both_variants(self) -> None:
        for sid, scenario in SCENARIOS.items():
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
        real_rmtree = shutil.rmtree
        calls: list[str] = []

        def failing_rmtree(path: Any, *a: Any, **kw: Any) -> None:
            if Path(path).name.startswith("tmp"):
                calls.append(str(path))
                real_rmtree(path, ignore_errors=True)  # keep the machine clean
                # Like the real rmtree: it reports the error to the handler of tempfile.
                error = OSError(39, "Directory not empty")
                try:
                    raise error
                except OSError:
                    if "onexc" in kw:
                        kw["onexc"](os.rmdir, str(path), error)
                    else:
                        kw["onerror"](os.rmdir, str(path), sys.exc_info())
                return
            real_rmtree(path, *a, **kw)

        with mock.patch("shutil.rmtree", failing_rmtree):
            passed, detail = grade.k6_fails(ws, args)
        self.assertTrue(calls, "the cleanup of the temporary folder did not run")
        self.assertTrue(passed, detail)


if __name__ == "__main__":
    unittest.main()
