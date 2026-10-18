"""Tests for `stone eval`, the component eval runner (roadmap item 4a, D23).

Each test builds a repo in a temp folder and uses the real framework of this repo. No real model or
harness starts: the run config names a fake harness, a small Python script. The fake harness records
each call (argv, environment, working directory, standard input, files, git log) and does the
actions that the test plans for it.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

import yaml

from stone import cli

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
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
COMPONENT = "role.tester"
EVAL_DIR = "evals/role-tester"
ROLE_FILE = ".claude/agents/tester.md"
OTHER_ROLE_FILE = ".claude/agents/reviewer.md"
CHANGE_DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1,2 @@
 VALUE = 1
+CHANGED = True
"""
VALID_DELTA = ("## ADDED export.R1: A title\n\nThe user MUST do it.\n\n### Scenario: it works\n"
               "- WHEN the user does it\n- THEN it is done\n")
INVALID_DELTA = "## CHANGED nothing\n\nNo valid heading.\n"


def result_line(report: str = "done", cost: float = 0.1, tokens: int = 5) -> str:
    return json.dumps({"type": "result", "result": report, "total_cost_usd": cost,
                       "usage": {"output_tokens": tokens, "input_tokens": 1}, "num_turns": 2})


FAKE_HARNESS = r'''
"""Fake harness for the stone eval tests. It records each call, then does the planned actions."""
import json, os, signal, subprocess, sys, time
from pathlib import Path

variant, argv = sys.argv[1], sys.argv[2:]
state = Path(os.environ["FAKE_STATE"])
plan = json.loads((state / "plan.json").read_text(encoding="utf-8"))
counter = state / f"count-{variant}"
number = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(number + 1))
steps = plan.get(variant) or [{}]
step = steps[min(number, len(steps) - 1)]
cwd = Path.cwd()
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "fake", "GIT_AUTHOR_EMAIL": "fake@example.invalid",
           "GIT_COMMITTER_NAME": "fake", "GIT_COMMITTER_EMAIL": "fake@example.invalid"}


def git(*args):
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True,
                          check=True).stdout


def git_try(*args):
    """Like git, but give "" if the command fails (for example, no branch with that name)."""
    result = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


try:
    stat = os.fstat(0)
    stdin = "devnull" if os.path.samestat(stat, os.stat(os.devnull)) else "other"
except OSError:
    stdin = "closed"
stdin_text = ""
if stdin == "other" and not os.isatty(0):
    stdin_text = sys.stdin.read()
files = sorted(p.relative_to(cwd).as_posix() for p in cwd.rglob("*")
               if p.is_file() and ".git" not in p.relative_to(cwd).parts)
record = {"variant": variant, "number": number, "argv": argv, "cwd": str(cwd),
          "env": {k: v for k, v in os.environ.items() if k.startswith("FAKE_") and k != "FAKE_STATE"},
          "stdin": stdin, "stdin_text": stdin_text, "files": files,
          "is_git_root": (cwd / ".git").exists(),
          "log": git("log", "--format=%B%x1e"),
          "status": git("status", "--porcelain", "--untracked-files=all"),
          "tracked": git("ls-files", "-z").split("\0"),
          "branch": git_try("symbolic-ref", "-q", "--short", "HEAD").strip(),
          "main_log": git_try("log", "main", "--format=%H%x1f%B%x1e"),
          "head_log": git("log", "--format=%H%x1f%B%x1e"),
          "main_files": git_try("ls-tree", "-r", "--name-only", "main").splitlines(),
          "texts": {n: (cwd / n).read_text(encoding="utf-8") for n in plan.get("read", [])
                    if (cwd / n).is_file()}}
with (state / "calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\n")

for action in step.get("actions", []):
    if action[0] == "write":
        target = cwd / action[1]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(action[2], encoding="utf-8")
    elif action[0] == "add":
        git("add", *action[1:])
    elif action[0] == "commit":
        git("commit", "-q", "-m", action[1])
    elif action[0] == "mv":
        (cwd / action[2]).parent.mkdir(parents=True, exist_ok=True)
        git("mv", action[1], action[2])
    elif action[0] == "spawn":  # a child process that writes a file after a delay
        code = (f"import pathlib, time; time.sleep({action[2]}); "
                f"pathlib.Path({action[1]!r}).write_text('late')")
        subprocess.Popen([sys.executable, "-c", code])
    elif action[0] == "kill_parent":  # stop the stone process that started this harness
        os.kill(os.getppid(), signal.SIGKILL)
        time.sleep(1)
print(f"TRANSCRIPT {variant} {number}")
sys.stdout.flush()
if step.get("raw_stdout"):
    sys.stdout.buffer.write(bytes.fromhex(step["raw_stdout"]))
    sys.stdout.buffer.flush()
for line in step.get("stdout", [plan["default_result"]]):
    print(line)
sys.stdout.flush()
for line in step.get("stderr", []):
    print(line, file=sys.stderr)
if step.get("raw_stderr"):
    sys.stderr.buffer.write(bytes.fromhex(step["raw_stderr"]))
sys.stderr.flush()
if step.get("sleep"):
    time.sleep(step["sleep"])
sys.exit(step.get("exit", 0))
'''

GRADER = r'''
import argparse, json, sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("name")
parser.add_argument("--workspace", required=True)
parser.add_argument("--args", required=True)
options = parser.parse_args()
args = json.loads(options.args)
workspace = Path(options.workspace)
if options.name == "pass":
    print("some log text")
    print(json.dumps({"pass": True, "detail": "ok"}))
elif options.name == "fail":
    print(json.dumps({"pass": False}))
elif options.name == "crash":
    raise RuntimeError("the grader crashed")
elif options.name == "bad_output":
    print("this is not JSON")
elif options.name == "silent":
    pass
elif options.name == "not_last":
    print(json.dumps({"pass": True}))
    print("a line after the JSON")
elif options.name == "uses_args":
    ok = (workspace / args["file"]).is_file() and args.get("min") == 2
    print(json.dumps({"pass": ok}))
elif options.name == "literal":
    print(json.dumps({"pass": args["value"]}))
'''


class EvalTestCase(unittest.TestCase):
    """A repo in a temp folder with an eval folder, a fixture, a fake harness, and a run config."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.base = Path(self.folder.name)
        self.root = self.base / "repo"
        self.state = self.base / "state"
        self.state.mkdir()
        self.write(".cornerstone/config.yaml", CONFIG)
        self.eval_dir = self.root / EVAL_DIR
        self.write(f"{EVAL_DIR}/fixtures/basic/src/app.py", "VALUE = 1\n")
        self.write(f"{EVAL_DIR}/fixtures/basic/b/keep.txt", "keep b\n")
        self.write(f"{EVAL_DIR}/fixtures/basic/c/keep.txt", "keep c\n")
        self.write(f"{EVAL_DIR}/fixtures/basic.diff", CHANGE_DIFF)
        self.write(f"{EVAL_DIR}/fixtures/rendered/src/app.py", "VALUE = 1\n")
        self.write(f"{EVAL_DIR}/fixtures/rendered/.cornerstone/config.yaml", CONFIG)
        self.fake = self.base / "fake_harness.py"
        self.fake.write_text(FAKE_HARNESS, encoding="utf-8")
        self.run_yaml = self.base / "run.yaml"
        self.write_run_config()
        self.plan({})

    def tearDown(self) -> None:
        self.folder.cleanup()

    # Helpers ---------------------------------------------------------------------------------

    def write(self, path: str, text: str) -> Path:
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")
        return full

    def fake_cmd(self, variant: str) -> list[str]:
        return [sys.executable, str(self.fake), variant, "--role", "$role", "--model", "$model",
                "--budget", "$budget", "--tools", "$tools", "--prompt", "$prompt"]

    def run_config(self, run: dict | None = None, env: dict | None = None,
                   tools: dict | None = None, output: dict | None = None,
                   output_where: Any = None) -> dict:
        env = env if env is not None else {
            "with": {"FAKE_ROLE": "$role", "FAKE_MODEL": "$model"},
            "without": {"FAKE_ROLE": "without-$role"}}
        env = {variant: {"FAKE_STATE": str(self.state), **(env.get(variant) or {})}
               for variant in ("with", "without")}
        config = {
            "run": {"with": self.fake_cmd("with"), "without": self.fake_cmd("without"),
                    **(run or {})},
            "env": env,
            "tools": tools if tools is not None else {"tester": ["Read", "Bash(git log*)"]},
            "output": output if output is not None else {
                "report": "result", "cost_usd": "total_cost_usd",
                "output_tokens": "usage.output_tokens", "input_tokens": "usage.input_tokens",
                "turns": "num_turns"},
        }
        if output_where is not None:
            config["output_where"] = output_where
        return config

    def write_run_config(self, path: Path | None = None, **kwargs: Any) -> None:
        (path or self.run_yaml).write_text(yaml.safe_dump(self.run_config(**kwargs)),
                                           encoding="utf-8")

    def plan(self, plan: dict) -> None:
        plan = {"default_result": result_line(), **plan}
        (self.state / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    def scenario(self, sid: str = "T1", fixture: str = "fixtures/basic",
                 expect: list | None = None, **extra: Any) -> dict:
        return {"id": sid, "fixture": fixture, "prompt": f"Do the job for {sid}.",
                "expect": expect or [{"check": "file_exists", "path": "src/app.py"}], **extra}

    def scenarios(self, *items: dict, task: str | None = "Write tests for this ticket.",
                  **top: Any) -> None:
        data: dict[str, Any] = {"component": COMPONENT, "role": "tester"}
        if task is not None:
            data["task"] = task
        data["scenarios"] = list(items) or [self.scenario()]
        data.update(top)
        self.write_yaml(data)

    def write_yaml(self, data: dict) -> None:
        self.write(f"{EVAL_DIR}/scenarios.yaml", yaml.safe_dump(data, sort_keys=False))

    def grader(self) -> None:
        self.write(f"{EVAL_DIR}/grade.py", GRADER)

    def copy_framework(self) -> Path:
        copy = self.base / "framework"
        shutil.copytree(FRAMEWORK, copy)
        return copy

    def eval(self, *args: str, framework: Path | None = None,
             run_config: bool = True) -> tuple[int, str]:
        argv = ["eval", COMPONENT, "--root", str(self.root),
                "--framework", str(framework or FRAMEWORK)]
        if run_config:
            argv += ["--run-config", str(self.run_yaml)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(argv + list(args))
        return code, out.getvalue()

    def calls(self) -> list[dict]:
        log = self.state / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def runs_folder(self) -> Path:
        folders = list((self.root / ".cornerstone/eval-runs").iterdir())
        self.assertEqual(len(folders), 1, folders)
        return folders[0]

    def runs(self) -> list[dict]:
        text = (self.runs_folder() / "runs.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def check_passes(self, run: dict) -> list[bool]:
        return [check["pass"] for check in run["checks"]]

    def table(self) -> tuple[str, dict[tuple[str, str], dict[str, str]]]:
        files = list((self.root / "evals/results").glob("*.md"))
        self.assertEqual(len(files), 1, files)
        text = files[0].read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if line.startswith("|")]
        header = [cell.strip().lower() for cell in lines[0].strip().strip("|").split("|")]
        rows = {}
        for line in lines[2:]:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            rows[(cells[0], cells[1])] = dict(zip(header, cells))
        return text, rows

    @staticmethod
    def col(row: dict[str, str], word: str) -> str:
        return next(value for key, value in row.items() if word in key)

    def reset_records(self) -> None:
        """Remove the records of an earlier eval in the same test: runs, results, and calls."""
        shutil.rmtree(self.root / ".cornerstone/eval-runs", ignore_errors=True)
        shutil.rmtree(self.root / "evals/results", ignore_errors=True)
        for path in self.state.iterdir():
            if path.name != "plan.json":
                path.unlink()

    def no_run_started(self) -> None:
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.root / ".cornerstone/eval-runs").exists())
        self.assertFalse((self.root / "evals/results").exists())

    def grade_once(self, expect: list, actions: list | None = None,
                   stdout: list[str] | None = None, **extra: Any) -> list[bool]:
        """Run one scenario with the `with` variant. Return the pass value of each check."""
        step: dict[str, Any] = {"actions": actions or []}
        if stdout is not None:
            step["stdout"] = stdout
        self.plan({"with": [step]})
        self.scenarios(self.scenario(expect=expect, **extra))
        self.eval("--variant", "with")
        runs = self.runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(runs[0]["checks"]), len(expect))
        return self.check_passes(runs[0])


def arg(call: dict, flag: str) -> str:
    argv = call["argv"]
    return argv[argv.index(flag) + 1]


# AC1, AC3: find the component and check only -------------------------------------------------


class CheckOnlyTest(EvalTestCase):
    def test_ac1_check_only_valid_file_exits_0_lists_runs_and_starts_no_run(self) -> None:
        self.scenarios(self.scenario("T1"), self.scenario("T2"))
        code, out = self.eval("--check-only", "--trials", "2")
        self.assertEqual(code, 0, out)
        self.assertIn("T1", out)
        self.assertIn("T2", out)
        self.no_run_started()

    def test_ac1_eval_folder_comes_from_the_component_eval_field(self) -> None:
        framework = self.copy_framework()
        components = framework / "adapters/claude-code/components.yaml"
        text = components.read_text(encoding="utf-8")
        self.assertEqual(text.count("eval: evals/role-tester/"), 1)
        components.write_text(text.replace("eval: evals/role-tester/", "eval: evals/elsewhere/"),
                              encoding="utf-8")
        self.scenarios()
        shutil.move(str(self.eval_dir), str(self.root / "evals/elsewhere"))
        code, out = self.eval("--check-only", framework=framework)
        self.assertEqual(code, 0, out)

    def test_ac1_eval_folder_with_no_scenarios_file_exits_2(self) -> None:
        code, out = self.eval("--check-only")
        self.assertEqual(code, 2, out)
        self.assertIn("scenarios.yaml", out)

    def test_ac3_unknown_component_exits_2(self) -> None:
        self.scenarios()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["eval", "role.nobody", "--root", str(self.root), "--framework",
                             str(FRAMEWORK), "--run-config", str(self.run_yaml), "--check-only"])
        self.assertEqual(code, 2, out.getvalue())
        self.assertIn("role.nobody", out.getvalue())

    def test_ac3_component_with_empty_eval_field_exits_2(self) -> None:
        self.scenarios()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["eval", "check.k6", "--root", str(self.root), "--framework",
                             str(FRAMEWORK), "--run-config", str(self.run_yaml)])
        self.assertEqual(code, 2, out.getvalue())
        self.assertEqual(self.calls(), [])


# AC2: validation of scenarios.yaml -------------------------------------------------------------


class ValidationTest(EvalTestCase):
    def assert_invalid(self, data: dict, *words: str) -> str:
        self.write_yaml(data)
        code, out = self.eval("--check-only")
        self.assertEqual(code, 2, out)
        message = out.replace(str(self.eval_dir / "scenarios.yaml"), "<file>")
        for word in words:
            pattern = rf"(?<![\w-]){re.escape(word)}(?![\w-])"
            self.assertRegex(message, re.compile(pattern, re.I), f"'{word}' not named in: {out}")
        self.no_run_started()
        return message

    def valid(self) -> dict:
        return {"component": COMPONENT, "role": "tester", "task": "Write tests.",
                "scenarios": [self.scenario()]}

    def test_ac2_missing_top_level_key_is_named(self) -> None:
        for key in ("component", "role", "scenarios"):
            with self.subTest(key=key):
                data = self.valid()
                del data[key]
                self.assert_invalid(data, key)

    def test_ac2_scenario_missing_key_is_named(self) -> None:
        for key in ("id", "fixture", "prompt", "expect"):
            with self.subTest(key=key):
                data = self.valid()
                del data["scenarios"][0][key]
                self.assert_invalid(data, key)

    def test_ac2_repeated_id_is_named(self) -> None:
        data = self.valid()
        data["scenarios"] = [self.scenario("T7"), self.scenario("T7")]
        self.assert_invalid(data, "T7")

    def test_ac2_fixture_path_that_does_not_exist_is_named(self) -> None:
        data = self.valid()
        data["scenarios"][0]["fixture"] = "fixtures/nothing-here"
        self.assert_invalid(data, "fixtures/nothing-here")

    def test_ac2_change_path_that_does_not_exist_is_named(self) -> None:
        data = self.valid()
        data["scenarios"][0]["change"] = "fixtures/no-such.diff"
        self.assert_invalid(data, "fixtures/no-such.diff")

    def test_ac2_unknown_check_name_is_named(self) -> None:
        data = self.valid()
        data["scenarios"][0]["expect"] = [{"check": "no_such_check", "path": "x"}]
        self.assert_invalid(data, "no_such_check")

    def test_ac2_check_with_no_required_key_names_the_key(self) -> None:
        self.grader()  # so that a grader check fails only for the missing key
        cases = [
            ({"check": "file_exists"}, "path"),
            ({"check": "file_absent"}, "path"),
            ({"check": "unchanged"}, "paths"),
            ({"check": "only_changed"}, "paths"),
            ({"check": "matches", "pattern": "x"}, "path"),
            ({"check": "matches", "path": "x"}, "pattern"),
            ({"check": "sections_in_order", "sections": ["A"]}, "path"),
            ({"check": "sections_in_order", "path": "x"}, "sections"),
            ({"check": "json_valid"}, "path"),
            ({"check": "command"}, "run"),
            ({"check": "commit_trailer"}, "trailer"),
            ({"check": "spec_delta_valid"}, "path"),
            ({"check": "grader"}, "name"),
        ]
        for item, key in cases:
            with self.subTest(check=item["check"], key=key):
                data = self.valid()
                data["scenarios"][0]["expect"] = [item]
                self.assert_invalid(data, item["check"], key)

    def test_ac2_kind_that_is_not_outcome_or_contract_is_named(self) -> None:
        data = self.valid()
        data["scenarios"][0]["expect"] = [{"check": "file_exists", "path": "x",
                                           "kind": "judgment"}]
        self.assert_invalid(data, "judgment")

    def test_ac2_both_valid_kinds_are_accepted(self) -> None:
        data = self.valid()
        data["scenarios"][0]["expect"] = [
            {"check": "file_exists", "path": "x", "kind": "outcome"},
            {"check": "file_exists", "path": "x", "kind": "contract"}]
        self.write_yaml(data)
        code, out = self.eval("--check-only")
        self.assertEqual(code, 0, out)

    def test_ac2_grader_check_without_grade_py_is_named(self) -> None:
        data = self.valid()
        data["scenarios"][0]["expect"] = [{"check": "grader", "name": "pass"}]
        self.assert_invalid(data, "grade.py")

    def test_ac2_grader_check_with_grade_py_is_valid(self) -> None:
        self.grader()
        data = self.valid()
        data["scenarios"][0]["expect"] = [{"check": "grader", "name": "pass"}]
        self.write_yaml(data)
        code, out = self.eval("--check-only")
        self.assertEqual(code, 0, out)

    def test_ac2_one_message_names_each_problem(self) -> None:
        data = {
            "role": "tester",
            "scenarios": [
                {"fixture": "fixtures/basic", "prompt": "p",
                 "expect": [{"check": "file_exists", "path": "x"}]},
                {"id": "T2", "fixture": "fixtures/nothing-here", "prompt": "p",
                 "expect": [{"check": "no_such_check"}]},
                {"id": "T2", "fixture": "fixtures/basic", "prompt": "p",
                 "change": "fixtures/no-such.diff",
                 "expect": [{"check": "matches", "path": "x"},
                            {"check": "grader", "name": "g"},
                            {"check": "file_exists", "path": "x", "kind": "judgment"}]},
                {"id": "T3", "fixture": "fixtures/basic",
                 "expect": [{"check": "file_exists", "path": "x"}]},
            ],
        }
        self.assert_invalid(data, "component", "id", "fixtures/nothing-here", "no_such_check",
                            "T2", "fixtures/no-such.diff", "pattern", "grade.py", "judgment",
                            "prompt")

    def test_ac2_scenario_that_is_not_a_mapping_exits_2(self) -> None:
        data = self.valid()
        data["scenarios"].append("T2 is only a string")
        self.write_yaml(data)
        code, out = self.eval("--check-only")
        self.assertEqual(code, 2, out)
        self.no_run_started()

    def test_ac2_top_level_list_exits_2(self) -> None:
        self.write(f"{EVAL_DIR}/scenarios.yaml", yaml.safe_dump([self.scenario()]))
        code, out = self.eval("--check-only")
        self.assertEqual(code, 2, out)
        self.no_run_started()

    def test_readme_run_config_with_no_argv_list_for_a_variant_exits_2(self) -> None:
        self.scenarios()
        config = self.run_config()
        del config["run"]["without"]
        self.run_yaml.write_text(yaml.safe_dump(config), encoding="utf-8")
        code, out = self.eval()
        self.assertEqual(code, 2, out)
        self.assertIn("run.without", out)
        self.no_run_started()

    def test_readme_run_config_that_is_not_valid_yaml_exits_2(self) -> None:
        self.scenarios()
        self.run_yaml.write_text("run: [with: {\n", encoding="utf-8")
        code, out = self.eval()
        self.assertEqual(code, 2, out)
        self.no_run_started()

    def test_ac2_invalid_file_starts_no_run_without_check_only(self) -> None:
        data = self.valid()
        data["scenarios"][0]["expect"] = [{"check": "no_such_check"}]
        self.write_yaml(data)
        code, out = self.eval()
        self.assertEqual(code, 2, out)
        self.no_run_started()


# AC4: the workspace ------------------------------------------------------------------------------


class WorkspaceTest(EvalTestCase):
    def test_ac4_workspace_is_a_new_git_repo_in_system_temp_not_under_root(self) -> None:
        self.scenarios(self.scenario())
        code, out = self.eval("--trials", "2")
        self.assertEqual(code, 0, out)
        calls = self.calls()
        self.assertEqual(len(calls), 4)
        temp = Path(tempfile.gettempdir()).resolve()
        root = self.root.resolve()
        for call in calls:
            cwd = Path(call["cwd"]).resolve()
            self.assertTrue(cwd.is_relative_to(temp), cwd)
            self.assertFalse(cwd.is_relative_to(root), cwd)
            self.assertTrue(call["is_git_root"])
            self.assertIn("src/app.py", call["files"])
            self.assertIn("b/keep.txt", call["files"])
            self.assertEqual(call["status"], "", "the fixture is committed as the base")
        self.assertEqual(len({call["cwd"] for call in calls}), 4, "a new repo for each run")

    def test_ac4_with_has_the_role_file_and_without_does_not(self) -> None:
        self.scenarios(self.scenario(fixture="fixtures/rendered"))
        code, out = self.eval()
        self.assertEqual(code, 0, out)
        calls = {call["variant"]: call for call in self.calls()}
        self.assertIn(ROLE_FILE, calls["with"]["files"])
        self.assertNotIn(ROLE_FILE, calls["without"]["files"])
        for variant in ("with", "without"):
            with self.subTest(variant=variant):
                self.assertIn(OTHER_ROLE_FILE, calls[variant]["files"],
                              "the repo config is rendered in both variants")
                self.assertEqual(calls[variant]["status"], "", "the render is committed")

    def test_ac4_fixture_without_config_is_not_rendered(self) -> None:
        self.scenarios(self.scenario(fixture="fixtures/basic"))
        self.eval("--variant", "with")
        files = self.calls()[0]["files"]
        self.assertFalse([name for name in files if name.startswith(".claude/")], files)

    def test_ac4_change_is_committed_with_implementer_trailer_before_harness(self) -> None:
        self.plan({"read": ["src/app.py"]})
        self.scenarios(self.scenario(change="fixtures/basic.diff"))
        code, out = self.eval("--variant", "with")
        self.assertEqual(code, 0, out)
        call = self.calls()[0]
        self.assertEqual(call["texts"]["src/app.py"], "VALUE = 1\nCHANGED = True\n")
        self.assertEqual(call["status"], "")
        last_commit = call["log"].split("\x1e")[0]
        self.assertIn("Role: implementer", last_commit.splitlines())

    def test_ac4_checks_grade_only_the_changes_after_the_setup(self) -> None:
        expect = [
            {"check": "unchanged", "paths": ["src/"]},
            {"check": "unchanged", "paths": [".claude/", ".cornerstone/"]},
            {"check": "only_changed", "paths": ["tests/"]},
            {"check": "commit_trailer", "trailer": "Role: implementer"},
        ]
        passes = self.grade_once(expect, fixture="fixtures/rendered", change="fixtures/basic.diff")
        self.assertEqual(passes, [True, True, True, False])


# AC5: the run command ----------------------------------------------------------------------------


class CommandTest(EvalTestCase):
    def test_ac5_role_model_budget_and_prompt_are_filled(self) -> None:
        self.scenarios(self.scenario())
        code, out = self.eval("--variant", "with", "--model", "model-x", "--budget", "7")
        self.assertEqual(code, 0, out)
        call = self.calls()[0]
        self.assertEqual(arg(call, "--role"), "tester")
        self.assertEqual(arg(call, "--model"), "model-x")
        self.assertEqual(arg(call, "--budget"), "7")

    def test_ac5_prompt_is_task_blank_line_then_scenario_prompt(self) -> None:
        item = self.scenario()
        item["prompt"] = "Ticket SLUG-1: make a slug."
        self.scenarios(item, task="Write tests for this ticket.")
        self.eval("--variant", "with")
        self.assertEqual(self.calls()[0]["argv"][-1],
                         "Write tests for this ticket.\n\nTicket SLUG-1: make a slug.")

    def test_ac5_tools_argument_becomes_one_argument_for_each_tool(self) -> None:
        self.write_run_config(tools={"tester": ["Read", "Bash(git log*)", "Edit"],
                                     "planner": ["Write"]})
        self.scenarios(self.scenario())
        self.eval()
        for call in self.calls():
            with self.subTest(variant=call["variant"]):
                argv = call["argv"]
                tools = argv[argv.index("--tools") + 1:argv.index("--prompt")]
                self.assertEqual(tools, ["Read", "Bash(git log*)", "Edit"])

    def test_ac5_tools_argument_with_no_list_for_the_role_adds_no_argument(self) -> None:
        self.write_run_config(tools={"planner": ["Write"]})
        self.scenarios(self.scenario())
        self.eval("--variant", "with")
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv.index("--prompt"), argv.index("--tools") + 1)

    def test_ac5_env_of_each_variant_is_filled_and_set(self) -> None:
        self.write_run_config(env={"with": {"FAKE_ROLE": "$role", "FAKE_MODEL": "$model",
                                            "FAKE_BUDGET": "b-$budget"},
                                   "without": {"FAKE_ROLE": "without-$role"}})
        self.scenarios(self.scenario())
        code, out = self.eval("--model", "model-y", "--budget", "3")
        self.assertEqual(code, 0, out)
        calls = {call["variant"]: call for call in self.calls()}
        self.assertEqual(calls["with"]["env"],
                         {"FAKE_ROLE": "tester", "FAKE_MODEL": "model-y", "FAKE_BUDGET": "b-3"})
        self.assertEqual(calls["without"]["env"], {"FAKE_ROLE": "without-tester"})

    def test_ac5_variants_use_their_own_argv_list(self) -> None:
        self.write_run_config(run={"without": [sys.executable, str(self.fake), "without",
                                               "--only-without", "--prompt", "$prompt"]})
        self.scenarios(self.scenario())
        self.eval()
        calls = {call["variant"]: call for call in self.calls()}
        self.assertIn("--tools", calls["with"]["argv"])
        self.assertNotIn("--only-without", calls["with"]["argv"])
        self.assertEqual(calls["without"]["argv"][0], "--only-without")

    def test_ac5_process_gets_no_stdin_and_runs_in_the_workspace(self) -> None:
        self.plan({"with": [{"actions": [["write", "marker.txt", "x"]]}]})
        self.scenarios(self.scenario(expect=[{"check": "file_exists", "path": "marker.txt"}]))
        read_end, write_end = os.pipe()
        os.write(write_end, b"TEXT FROM THE TEST PROCESS\n")
        os.close(write_end)
        saved = os.dup(0)
        try:
            os.dup2(read_end, 0)
            code, out = self.eval("--variant", "with")
        finally:
            os.dup2(saved, 0)
            os.close(saved)
            os.close(read_end)
        call = self.calls()[0]
        self.assertIn(call["stdin"], ("devnull", "closed"), call)
        self.assertEqual(call["stdin_text"], "")
        self.assertIn("src/app.py", call["files"])
        self.assertEqual(code, 0, "a file that the harness wrote in its cwd is in the workspace")

    def test_ac5_default_run_config_is_the_adapter_eval_yaml(self) -> None:
        framework = self.copy_framework()
        self.write_run_config(path=framework / "adapters/claude-code/eval.yaml")
        self.scenarios(self.scenario())
        code, out = self.eval("--variant", "with", framework=framework, run_config=False)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls()), 1)


# AC6: the harness output ------------------------------------------------------------------------


class OutputTest(EvalTestCase):
    def test_ac6_last_json_object_line_gives_usage_and_report(self) -> None:
        stdout = [
            "starting the run",
            json.dumps({"type": "system", "total_cost_usd": 9.0, "result": "not this one"}),
            json.dumps({"type": "result", "result": "First line\nThe Final REPORT text",
                        "total_cost_usd": 0.25, "num_turns": 3,
                        "usage": {"output_tokens": 42, "input_tokens": 7}}),
            json.dumps([1, 2, 3]),
            "a last line that is not JSON",
        ]
        expect = [
            {"check": "matches", "path": "@report", "pattern": "final report text"},
            {"check": "matches", "path": "@report", "pattern": "^The Final REPORT text$"},
            {"check": "matches", "path": "@report", "pattern": "not this one"},
        ]
        passes = self.grade_once(expect, stdout=stdout)
        self.assertEqual(passes, [True, True, False])
        usage = self.runs()[0]["usage"]
        self.assertEqual(usage["cost_usd"], 0.25)
        self.assertEqual(usage["output_tokens"], 42)
        self.assertEqual(usage["input_tokens"], 7)
        self.assertEqual(usage["turns"], 3)
        self.assertNotIn("report", usage, "the report is not a usage field")

    def test_ac6_output_with_no_json_object_gives_no_usage_and_empty_report(self) -> None:
        expect = [{"check": "matches", "path": "@report", "pattern": "."}]
        passes = self.grade_once(expect, stdout=["plain text only", "[1, 2]"])
        self.assertEqual(passes, [False])
        usage = self.runs()[0]["usage"]
        self.assertNotIn("cost_usd", usage)
        self.assertNotIn("output_tokens", usage)


# AC7: the checks ---------------------------------------------------------------------------------


class ChecksTest(EvalTestCase):
    def test_ac7_file_exists_and_file_absent_use_a_glob(self) -> None:
        actions = [["write", "tests/test_slug.py", "x"]]
        expect = [
            {"check": "file_exists", "path": "tests/test_*.py"},
            {"check": "file_exists", "path": "docs/*.md"},
            {"check": "file_absent", "path": "docs/*.md"},
            {"check": "file_absent", "path": "tests/test_*.py"},
            {"check": "file_exists", "path": "**/app.py"},
        ]
        self.assertEqual(self.grade_once(expect, actions), [True, False, True, False, True])

    def test_ac7_unchanged_sees_committed_staged_unstaged_and_untracked(self) -> None:
        actions = [
            ["write", "a/new.txt", "committed"], ["add", "a/new.txt"], ["commit", "test: a"],
            ["write", "b/new.txt", "staged"], ["add", "b/new.txt"],
            ["write", "c/keep.txt", "unstaged change"],
            ["write", "d/new.txt", "untracked"],
        ]
        expect = [
            {"check": "unchanged", "paths": ["a/"]},
            {"check": "unchanged", "paths": ["b/"]},
            {"check": "unchanged", "paths": ["c/"]},
            {"check": "unchanged", "paths": ["d/"]},
            {"check": "unchanged", "paths": ["src/"]},
            {"check": "unchanged", "paths": ["src/", "e/"]},
            {"check": "unchanged", "paths": ["src/", "d/"]},
            {"check": "unchanged", "paths": ["c/keep.txt"]},
            {"check": "unchanged", "paths": ["d/ne"]},
        ]
        self.assertEqual(self.grade_once(expect, actions),
                         [False, False, False, False, True, True, False, False, True])

    def test_ac7_only_changed_needs_each_changed_file_under_paths(self) -> None:
        actions = [
            ["write", "tests/test_a.py", "x"], ["add", "tests/test_a.py"],
            ["commit", "test: add"],
            ["write", "docs/notes.md", "untracked"],
        ]
        expect = [
            {"check": "only_changed", "paths": ["tests/"]},
            {"check": "only_changed", "paths": ["tests/", "docs/"]},
            {"check": "only_changed", "paths": ["tests/", "docs/notes.md"]},
            {"check": "only_changed", "paths": ["tes", "docs/"]},
        ]
        passes = self.grade_once(expect, actions, change="fixtures/basic.diff")
        self.assertEqual(passes, [False, True, True, False])

    def test_ac7_matches_is_case_insensitive_and_multiline(self) -> None:
        actions = [["write", "notes.md", "First line\nHello World\nlast line\n"]]
        expect = [
            {"check": "matches", "path": "notes.md", "pattern": "hello world"},
            {"check": "matches", "path": "notes.md", "pattern": "^hello world$"},
            {"check": "matches", "path": "notes.md", "pattern": "goodbye"},
            {"check": "matches", "path": "missing.md", "pattern": "."},
            {"check": "matches", "path": "@report", "pattern": "ALL TESTS ADDED"},
        ]
        passes = self.grade_once(expect, actions,
                                 stdout=[result_line(report="Done: all tests added.")])
        self.assertEqual(passes, [True, True, False, False, True])

    def test_ac7_sections_in_order_reads_the_markdown_headings(self) -> None:
        report = ("# Test report\n\n## Tests added (3)\n\nText. Gaps are in the text only.\n\n"
                  "## Behavior covered\n\n## Failing tests\n")
        actions = [["write", "report.md", report]]
        expect = [
            {"check": "sections_in_order", "path": "report.md",
             "sections": ["Tests added", "Behavior covered", "Failing tests"]},
            {"check": "sections_in_order", "path": "report.md",
             "sections": ["Behavior covered", "Tests added"]},
            {"check": "sections_in_order", "path": "report.md",
             "sections": ["Tests added", "Gaps"]},
            {"check": "sections_in_order", "path": "missing.md", "sections": ["A"]},
        ]
        self.assertEqual(self.grade_once(expect, actions), [True, False, False, False])

    def test_ac7_json_valid_needs_an_object_with_the_required_keys(self) -> None:
        actions = [["write", "result.json", '{"a": 1, "b": 2}'],
                   ["write", "list.json", "[1, 2]"],
                   ["write", "bad.json", "{not json"]]
        expect = [
            {"check": "json_valid", "path": "result.json", "required": ["a", "b"]},
            {"check": "json_valid", "path": "result.json", "required": ["a", "c"]},
            {"check": "json_valid", "path": "result.json"},
            {"check": "json_valid", "path": "list.json"},
            {"check": "json_valid", "path": "bad.json"},
            {"check": "json_valid", "path": "missing.json"},
        ]
        self.assertEqual(self.grade_once(expect, actions),
                         [True, False, True, False, False, False])

    def test_ac7_command_compares_the_exit_code_and_runs_in_the_workspace(self) -> None:
        python = shlex.quote(sys.executable)

        def run(code: str) -> str:
            return f"{python} -c {shlex.quote(code)}"

        in_workspace = ("import pathlib, sys; "
                        "sys.exit(0 if pathlib.Path('marker.txt').is_file() else 1)")
        actions = [["write", "marker.txt", "x"]]
        expect = [
            {"check": "command", "run": run(in_workspace)},
            {"check": "command", "run": run("import sys; sys.exit(3)"), "exit": 3},
            {"check": "command", "run": run("import sys; sys.exit(3)")},
            {"check": "command", "run": run("import sys; sys.exit(0)"), "exit": 3},
            {"check": "command", "run": "/no/such/program-for-stone-eval"},
        ]
        self.assertEqual(self.grade_once(expect, actions), [True, True, False, False, False])

    def test_ac7_commit_trailer_needs_the_exact_line_in_a_commit_after_setup(self) -> None:
        actions = [["write", "tests/test_a.py", "x"], ["add", "tests/test_a.py"],
                   ["commit", "test: add tests\n\nRole: tester\nActor: agent"]]
        expect = [
            {"check": "commit_trailer", "trailer": "Role: tester"},
            {"check": "commit_trailer", "trailer": "Actor: agent"},
            {"check": "commit_trailer", "trailer": "Role: implementer"},
            {"check": "commit_trailer", "trailer": "Role: test"},
            {"check": "commit_trailer", "trailer": "Role: generator"},
        ]
        passes = self.grade_once(expect, actions, fixture="fixtures/rendered",
                                 change="fixtures/basic.diff")
        self.assertEqual(passes, [True, True, False, False, False])

    def test_ac7_commit_trailer_fails_when_the_run_makes_no_commit(self) -> None:
        expect = [{"check": "commit_trailer", "trailer": "Role: implementer"}]
        self.assertEqual(self.grade_once(expect, change="fixtures/basic.diff"), [False])

    def test_ac7_spec_delta_valid_uses_the_k19_parser(self) -> None:
        actions = [["write", "docs/plans/T-1.spec.md", VALID_DELTA],
                   ["write", "docs/plans/T-2.spec.md", INVALID_DELTA]]
        expect = [
            {"check": "spec_delta_valid", "path": "docs/plans/T-1.spec.md"},
            {"check": "spec_delta_valid", "path": "docs/plans/T-2.spec.md"},
            {"check": "spec_delta_valid", "path": "docs/plans/T-3.spec.md"},
        ]
        self.assertEqual(self.grade_once(expect, actions), [True, False, False])

    def test_ac7_grader_passes_only_on_last_line_json_pass_true(self) -> None:
        self.grader()
        actions = [["write", "marker.txt", "x"]]
        expect = [
            {"check": "grader", "name": "pass"},
            {"check": "grader", "name": "fail"},
            {"check": "grader", "name": "not_last"},
            {"check": "grader", "name": "uses_args", "file": "marker.txt", "min": 2},
            {"check": "grader", "name": "uses_args", "file": "absent.txt", "min": 2},
        ]
        self.assertEqual(self.grade_once(expect, actions), [True, False, False, True, False])

    def test_ac7_grader_crash_or_bad_output_fails_the_check_not_the_run(self) -> None:
        self.grader()
        expect = [
            {"check": "grader", "name": "crash"},
            {"check": "grader", "name": "bad_output"},
            {"check": "grader", "name": "silent"},
            {"check": "file_exists", "path": "src/app.py"},
        ]
        self.assertEqual(self.grade_once(expect), [False, False, False, True])
        self.assertEqual(self.runs()[0]["error"], "")
        _, rows = self.table()
        self.assertEqual(self.col(rows[("T1", "with")], "error"), "0")

    def test_ac7_kind_defaults_to_outcome(self) -> None:
        expect = [
            {"check": "file_exists", "path": "nothing.txt"},
            {"check": "file_exists", "path": "src/app.py", "kind": "contract"},
        ]
        self.grade_once(expect)
        _, rows = self.table()
        row = rows[("T1", "with")]
        self.assertAlmostEqual(float(self.col(row, "outcome")), 0.0)
        self.assertAlmostEqual(float(self.col(row, "contract")), 1.0)


# AC8: harness errors -----------------------------------------------------------------------------


class HarnessErrorTest(EvalTestCase):
    def two_scenarios(self) -> None:
        self.scenarios(self.scenario("T1"), self.scenario("T2"))

    def assert_error_recorded(self, run: dict) -> None:
        self.assertTrue(run["error"], run)
        self.assertEqual(self.check_passes(run), [True], "the checks are still recorded")

    def test_ac8_non_zero_exit_is_an_error_and_other_runs_continue(self) -> None:
        self.plan({"with": [{"exit": 3}, {}]})
        self.two_scenarios()
        code, out = self.eval("--variant", "with")
        self.assertEqual(code, 1, out)
        runs = {run["scenario"]: run for run in self.runs()}
        self.assert_error_recorded(runs["T1"])
        self.assertEqual(runs["T2"]["error"], "")
        _, rows = self.table()
        self.assertEqual(self.col(rows[("T1", "with")], "error"), "1")
        self.assertEqual(self.col(rows[("T2", "with")], "error"), "0")

    def test_ac8_harness_past_timeout_is_an_error_and_other_runs_continue(self) -> None:
        self.plan({"with": [{"sleep": 30}, {}]})
        self.two_scenarios()
        start = time.monotonic()
        code, out = self.eval("--variant", "with", "--timeout", "1")
        self.assertLess(time.monotonic() - start, 20, "the runner stops the harness")
        self.assertEqual(code, 1, out)
        runs = {run["scenario"]: run for run in self.runs()}
        self.assert_error_recorded(runs["T1"])
        self.assertEqual(runs["T2"]["error"], "")

    def test_ac8_harness_that_cannot_start_is_an_error_and_other_runs_continue(self) -> None:
        self.write_run_config(run={"with": [str(self.base / "no-such-harness"), "$prompt"]})
        self.scenarios(self.scenario())
        code, out = self.eval()
        self.assertEqual(code, 1, out)
        runs = {run["variant"]: run for run in self.runs()}
        self.assert_error_recorded(runs["with"])
        self.assertEqual(runs["without"]["error"], "")
        self.assertEqual([call["variant"] for call in self.calls()], ["without"])


# AC9: transcripts, runs.jsonl, and the result table ----------------------------------------------


class RecordsTest(EvalTestCase):
    def test_ac9_transcripts_and_runs_jsonl_go_to_the_eval_runs_folder(self) -> None:
        self.scenarios(self.scenario())
        code, out = self.eval("--trials", "2")
        self.assertEqual(code, 0, out)
        folder = self.runs_folder()
        self.assertTrue(folder.name.endswith("-role-tester"), folder.name)
        self.assertNotEqual(folder.name, "role-tester", "the folder name starts with a stamp")
        runs = self.runs()
        self.assertEqual(len(runs), 4)
        self.assertEqual(sorted((r["variant"], r["trial"]) for r in runs),
                         [("with", 1), ("with", 2), ("without", 1), ("without", 2)])
        texts = [p.read_text(encoding="utf-8") for p in folder.iterdir()
                 if p.is_file() and p.name != "runs.jsonl"]
        self.assertEqual(len(texts), 4, "one transcript for each run")
        for marker in ("TRANSCRIPT with 0", "TRANSCRIPT with 1", "TRANSCRIPT without 0",
                       "TRANSCRIPT without 1"):
            with self.subTest(marker=marker):
                self.assertEqual(sum(marker in text for text in texts), 1)
        self.assertEqual(len(list((self.root / "evals/results").glob("*.md"))), 1)

    def test_ac9_result_table_has_one_row_for_each_scenario_and_variant(self) -> None:
        both = [["write", "marker.txt", "x"], ["write", "contract.txt", "x"]]
        self.plan({
            "with": [
                {"actions": both, "stdout": [result_line(cost=0.2, tokens=10)]},
                {"actions": both[1:], "stdout": [result_line(cost=0.4, tokens=30)]},
                {}, {}],
            "without": [{"stdout": [result_line(cost=0.1, tokens=5)]}],
        })
        self.scenarios(
            self.scenario("T1", expect=[
                {"check": "file_exists", "path": "marker.txt"},
                {"check": "file_exists", "path": "contract.txt", "kind": "contract"}]),
            self.scenario("T2"))
        code, out = self.eval("--trials", "2")
        self.assertEqual(code, 1, out)
        text, rows = self.table()
        self.assertEqual(sorted(rows), [("T1", "with"), ("T1", "without"),
                                        ("T2", "with"), ("T2", "without")])
        t1_with = rows[("T1", "with")]
        self.assertEqual(self.col(t1_with, "trial"), "2")
        self.assertEqual(self.col(t1_with, "pass^k"), "0")
        self.assertAlmostEqual(float(self.col(t1_with, "outcome")), 0.5)
        self.assertAlmostEqual(float(self.col(t1_with, "contract")), 1.0)
        self.assertAlmostEqual(float(self.col(t1_with, "cost")), 0.3)
        self.assertAlmostEqual(float(self.col(t1_with, "token")), 20)
        self.assertGreaterEqual(float(self.col(t1_with, "second")), 0)
        self.assertEqual(self.col(t1_with, "error"), "0")
        t1_without = rows[("T1", "without")]
        self.assertEqual(self.col(t1_without, "pass^k"), "0")
        self.assertAlmostEqual(float(self.col(t1_without, "outcome")), 0.0)
        self.assertAlmostEqual(float(self.col(t1_without, "contract")), 0.0)
        self.assertAlmostEqual(float(self.col(t1_without, "cost")), 0.1)
        self.assertEqual(self.col(rows[("T2", "with")], "pass^k"), "1")
        self.assertAlmostEqual(float(self.col(rows[("T2", "with")], "outcome")), 1.0)
        # with: 3 of 4 runs pass the outcome checks. without: 2 of 4 (only T2).
        gain = re.search(r"with minus without\D*?([-+]?\d+(?:\.\d+)?)", text, re.I)
        self.assertIsNotNone(gain, text)
        self.assertAlmostEqual(float(gain.group(1)), 0.25)


# AC10: exit codes and options --------------------------------------------------------------------


class OptionsTest(EvalTestCase):
    def test_ac10_exit_0_if_all_with_runs_pass_and_without_runs_fail(self) -> None:
        self.plan({"with": [{"actions": [["write", "marker.txt", "x"]]}],
                   "without": [{"exit": 1}]})
        self.scenarios(self.scenario(expect=[{"check": "file_exists", "path": "marker.txt"}]))
        code, out = self.eval("--trials", "2")
        self.assertEqual(code, 0, out)
        runs = self.runs()
        self.assertEqual(len(runs), 4)
        self.assertTrue(all(run["error"] for run in runs if run["variant"] == "without"))

    def test_ac10_exit_1_if_a_with_run_fails_a_check(self) -> None:
        self.plan({"with": [{"actions": [["write", "marker.txt", "x"]]}, {}]})
        self.scenarios(self.scenario(expect=[{"check": "file_exists", "path": "marker.txt"}]))
        code, out = self.eval("--variant", "with", "--trials", "2")
        self.assertEqual(code, 1, out)

    def test_ac10_exit_1_if_a_with_run_fails_a_contract_check(self) -> None:
        self.scenarios(self.scenario(expect=[
            {"check": "file_exists", "path": "src/app.py"},
            {"check": "file_exists", "path": "nothing.txt", "kind": "contract"}]))
        code, out = self.eval("--variant", "with")
        self.assertEqual(code, 1, out)

    def test_ac10_trials_0_exits_2_and_starts_no_run(self) -> None:
        self.scenarios(self.scenario())
        code, out = self.eval("--trials", "0")
        self.assertEqual(code, 2, out)
        self.no_run_started()

    def test_ac10_unknown_scenario_id_exits_2_and_starts_no_run(self) -> None:
        self.scenarios(self.scenario("T1"), self.scenario("T2"))
        for ids in (["NOPE"], ["T1", "NOPE"]):
            with self.subTest(ids=ids):
                args = [part for sid in ids for part in ("--scenario", sid)]
                code, out = self.eval(*args)
                self.assertEqual(code, 2, out)
                self.assertIn("NOPE", out)
                self.no_run_started()

    def test_ac10_scenario_option_runs_only_that_scenario(self) -> None:
        self.scenarios(self.scenario("T1"), self.scenario("T2"), self.scenario("T3"))
        code, out = self.eval("--scenario", "T2", "--scenario", "T3")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted({run["scenario"] for run in self.runs()}), ["T2", "T3"])
        self.assertEqual(len(self.calls()), 4)

    def test_ac10_variant_with_runs_only_the_with_variant(self) -> None:
        self.scenarios(self.scenario())
        code, out = self.eval("--variant", "with")
        self.assertEqual(code, 0, out)
        self.assertEqual([call["variant"] for call in self.calls()], ["with"])
        text, rows = self.table()
        self.assertEqual(sorted(rows), [("T1", "with")])
        self.assertNotRegex(text, re.compile("with minus without", re.I))

    def test_ac10_trials_n_runs_n_trials_for_each_variant(self) -> None:
        self.scenarios(self.scenario())
        code, out = self.eval("--trials", "3")
        self.assertEqual(code, 0, out)
        variants = [call["variant"] for call in self.calls()]
        self.assertEqual((variants.count("with"), variants.count("without")), (3, 3))
        _, rows = self.table()
        self.assertEqual(self.col(rows[("T1", "with")], "trial"), "3")
        self.assertEqual(self.col(rows[("T1", "without")], "trial"), "3")


# AC11: workspace removal ---------------------------------------------------------------------


class KeepTest(EvalTestCase):
    def test_ac11_workspace_is_deleted_after_each_run(self) -> None:
        self.scenarios(self.scenario("T1"), self.scenario("T2"))
        code, out = self.eval()
        self.assertEqual(code, 0, out)
        calls = self.calls()
        self.assertEqual(len(calls), 4)
        for call in calls:
            self.assertFalse(Path(call["cwd"]).exists(), call["cwd"])

    def test_ac11_keep_keeps_each_workspace(self) -> None:
        self.plan({"with": [{"actions": [["write", "marker.txt", "x"]]}]})
        self.scenarios(self.scenario())
        code, out = self.eval("--variant", "with", "--keep")
        workspace = Path(self.calls()[0]["cwd"])
        self.addCleanup(self.remove_workspace, workspace)
        self.assertEqual(code, 0, out)
        self.assertTrue((workspace / "marker.txt").is_file())
        self.assertTrue((workspace / "src/app.py").is_file())

    @staticmethod
    def remove_workspace(workspace: Path) -> None:
        temp = Path(tempfile.gettempdir()).resolve()
        target = workspace.resolve()
        if target.parent != temp and target.parent.is_relative_to(temp):
            target = target.parent
        shutil.rmtree(target, ignore_errors=True)


# AC12: the model ---------------------------------------------------------------------------------


class ModelTest(EvalTestCase):
    def test_ac12_default_model_is_the_role_model_of_the_model_profile(self) -> None:
        framework = self.copy_framework()
        profile = framework / "adapters/claude-code/models/claude-5.yaml"
        data = yaml.safe_load(profile.read_text(encoding="utf-8"))
        data["defaults"]["role_models"]["tester"] = "fake-tester-model"
        data["defaults"]["role_models"]["reviewer"] = "fake-reviewer-model"
        profile.write_text(yaml.safe_dump(data), encoding="utf-8")
        self.scenarios(self.scenario())
        code, out = self.eval(framework=framework)
        self.assertEqual(code, 0, out)
        for call in self.calls():
            with self.subTest(variant=call["variant"]):
                self.assertEqual(arg(call, "--model"), "fake-tester-model")
        self.assertEqual(self.calls()[0]["env"]["FAKE_MODEL"], "fake-tester-model")

    def test_ac12_default_model_with_the_real_profile(self) -> None:
        data = yaml.safe_load((FRAMEWORK / "adapters/claude-code/models/claude-5.yaml")
                              .read_text(encoding="utf-8"))
        self.scenarios(self.scenario())
        self.eval("--variant", "with")
        self.assertEqual(arg(self.calls()[0], "--model"),
                         data["defaults"]["role_models"]["tester"])

    def test_ac12_model_option_overrides_the_profile(self) -> None:
        self.scenarios(self.scenario())
        code, out = self.eval("--model", "other-model")
        self.assertEqual(code, 0, out)
        for call in self.calls():
            with self.subTest(variant=call["variant"]):
                self.assertEqual(arg(call, "--model"), "other-model")


# Review fixes (AC13 to AC25) -----------------------------------------------------------------
#
# The criteria come from the follow-up ticket after the review of the first version.


class BareFixtureTest(EvalTestCase):
    def test_ac13_fixture_without_config_but_with_role_file_removes_it_for_without(self) -> None:
        self.write(f"{EVAL_DIR}/fixtures/bare/src/app.py", "VALUE = 1\n")
        self.write(f"{EVAL_DIR}/fixtures/bare/{ROLE_FILE}", "# The fixture tester role\n")
        self.scenarios(self.scenario(fixture="fixtures/bare", expect=[
            {"check": "unchanged", "paths": [".claude/"]}]))
        code, out = self.eval()
        self.assertEqual(code, 0, out)
        calls = {call["variant"]: call for call in self.calls()}
        self.assertIn(ROLE_FILE, calls["with"]["files"])
        self.assertNotIn(ROLE_FILE, calls["without"]["files"])
        for variant in ("with", "without"):
            with self.subTest(variant=variant):
                self.assertEqual(calls[variant]["status"], "", "the setup is committed")
        runs = {run["variant"]: run for run in self.runs()}
        self.assertEqual(self.check_passes(runs["without"]), [True],
                         "the removal is part of the setup, not a change of the run")


class ChangedPathsTest(EvalTestCase):
    RENAME_EXPECT = [
        {"check": "unchanged", "paths": ["b/"]},
        {"check": "unchanged", "paths": ["e/"]},
        {"check": "only_changed", "paths": ["e/"]},
        {"check": "only_changed", "paths": ["b/"]},
        {"check": "only_changed", "paths": ["b/", "e/"]},
        {"check": "unchanged", "paths": ["c/", "src/"]},
    ]
    RENAME_PASSES = [False, False, False, False, True, True]

    def grade_once(self, expect: list, actions: list | None = None,
                   stdout: list[str] | None = None, **extra: Any) -> list[bool]:
        passes = super().grade_once(expect, actions, stdout, **extra)
        self.assertEqual(self.runs()[0]["error"], "", "the fake harness actions worked")
        return passes

    def test_ac14_committed_rename_counts_both_paths(self) -> None:
        actions = [["mv", "b/keep.txt", "e/moved.txt"], ["commit", "test: move"]]
        passes = self.grade_once(self.RENAME_EXPECT, actions)
        self.assertEqual(passes, self.RENAME_PASSES, self.runs()[0])

    def test_ac14_staged_rename_counts_both_paths(self) -> None:
        actions = [["mv", "b/keep.txt", "e/moved.txt"]]
        passes = self.grade_once(self.RENAME_EXPECT, actions)
        self.assertEqual(passes, self.RENAME_PASSES, self.runs()[0])

    def test_ac14_paths_with_a_space_or_non_ascii_match(self) -> None:
        names = ["docs/my notes.md", "docs/日本語.md", "docs/café.md"]
        expect = [{"check": "unchanged", "paths": [name]} for name in names] + [
            {"check": "only_changed", "paths": names},
            {"check": "only_changed", "paths": names[:1]},
        ]
        writes = [["write", name, "text\n"] for name in names]
        modes = {
            "untracked": writes,
            "staged": writes + [["add", *names]],
            "committed": writes + [["add", *names], ["commit", "docs: add"]],
        }
        for mode, actions in modes.items():
            with self.subTest(mode=mode):
                self.reset_records()
                passes = self.grade_once(expect, actions)
                self.assertEqual(passes, [False, False, False, True, False], self.runs()[0])

    def test_ac14_rename_of_a_path_with_a_space_to_a_non_ascii_path(self) -> None:
        self.write(f"{EVAL_DIR}/fixtures/names/old name.txt", "same text\n")
        self.write(f"{EVAL_DIR}/fixtures/names/src/app.py", "VALUE = 1\n")
        expect = [
            {"check": "unchanged", "paths": ["old name.txt"]},
            {"check": "unchanged", "paths": ["日本/"]},
            {"check": "only_changed", "paths": ["old name.txt", "日本/"]},
            {"check": "unchanged", "paths": ["src/"]},
        ]
        modes = {
            "staged": [["mv", "old name.txt", "日本/new name.txt"]],
            "committed": [["mv", "old name.txt", "日本/new name.txt"], ["commit", "test: mv"]],
        }
        for mode, actions in modes.items():
            with self.subTest(mode=mode):
                self.reset_records()
                passes = self.grade_once(expect, actions, fixture="fixtures/names")
                self.assertEqual(passes, [False, False, True, True], self.runs()[0])


class GitConfigTest(EvalTestCase):
    """AC15: the git of the workspace does not read the global or the system git config."""

    EXPECT = [
        {"check": "commit_trailer", "trailer": "Role: tester"},
        {"check": "unchanged", "paths": ["ignored-new.txt"]},
        {"check": "only_changed", "paths": ["tests/"]},
        {"check": "command", "run": "git check-ignore -q ignored-new.txt", "exit": 1},
        {"check": "command", "run": "git commit -q --allow-empty -m signed-or-not"},
    ]
    PASSES = [True, False, False, True, True]

    def setUp(self) -> None:
        super().setUp()
        self.write(f"{EVAL_DIR}/fixtures/gitcfg/src/app.py", "VALUE = 1\n")
        self.write(f"{EVAL_DIR}/fixtures/gitcfg/ignored-base.txt", "in the fixture\n")
        ignore = self.base / "global-ignore"
        ignore.write_text("ignored*.txt\n", encoding="utf-8")
        self.bad_config = self.base / "bad-gitconfig"
        self.bad_config.write_text(
            f"[core]\n\texcludesFile = {ignore}\n[commit]\n\tgpgsign = true\n"
            "[gpg]\n\tprogram = /no/such/gpg-for-stone-eval\n", encoding="utf-8")
        self.empty_config = self.base / "empty-gitconfig"
        self.empty_config.write_text("", encoding="utf-8")
        self.plan({"with": [{"actions": [
            ["write", "tests/test_a.py", "x"], ["add", "tests/test_a.py"],
            ["commit", "test: add\n\nRole: tester"],
            ["write", "ignored-new.txt", "made by the run"]]}]})
        self.scenarios(self.scenario(fixture="fixtures/gitcfg", expect=self.EXPECT))

    def outcome(self, env: dict[str, str], drop: tuple[str, ...] = ()) -> tuple[list[bool], dict]:
        self.reset_records()
        with unittest.mock.patch.dict(os.environ, env):
            for name in drop:
                os.environ.pop(name, None)
            code, out = self.eval("--variant", "with")
        runs = self.runs()
        self.assertEqual(len(runs), 1, out)
        self.assertEqual(runs[0]["error"], "", out)
        calls = self.calls()
        self.assertEqual(len(calls), 1, out)
        return self.check_passes(runs[0]), calls[0]

    def assert_config_is_read_by_git(self, env: dict[str, str], scope: str) -> None:
        """Make sure that this git reads the variable. If not, the test proves nothing."""
        result = subprocess.run(["git", "config", f"--{scope}", "--get", "commit.gpgsign"],
                                env={**os.environ, **env}, capture_output=True, text=True)
        if result.stdout.strip() != "true":
            self.skipTest(f"this git does not read the {scope} config from the environment")

    def test_ac15_global_config_does_not_change_the_result(self) -> None:
        env = {"GIT_CONFIG_GLOBAL": str(self.bad_config)}
        self.assert_config_is_read_by_git(env, "global")
        baseline, _ = self.outcome({"GIT_CONFIG_GLOBAL": str(self.empty_config)})
        self.assertEqual(baseline, self.PASSES)
        passes, call = self.outcome(env)
        self.assertEqual(passes, baseline)
        self.assertIn("ignored-base.txt", call["tracked"], "the setup commits the ignored name")

    def test_ac15_system_config_does_not_change_the_result(self) -> None:
        env = {"GIT_CONFIG_GLOBAL": str(self.empty_config),
               "GIT_CONFIG_SYSTEM": str(self.bad_config)}
        self.assert_config_is_read_by_git({**env, "GIT_CONFIG_NOSYSTEM": ""}, "system")
        passes, call = self.outcome(env, drop=("GIT_CONFIG_NOSYSTEM",))
        self.assertEqual(passes, self.PASSES)
        self.assertIn("ignored-base.txt", call["tracked"])


class BrokenCheckTest(EvalTestCase):
    @staticmethod
    def glob_rejects(pattern: str) -> bool:
        try:
            list(Path(tempfile.gettempdir()).glob(pattern))
        except Exception:  # noqa: BLE001 - any error means that the glob rejects the pattern
            return True
        return False

    def test_ac16_a_check_that_raises_fails_only_that_check_and_the_eval_continues(self) -> None:
        rejected = [p for p in ("/an/absolute/*", "") if self.glob_rejects(p)]
        if not rejected:
            self.skipTest("this Python accepts each glob pattern in the list")
        broken = [{"check": "file_exists", "path": p} for p in rejected] + [
            {"check": "command", "run": 'echo "unbalanced'}]
        expect = broken + [{"check": "file_exists", "path": "src/app.py"}]
        self.scenarios(self.scenario("T1", expect=expect), self.scenario("T2", expect=expect))
        code, out = self.eval("--variant", "with")
        self.assertEqual(code, 1, out)
        runs = self.runs()
        self.assertEqual([run["scenario"] for run in runs], ["T1", "T2"], "the eval continues")
        for run in runs:
            with self.subTest(scenario=run["scenario"]):
                self.assertEqual(run["error"], "")
                self.assertEqual(self.check_passes(run), [False] * len(broken) + [True])
                for check in run["checks"][:len(broken)]:
                    self.assertTrue(check["detail"].startswith("the check failed"), check)
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertFalse(Path(call["cwd"]).exists(), "the workspace is deleted")


class PatternValidationTest(EvalTestCase):
    def test_ac17_matches_with_a_pattern_that_is_not_a_regex_is_not_valid(self) -> None:
        pattern = "([unclosed"
        self.scenarios(self.scenario(expect=[
            {"check": "matches", "path": "notes.md", "pattern": pattern}]))
        for args in (("--check-only",), ()):
            with self.subTest(args=args):
                code, out = self.eval(*args)
                self.assertEqual(code, 2, out)
                self.assertIn(pattern, out)
                self.no_run_started()

    def test_ac17_a_valid_pattern_is_accepted(self) -> None:
        self.scenarios(self.scenario(expect=[
            {"check": "matches", "path": "notes.md", "pattern": r"^\[closed\]$"}]))
        code, out = self.eval("--check-only")
        self.assertEqual(code, 0, out)


class StoppedProcessTest(EvalTestCase):
    def test_ac18_runs_jsonl_keeps_each_finished_run_after_the_process_stops(self) -> None:
        self.plan({"with": [{}, {"actions": [["kill_parent"]]}, {}]})
        self.scenarios(self.scenario("T1"), self.scenario("T2"), self.scenario("T3"))
        package = Path(cli.__file__).resolve().parents[1]
        env = {**os.environ,
               "PYTHONPATH": os.pathsep.join(filter(None, [str(package),
                                                           os.environ.get("PYTHONPATH")]))}
        script = "import sys; from stone import cli; sys.exit(cli.main(sys.argv[1:]))"
        result = subprocess.run(
            [sys.executable, "-c", script, "eval", COMPONENT, "--root", str(self.root),
             "--framework", str(FRAMEWORK), "--run-config", str(self.run_yaml),
             "--variant", "with"], env=env, capture_output=True, text=True, timeout=120)
        calls = self.calls()
        for call in calls[1:]:
            self.addCleanup(KeepTest.remove_workspace, Path(call["cwd"]))
        self.assertLess(result.returncode, 0, "the harness stopped the stone process")
        self.assertEqual(len(calls), 2, "T3 did not start")
        runs = self.runs()
        self.assertEqual([run["scenario"] for run in runs], ["T1"])
        self.assertEqual(self.check_passes(runs[0]), [True])


class StrictGraderTest(EvalTestCase):
    def test_ac19_grader_passes_only_on_the_json_value_true(self) -> None:
        self.grader()
        values = [True, "true", 1, "false", False, 1.0, "yes"]
        expect = [{"check": "grader", "name": "literal", "value": value} for value in values]
        self.assertEqual(self.grade_once(expect),
                         [True, False, False, False, False, False, False])


class StderrTest(EvalTestCase):
    def test_ac20_stderr_goes_to_an_err_file_next_to_the_transcript(self) -> None:
        self.plan({"with": [{"stderr": ["WARNING from the harness", "a second line"]}, {}]})
        self.scenarios(self.scenario("T1"), self.scenario("T2"))
        code, out = self.eval("--variant", "with")
        self.assertEqual(code, 0, out)
        folder = self.runs_folder()
        transcripts = {p.read_text(encoding="utf-8").splitlines()[0]: p
                       for p in folder.glob("*.out")}
        self.assertEqual(sorted(transcripts), ["TRANSCRIPT with 0", "TRANSCRIPT with 1"])
        with_err = transcripts["TRANSCRIPT with 0"].with_suffix(".err")
        no_err = transcripts["TRANSCRIPT with 1"].with_suffix(".err")
        self.assertTrue(with_err.is_file(), list(folder.iterdir()))
        text = with_err.read_text(encoding="utf-8")
        self.assertIn("WARNING from the harness", text)
        self.assertIn("a second line", text)
        self.assertNotIn("TRANSCRIPT", text, "the standard output is not in the .err file")
        self.assertFalse(no_err.exists(), "no standard error output, no .err file")
        self.assertEqual(len(list(folder.glob("*.err"))), 1)


class TimeoutChildTest(EvalTestCase):
    def late_file(self) -> Path:
        return self.state / "late.txt"

    def test_ac21_after_the_timeout_no_child_of_the_harness_writes(self) -> None:
        late = self.late_file()
        self.plan({"with": [{"actions": [["spawn", str(late), 2]], "sleep": 30}]})
        self.scenarios(self.scenario())
        start = time.monotonic()
        code, out = self.eval("--variant", "with", "--timeout", "1")
        self.assertEqual(code, 1, out)
        self.assertTrue(self.runs()[0]["error"])
        time.sleep(max(0.0, start + 5 - time.monotonic()))
        self.assertFalse(late.exists(), "a child of the harness wrote after the timeout")

    def test_ac21_control_the_child_writes_if_no_timeout_stops_it(self) -> None:
        late = self.late_file()
        self.plan({"with": [{"actions": [["spawn", str(late), 0.2]], "sleep": 2}]})
        self.scenarios(self.scenario())
        code, out = self.eval("--variant", "with", "--timeout", "60")
        self.assertEqual(code, 0, out)
        deadline = time.monotonic() + 5
        while not late.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(late.exists(), "the spawn action of the fake harness does not work")


class BadBytesTest(EvalTestCase):
    def test_ac22_output_that_is_not_utf8_does_not_stop_the_eval(self) -> None:
        self.plan({"with": [{"raw_stdout": "fffe20626164c30a", "raw_stderr": "ff0a"}]})
        expect = [{"check": "matches", "path": "@report", "pattern": "^done$"}]
        self.scenarios(self.scenario(expect=expect))
        code, out = self.eval("--variant", "with")
        self.assertEqual(code, 0, out)
        run = self.runs()[0]
        self.assertEqual(run["error"], "")
        self.assertEqual(self.check_passes(run), [True])

    def test_ac22_cut_utf8_at_a_timeout_does_not_stop_the_eval(self) -> None:
        self.plan({"with": [{"raw_stdout": "48690ae282", "stdout": [], "sleep": 30}, {}]})
        self.scenarios(self.scenario("T1"), self.scenario("T2"))
        code, out = self.eval("--variant", "with", "--timeout", "1")
        self.assertEqual(code, 1, out)
        runs = {run["scenario"]: run for run in self.runs()}
        self.assertTrue(runs["T1"]["error"])
        self.assertEqual(runs["T2"]["error"], "", "the eval continues after the timeout")


class ModelNameTest(EvalTestCase):
    def test_ac23_model_with_a_slash_writes_the_result_file_in_the_results_folder(self) -> None:
        self.scenarios(self.scenario())
        code, out = self.eval("--variant", "with", "--model", "vendor/model-x")
        self.assertEqual(code, 0, out)
        self.assertEqual(arg(self.calls()[0], "--model"), "vendor/model-x")
        results = self.root / "evals/results"
        self.assertEqual([p for p in results.rglob("*") if p.is_dir()], [],
                         "the model name makes no folder")
        files = list(results.glob("*.md"))
        self.assertEqual(len(files), 1, list(results.rglob("*")))
        self.assertIn("model-x", files[0].name)


class MergedComponentTest(EvalTestCase):
    MERGED = "hook.settings"

    def setUp(self) -> None:
        super().setUp()
        folder = "evals/hook-protect-paths"
        self.write(f"{folder}/fixtures/basic/src/app.py", "VALUE = 1\n")
        self.write(f"{folder}/scenarios.yaml", yaml.safe_dump({
            "component": self.MERGED, "role": "implementer", "task": "Do the task.",
            "scenarios": [self.scenario()]}, sort_keys=False))

    def eval_merged(self, *args: str) -> tuple[int, str]:
        argv = ["eval", self.MERGED, "--root", str(self.root), "--framework", str(FRAMEWORK),
                "--run-config", str(self.run_yaml), *args]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(argv)
        return code, out.getvalue()

    def test_ac24_merged_component_with_without_or_both_exits_2(self) -> None:
        for args in ((), ("--variant", "both"), ("--variant", "without"), ("--check-only",),
                     ("--variant", "without", "--check-only")):
            with self.subTest(args=args):
                code, out = self.eval_merged(*args)
                self.assertEqual(code, 2, out)
                self.assertIn(self.MERGED, out)
                self.no_run_started()

    def test_ac24_merged_component_with_variant_with_runs(self) -> None:
        code, out = self.eval_merged("--variant", "with", "--check-only")
        self.assertEqual(code, 0, out)
        code, out = self.eval_merged("--variant", "with")
        self.assertNotEqual(code, 2, out)
        self.assertEqual([call["variant"] for call in self.calls()], ["with"])


class ShapeValidationTest(EvalTestCase):
    def assert_exit_2(self, data: dict) -> None:
        self.write_yaml(data)
        for args in (("--check-only",), ()):
            code, out = self.eval(*args)
            self.assertEqual(code, 2, out)
            self.no_run_started()

    def test_ac25_scenarios_that_is_not_a_list_exits_2(self) -> None:
        for value in ({"T1": self.scenario()}, "T1", 5, True):
            with self.subTest(value=value):
                self.assert_exit_2({"component": COMPONENT, "role": "tester",
                                    "scenarios": value})

    def test_ac25_expect_that_is_not_a_list_exits_2(self) -> None:
        for value in ({"check": "file_exists", "path": "src/app.py"}, "file_exists", 5, True):
            with self.subTest(value=value):
                item = self.scenario()
                item["expect"] = value
                self.assert_exit_2({"component": COMPONENT, "role": "tester",
                                    "scenarios": [item]})


# Real-run fixes (AC26, AC27) -----------------------------------------------------------------
#
# The criteria come from the follow-up ticket after a real harness run.


def event(**fields: Any) -> str:
    """One JSON object line of a harness output stream."""
    return json.dumps(fields)


class OutputWhereTest(EvalTestCase):
    """AC26: `output_where` selects the JSON object line that gives the usage and the report."""

    EXPECT = [{"check": "matches", "path": "@report", "pattern": "^THE RESULT$"},
              {"check": "file_exists", "path": "src/app.py"}]

    @staticmethod
    def stream() -> list[str]:
        """A stream in which the result event is not the last JSON object line."""
        return [
            "starting the run",
            event(type="system", subtype="init", result="init", total_cost_usd=7.0),
            event(type="result", subtype="success", result="an earlier result",
                  total_cost_usd=0.05, num_turns=1,
                  usage={"output_tokens": 1, "input_tokens": 1}),
            event(type="result", subtype="success", result="THE RESULT", total_cost_usd=0.25,
                  num_turns=3, usage={"output_tokens": 42, "input_tokens": 7}),
            event(type="system", subtype="hook", result="a later event", total_cost_usd=9.0),
            event(result="an object with no type key", total_cost_usd=8.0),
            event(type="result", subtype="error", result="other subtype", total_cost_usd=6.0,
                  num_turns=4, usage={"output_tokens": 60, "input_tokens": 6}),
            json.dumps([1, 2, 3]),
            "a last line that is not JSON",
        ]

    def run_with(self, where: Any, stdout: list[str], expect: list | None = None) -> dict:
        self.reset_records()
        self.write_run_config(output_where=where)
        self.plan({"with": [{"stdout": stdout}]})
        self.scenarios(self.scenario(expect=expect or self.EXPECT))
        code, out = self.eval("--variant", "with")
        runs = self.runs()
        self.assertEqual(len(runs), 1, out)
        return runs[0]

    def test_ac26_output_where_reads_the_last_matching_object_and_skips_later_ones(self) -> None:
        run = self.run_with({"type": "result", "subtype": "success"}, self.stream())
        self.assertEqual(run["error"], "")
        self.assertEqual(self.check_passes(run), [True, True], run)
        usage = run["usage"]
        self.assertEqual(usage["cost_usd"], 0.25)
        self.assertEqual(usage["output_tokens"], 42)
        self.assertEqual(usage["input_tokens"], 7)
        self.assertEqual(usage["turns"], 3)

    def test_ac26_output_where_needs_each_key_to_match(self) -> None:
        """With only `type`, the later object with the other subtype is the last match."""
        run = self.run_with({"type": "result"}, self.stream(), expect=[
            {"check": "matches", "path": "@report", "pattern": "^other subtype$"}])
        self.assertEqual(self.check_passes(run), [True], run)
        self.assertEqual(run["usage"]["cost_usd"], 6.0)
        self.assertEqual(run["usage"]["turns"], 4)

    def test_ac26_output_where_with_no_match_gives_empty_usage_and_the_run_is_graded(self) -> None:
        expect = [{"check": "matches", "path": "@report", "pattern": "."},
                  {"check": "file_exists", "path": "src/app.py"},
                  {"check": "file_exists", "path": "marker.txt"}]
        self.reset_records()
        self.write_run_config(output_where={"type": "result", "subtype": "never"})
        self.plan({"with": [{"stdout": self.stream(),
                             "actions": [["write", "marker.txt", "x"]]}]})
        self.scenarios(self.scenario(expect=expect))
        code, out = self.eval("--variant", "with")
        runs = self.runs()
        self.assertEqual(len(runs), 1, out)
        run = runs[0]
        self.assertEqual(run["error"], "", "no match is not a harness error")
        self.assertEqual(self.check_passes(run), [False, True, True], "the run is graded")
        for name in ("cost_usd", "output_tokens", "input_tokens", "turns", "report"):
            with self.subTest(name=name):
                self.assertNotIn(name, run["usage"])
        _, rows = self.table()
        self.assertEqual(self.col(rows[("T1", "with")], "error"), "0")

    def test_ac26_without_output_where_reads_the_last_json_object_line(self) -> None:
        run = self.run_with(None, self.stream(), expect=[
            {"check": "matches", "path": "@report", "pattern": "^other subtype$"}])
        self.assertEqual(self.check_passes(run), [True], run)
        self.assertEqual(run["usage"]["cost_usd"], 6.0)
        self.assertEqual(run["usage"]["output_tokens"], 60)

    def test_ac26_output_where_needs_the_key_in_the_object(self) -> None:
        """A `null` value in `output_where` does not match an object that does not have the key."""
        stdout = [
            event(type="result", stop_reason=None, result="THE RESULT", total_cost_usd=0.25),
            event(type="result", result="no stop_reason key", total_cost_usd=5.0),
        ]
        run = self.run_with({"type": "result", "stop_reason": None}, stdout)
        self.assertEqual(run["usage"].get("cost_usd"), 0.25, run)
        self.assertEqual(self.check_passes(run), [True, True], run)

    def test_ac26_output_where_compares_json_values_of_the_same_type(self) -> None:
        """The JSON values 0 and 1 are not the JSON values false and true."""
        cases = {
            "false is not 0": ({"type": "result", "is_error": False}, "is_error", False, 0),
            "true is not 1": ({"type": "result", "done": True}, "done", True, 1),
        }
        for name, (where, key, right, wrong) in cases.items():
            with self.subTest(case=name):
                stdout = [
                    event(type="result", result="THE RESULT", total_cost_usd=0.25, **{key: right}),
                    event(type="result", result="wrong type", total_cost_usd=5.0, **{key: wrong}),
                ]
                run = self.run_with(where, stdout)
                self.assertEqual(run["usage"].get("cost_usd"), 0.25, run)

    def test_ac26_adapter_eval_yaml_reads_the_result_event_of_a_stream(self) -> None:
        """The real `output_where` and `output` of the adapter, with the stream of a real run."""
        framework = self.copy_framework()
        adapter_file = framework / "adapters/claude-code/eval.yaml"
        adapter = yaml.safe_load(adapter_file.read_text(encoding="utf-8"))
        self.assertIsInstance(adapter.get("output_where"), dict, "the adapter gives output_where")
        self.write_run_config(path=adapter_file, output=adapter["output"],
                              output_where=adapter["output_where"])
        stdout = [
            event(type="system", subtype="init", session_id="s1"),
            event(type="assistant", message={"content": [{"type": "text", "text": "Working."}]}),
            event(type="result", subtype="success", is_error=False, result="THE RESULT",
                  total_cost_usd=0.25, num_turns=3,
                  usage={"output_tokens": 42, "input_tokens": 7}),
            event(type="system", subtype="status", session_id="s1"),
        ]
        self.plan({"with": [{"stdout": stdout}], "without": [{"stdout": stdout}]})
        self.scenarios(self.scenario(expect=self.EXPECT))
        code, out = self.eval(framework=framework, run_config=False)
        self.assertEqual(code, 0, out)
        runs = self.runs()
        self.assertEqual(sorted(run["variant"] for run in runs), ["with", "without"])
        for run in runs:
            with self.subTest(variant=run["variant"]):
                self.assertEqual(self.check_passes(run), [True, True], run)
                self.assertEqual(run["usage"]["cost_usd"], 0.25)
                self.assertEqual(run["usage"]["output_tokens"], 42)
                self.assertEqual(run["usage"]["input_tokens"], 7)
                self.assertEqual(run["usage"]["turns"], 3)


class WorkBranchTest(EvalTestCase):
    """AC27: the base is on `main`. The setup commits and the run are on `feature/eval-work`."""

    BRANCH = "feature/eval-work"

    @staticmethod
    def commits(log: str) -> list[tuple[str, list[str]]]:
        """Parse a `%H%x1f%B%x1e` log into (hash, message lines), newest first."""
        items = []
        for entry in log.split("\x1e"):
            if entry.strip():
                sha, _, body = entry.strip().partition("\x1f")
                items.append((sha.strip(), [line.strip() for line in body.splitlines()]))
        return items

    def test_ac27_harness_starts_on_the_work_branch_in_both_variants(self) -> None:
        self.scenarios(self.scenario(fixture="fixtures/rendered", change="fixtures/basic.diff"))
        code, out = self.eval()
        self.assertEqual(code, 0, out)
        calls = self.calls()
        self.assertEqual(sorted(call["variant"] for call in calls), ["with", "without"])
        for call in calls:
            with self.subTest(variant=call["variant"]):
                self.assertEqual(call["branch"], self.BRANCH)
                self.assertEqual(call["status"], "")

    def test_ac27_base_is_on_main_and_the_render_and_change_commits_are_on_the_work_branch(
            self) -> None:
        self.scenarios(self.scenario(fixture="fixtures/rendered", change="fixtures/basic.diff"))
        code, out = self.eval()
        self.assertEqual(code, 0, out)
        for call in self.calls():
            with self.subTest(variant=call["variant"]):
                main = self.commits(call["main_log"])
                head = self.commits(call["head_log"])
                self.assertEqual(len(main), 1, "main has only the base commit of the fixture")
                base_sha, base_lines = main[0]
                self.assertEqual(head[-1][0], base_sha, "the work branch starts at the base")
                self.assertNotIn("Role: generator", base_lines)
                self.assertNotIn("Role: implementer", base_lines)
                after_base = [lines for sha, lines in head if sha != base_sha]
                self.assertTrue(any("Role: generator" in lines for lines in after_base),
                                "the render commit is on the work branch")
                self.assertTrue(any("Role: implementer" in lines for lines in after_base),
                                "the change commit is on the work branch")
                self.assertIn("src/app.py", call["main_files"])
                self.assertIn(".cornerstone/config.yaml", call["main_files"])
                self.assertNotIn(OTHER_ROLE_FILE, call["main_files"],
                                 "the rendered files are not on main")
                self.assertIn(OTHER_ROLE_FILE, call["files"])

    def test_ac27_base_is_on_main_for_a_fixture_with_no_config_and_no_change(self) -> None:
        self.scenarios(self.scenario(fixture="fixtures/basic"))
        self.eval("--variant", "with")
        call = self.calls()[0]
        self.assertEqual(call["branch"], self.BRANCH)
        main = self.commits(call["main_log"])
        self.assertEqual(len(main), 1)
        self.assertEqual(self.commits(call["head_log"])[-1][0], main[0][0])
        self.assertIn("b/keep.txt", call["main_files"])

    def on_branch_command(self) -> str:
        """A command check: HEAD is still on the work branch and main has only the base."""
        code = ("import subprocess, sys\n"
                "def git(*a):\n"
                "    return subprocess.run(['git', *a], capture_output=True,"
                " text=True).stdout.strip()\n"
                f"ok = (git('symbolic-ref', '--short', 'HEAD') == {self.BRANCH!r}"
                " and git('rev-list', '--count', 'main') == '1')\n"
                "sys.exit(0 if ok else 1)\n")
        return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"

    def test_ac27_harness_commit_on_the_work_branch_counts_for_the_checks(self) -> None:
        actions = [["write", "tests/test_a.py", "x"], ["add", "tests/test_a.py"],
                   ["commit", "test: add tests\n\nRole: tester\nActor: agent"]]
        expect = [
            {"check": "commit_trailer", "trailer": "Role: tester"},
            {"check": "commit_trailer", "trailer": "Actor: agent"},
            {"check": "commit_trailer", "trailer": "Role: implementer"},
            {"check": "commit_trailer", "trailer": "Role: generator"},
            {"check": "only_changed", "paths": ["tests/"]},
            {"check": "unchanged", "paths": ["tests/"]},
            {"check": "unchanged", "paths": ["src/", ".claude/", ".cornerstone/"]},
            {"check": "command", "run": self.on_branch_command()},
        ]
        passes = self.grade_once(expect, actions, fixture="fixtures/rendered",
                                 change="fixtures/basic.diff")
        self.assertEqual(self.runs()[0]["error"], "")
        self.assertEqual(self.calls()[0]["branch"], self.BRANCH)
        self.assertEqual(passes, [True, True, False, False, True, False, True, True],
                         self.runs()[0]["checks"])

    def test_ac27_files_of_a_harness_commit_count_for_unchanged_and_only_changed(self) -> None:
        actions = [["write", "src/app.py", "VALUE = 2\n"],
                   ["write", "tests/test_a.py", "x"], ["add", "src/app.py", "tests/test_a.py"],
                   ["commit", "fix: change src\n\nRole: tester"]]
        expect = [
            {"check": "unchanged", "paths": ["src/"]},
            {"check": "only_changed", "paths": ["tests/"]},
            {"check": "only_changed", "paths": ["tests/", "src/"]},
            {"check": "unchanged", "paths": [".claude/", ".cornerstone/", "b/"]},
            {"check": "command", "run": self.on_branch_command()},
        ]
        passes = self.grade_once(expect, actions, fixture="fixtures/rendered",
                                 change="fixtures/basic.diff")
        self.assertEqual(self.runs()[0]["error"], "")
        self.assertEqual(passes, [False, False, True, True, True], self.runs()[0]["checks"])


# EVAL-4c criterion 1 (D33): the grader gets the final report of the run -----------------------

REPORT_GRADER = r'''
import argparse, json, os
parser = argparse.ArgumentParser()
parser.add_argument("name")
parser.add_argument("--workspace", required=True)
parser.add_argument("--args", required=True)
options = parser.parse_args()
args = json.loads(options.args)
value = os.environ.get("STONE_EVAL_REPORT")
keep = os.environ.get("STONE_TEST_KEEP")
ok = value == args["report"] and keep == "kept"
print(json.dumps({"pass": ok, "detail": json.dumps({"report": value, "keep": keep})}))
'''


class ReportEnvTest(EvalTestCase):
    def grade_report(self, expected: str, stdout: list[str]) -> list[dict]:
        self.write(f"{EVAL_DIR}/grade.py", REPORT_GRADER)
        expect = [{"check": "grader", "name": "report", "report": expected}]
        with unittest.mock.patch.dict(os.environ, {"STONE_TEST_KEEP": "kept",
                                                   "STONE_EVAL_REPORT": "a stale outer value"}):
            self.grade_once(expect, stdout=stdout)
        return self.runs()[0]["checks"]

    def test_eval4c_c1_grader_gets_the_report_in_stone_eval_report(self) -> None:
        report = "Plan written.\n\n## Open questions\n\n- What does an expired code do? é"
        checks = self.grade_report(report, [result_line(report=report)])
        self.assertTrue(checks[0]["pass"], checks[0]["detail"])

    def test_eval4c_c1_with_no_report_the_value_is_an_empty_string(self) -> None:
        checks = self.grade_report("", ["plain text only, no JSON object"])
        self.assertTrue(checks[0]["pass"], checks[0]["detail"])

    def test_eval4c_c1_the_report_is_the_report_field_of_the_last_result(self) -> None:
        stdout = [json.dumps({"type": "result", "result": "not this one"}),
                  result_line(report="THE FINAL TEXT")]
        checks = self.grade_report("THE FINAL TEXT", stdout)
        self.assertTrue(checks[0]["pass"], checks[0]["detail"])

    def test_eval4c_c1_each_grader_check_of_a_run_gets_the_report(self) -> None:
        self.write(f"{EVAL_DIR}/grade.py", REPORT_GRADER)
        expect = [{"check": "grader", "name": "a", "report": "done twice"},
                  {"check": "grader", "name": "b", "report": "done twice"},
                  {"check": "grader", "name": "c", "report": "other"}]
        with unittest.mock.patch.dict(os.environ, {"STONE_TEST_KEEP": "kept"}):
            passes = self.grade_once(expect, stdout=[result_line(report="done twice")])
        self.assertEqual(passes, [True, True, False], self.runs()[0]["checks"])


# EVAL-4c criterion 8: the first entry of git status keeps its whole path -----------------------


class FirstStatusEntryTest(EvalTestCase):
    """The run makes only changes of tracked files that are not in the index (" M path")."""

    def grade_unstaged(self, expect: list, actions: list) -> list[bool]:
        passes = self.grade_once(expect, actions)
        run = self.runs()[0]
        self.assertEqual(run["error"], "", "the fake harness actions worked")
        status = self.calls()[0]["status"]
        self.assertEqual(status, "", "the setup is committed, so the run makes the only changes")
        return passes

    def test_eval4c_c8_only_one_unstaged_change_under_src_fails_unchanged_src(self) -> None:
        expect = [
            {"check": "unchanged", "paths": ["src/"]},
            {"check": "unchanged", "paths": ["src/app.py"]},
            {"check": "unchanged", "paths": ["rc/"]},
            {"check": "only_changed", "paths": ["src/"]},
            {"check": "only_changed", "paths": ["src/app.py"]},
            {"check": "only_changed", "paths": ["rc/"]},
            {"check": "unchanged", "paths": ["b/", "c/"]},
        ]
        passes = self.grade_unstaged(expect, [["write", "src/app.py", "VALUE = 2\n"]])
        self.assertEqual(passes, [False, False, True, True, True, False, True], self.runs()[0])

    def test_eval4c_c8_unstaged_first_entry_and_later_entries_are_all_whole(self) -> None:
        # b/keep.txt sorts first, so its " M" entry is the first entry of the status list.
        actions = [["write", "b/keep.txt", "changed b\n"], ["write", "c/keep.txt", "changed c\n"],
                   ["write", "d/new.txt", "untracked\n"]]
        expect = [
            {"check": "unchanged", "paths": ["b/"]},
            {"check": "unchanged", "paths": ["c/"]},
            {"check": "unchanged", "paths": ["d/"]},
            {"check": "unchanged", "paths": ["/keep.txt"]},
            {"check": "only_changed", "paths": ["b/", "c/", "d/"]},
            {"check": "only_changed", "paths": ["c/", "d/"]},
            {"check": "unchanged", "paths": ["src/"]},
        ]
        passes = self.grade_unstaged(expect, actions)
        self.assertEqual(passes, [False, False, False, True, True, False, True], self.runs()[0])

    def test_eval4c_c8_unstaged_delete_of_a_tracked_file_is_whole(self) -> None:
        self.write(f"{EVAL_DIR}/fixtures/del/src/app.py", "VALUE = 1\n")
        self.write(f"{EVAL_DIR}/fixtures/del/src/old.py", "OLD = 1\n")
        script = "import os; os.remove('src/old.py')"
        expect = [
            {"check": "unchanged", "paths": ["src/"]},
            {"check": "unchanged", "paths": ["src/old.py"]},
            {"check": "only_changed", "paths": ["src/old.py"]},
            {"check": "unchanged", "paths": ["rc/"]},
        ]
        self.plan({"with": [{"actions": []}]})
        self.scenarios(self.scenario(expect=expect, fixture="fixtures/del"))
        # The fake harness has no delete action, so a command check before the checks is not
        # possible. Use a run config whose command deletes the file, then runs the fake harness.
        cmd = [sys.executable, "-c",
               f"{script}; import runpy, sys; sys.argv = {[str(self.fake), 'with']!r} + "
               "sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')",
               "--role", "$role"]
        self.write_run_config(run={"with": cmd})
        self.eval("--variant", "with")
        run = self.runs()[0]
        self.assertEqual(run["error"], "", run)
        self.assertEqual(self.check_passes(run), [False, False, True, True], run)


if __name__ == "__main__":
    unittest.main()
