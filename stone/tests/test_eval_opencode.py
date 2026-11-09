"""Tests for the OpenCode harness adapter (P12): `stone eval` runs a role with `opencode run`.

No real model starts. A fake `opencode` on `PATH` records each call and writes the JSON events of
a run. The test uses the real adapter files in `framework/adapters/opencode/`.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from stone import cli, evals, framework_check, render

REPO = Path(__file__).resolve().parents[2]
FRAMEWORK = REPO / "framework"
ADAPTER = FRAMEWORK / "adapters" / "opencode"
EVAL_YAML = ADAPTER / "eval.yaml"
COMPONENTS = ADAPTER / "components.yaml"
MODEL_PROFILE = ADAPTER / "models" / "opencode-default.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opencode"
ROLE_FILE = ".opencode/agents/tester.md"
EXPECTED_ROLES = {"shaper", "planner", "implementer", "tester", "reviewer", "investigator"}
EXPECTED_TOOLS = {
    "shaper": ["read", "grep", "glob", "shell", "edit"],
    "planner": ["read", "grep", "glob", "edit"],
    "implementer": ["read", "grep", "glob", "edit", "shell"],
    "tester": ["read", "grep", "glob", "edit", "shell"],
    "reviewer": ["read", "grep", "glob", "shell"],
    "investigator": ["read", "grep", "glob", "edit", "shell"],
}

CONFIG = """framework_version: 1.6.0
harness: opencode
model_profile: opencode-default
profiles: [single-ticket]
branches: {integration: main, main: main}
commands:
  install: "true"
  test_unit: "true"
  all_checks: "true"
paths:
  tests: [tests/]
  checks: [.cornerstone/checks/]
  plans: docs/plans/
owners: {default: eval}
"""

FAKE_OPENCODE = r'''#!/usr/bin/env python3
"""A fake `opencode` for the adapter test. It records the call and writes a JSON stream."""
import json
import os
import sys
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
state.mkdir(parents=True, exist_ok=True)
cwd = Path.cwd()
files = sorted(path.relative_to(cwd).as_posix() for path in cwd.rglob("*")
               if path.is_file() and ".git" not in path.relative_to(cwd).parts)
record = {"argv": sys.argv[1:], "cwd": str(cwd), "files": files}
with (state / "calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\n")
print(json.dumps({"type": "step_start", "part": {"type": "step-start"}}))
print(json.dumps({"type": "text",
                  "part": {"type": "text", "messageID": "msg_1",
                           "text": "OPENCODE REPORT"}}))
print(json.dumps({"type": "step_finish",
                  "part": {"type": "step-finish", "reason": "stop", "cost": 0.0,
                           "tokens": {"input": 1, "output": 1}}}))
'''


class OpenCodeAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "repo"
        self.state = self.base / "state"
        self.bin = self.base / "bin"
        self.state.mkdir()
        self.bin.mkdir()
        self.write(".cornerstone/config.yaml", CONFIG)
        self.write(f"evals/role-tester/fixtures/basic/{ROLE_FILE}",
                   "---\ndescription: Write tests.\nmode: primary\n---\n\nWrite tests.\n")
        self.write("evals/role-tester/scenarios.yaml", yaml.safe_dump({
            "component": "role.tester",
            "role": "tester",
            "task": "Write tests for this ticket.",
            "scenarios": [{
                "id": "O1",
                "fixture": "fixtures/basic",
                "prompt": "Do the job.",
                "expect": [
                    {"check": "file_exists", "path": ROLE_FILE},
                    {"check": "matches", "path": "@report", "pattern": "OPENCODE REPORT"},
                ],
            }],
        }, sort_keys=False))
        fake = self.bin / "opencode"
        fake.write_text(FAKE_OPENCODE, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        patcher = mock.patch.dict(os.environ, {
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_STATE": str(self.state),
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, path: str, text: str) -> Path:
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")
        return full

    def eval(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["eval", "role.tester", "--root", str(self.root),
                             "--framework", str(FRAMEWORK), "--model", "opencode-go/beam-free",
                             *args])
        return code, out.getvalue()

    def component(self, component: str, *args: str) -> tuple[int, str]:
        """Run a named component with the OpenCode run config."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["eval", component, "--root", str(self.root),
                             "--framework", str(FRAMEWORK), "--run-config", str(EVAL_YAML),
                             "--check-only", *args])
        return code, out.getvalue()

    def no_harness_started(self) -> None:
        self.assertFalse((self.state / "calls.jsonl").exists())

    def calls(self) -> list[dict]:
        path = self.state / "calls.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def runs(self) -> list[dict]:
        folders = list((self.root / ".cornerstone/eval-runs").iterdir())
        self.assertEqual(len(folders), 1, folders)
        text = (folders[0] / "runs.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def parser(self):
        return evals.load_parser(EVAL_YAML, ADAPTER, evals.load_run_config(EVAL_YAML))

    def test_run_config_names_the_role_the_model_and_the_parser(self) -> None:
        config = evals.load_run_config(EVAL_YAML)
        self.assertEqual(config["run"]["with"][:2], ["opencode", "--standalone"])
        self.assertIn("run", config["run"]["with"])
        self.assertIn("--agent", config["run"]["with"])
        self.assertIn("$role", config["run"]["with"])
        self.assertIn("$model", config["run"]["with"])
        self.assertIn("--standalone", config["run"]["with"])
        self.assertNotIn("--agent", config["run"]["without"])
        self.assertEqual(config["parser"], "parsers/opencode.py")
        self.assertEqual(config["tools"], EXPECTED_TOOLS)
        self.assertIn("guidance", config["unsupported"])

    def test_adapter_owns_the_shaper_permissions(self) -> None:
        file_values = render.adapter_values(ADAPTER, {
            "tickets": {"source": "file", "path": "tickets/{id}.md"}})
        file_rules = json.loads(file_values["shaper_permissions"])
        self.assertEqual(file_rules[0], {"action": "*", "resource": "*", "effect": "deny"})
        self.assertEqual([rule["action"] for rule in file_rules[1:]], EXPECTED_TOOLS["shaper"])
        plain_values = render.adapter_values(ADAPTER, {})
        plain_rules = json.loads(plain_values["shaper_permissions"])
        expected = [action for action in EXPECTED_TOOLS["shaper"] if action != "edit"]
        self.assertEqual([rule["action"] for rule in plain_rules[1:]], expected)

    def test_core_has_no_harness_tool_or_permission_values(self) -> None:
        values = render.ticket_values({})
        self.assertNotIn("shaper_tools", values)
        self.assertNotIn("shaper_permissions", values)
        source = (REPO / "stone/src/stone/render.py").read_text(encoding="utf-8")
        self.assertNotIn('"effect"', source)
        self.assertNotIn('"resource"', source)

    def test_component_list_maps_each_role_to_its_agent_file(self) -> None:
        data = yaml.safe_load(COMPONENTS.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "eval-only")
        roles = {entry["role"]: entry for entry in data["components"]
                 if entry.get("kind") == "role"}
        self.assertEqual(set(roles), EXPECTED_ROLES)
        for role, entry in roles.items():
            with self.subTest(role=role):
                self.assertEqual(entry["target"], f".opencode/agents/{role}.md")
                self.assertEqual(entry["template"], f"agents/{role}.md")
                self.assertTrue(entry["eval"])

    def test_model_profile_covers_each_role(self) -> None:
        profile = yaml.safe_load(MODEL_PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(profile["harness"], "opencode")
        self.assertEqual(set(profile["defaults"]["role_models"]), EXPECTED_ROLES)

    def test_role_templates_keep_the_steps_and_add_the_permissions(self) -> None:
        path_rule = re.compile(r"(A hook blocks the file tools[^\n]*|The role text[^\n]*)")
        for role in EXPECTED_ROLES:
            with self.subTest(role=role):
                reference = (FRAMEWORK / "adapters" / "claude-code" / "templates" / "agents"
                             / f"{role}.md").read_text(encoding="utf-8")
                template = (ADAPTER / "templates" / "agents" / f"{role}.md").read_text(
                    encoding="utf-8")
                reference_body = path_rule.sub("<PATH_RULE>", reference.split("---\n", 2)[2])
                template_body = path_rule.sub("<PATH_RULE>", template.split("---\n", 2)[2])
                self.assertEqual(template_body, reference_body)
                front = yaml.safe_load(template.split("---\n", 2)[1])
                self.assertEqual(front["steps"], 60)
                self.assertIn("permissions", front)
                self.assertNotIn("tools", front)
                permissions = front["permissions"]
                if role == "shaper":
                    values = render.adapter_values(ADAPTER, {
                        "tickets": {"source": "file", "path": "tickets/{id}.md"}})
                    permissions = json.loads(values["shaper_permissions"])
                self.assertEqual(permissions[0],
                                 {"action": "*", "resource": "*", "effect": "deny"})
                actions = [rule["action"] for rule in permissions[1:]
                           if rule["effect"] == "allow"]
                self.assertEqual(actions, EXPECTED_TOOLS[role])

    def test_eval_runs_the_role_with_agent_and_removes_the_role_file_without(self) -> None:
        code, out = self.eval()
        self.assertEqual(code, 0, out)
        calls = self.calls()
        self.assertEqual(len(calls), 2, calls)
        with_call = next(call for call in calls if "--agent" in call["argv"])
        without_call = next(call for call in calls if "--agent" not in call["argv"])
        self.assertIn("run", with_call["argv"])
        self.assertEqual(with_call["argv"][with_call["argv"].index("--agent") + 1], "tester")
        self.assertEqual(with_call["argv"][with_call["argv"].index("--model") + 1],
                         "opencode-go/beam-free")
        self.assertIn("--format", with_call["argv"])
        self.assertIn("json", with_call["argv"])
        self.assertIn(ROLE_FILE, with_call["files"])
        self.assertNotIn(ROLE_FILE, without_call["files"])

    def test_eval_reads_the_final_message_as_the_report(self) -> None:
        code, out = self.eval("--variant", "with")
        self.assertEqual(code, 0, out)
        run = self.runs()[0]
        self.assertTrue(all(check["pass"] for check in run["checks"]), run)
        self.assertTrue(run["usage"].get("transcript", "").endswith(".out"))

    def test_parser_reads_one_step(self) -> None:
        usage = self.parser().parse((FIXTURES / "one_step.jsonl").read_text(encoding="utf-8"),
                                    {}, None)
        self.assertEqual(usage["report"], "REPORT ONE")
        self.assertEqual(usage["cost_usd"], 0.001)
        self.assertEqual(usage["turns"], 1)
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 2)
        self.assertEqual(usage["reasoning_tokens"], 1)
        self.assertEqual(usage["cache_read_tokens"], 5)
        self.assertEqual(usage["cache_write_tokens"], 1)

    def test_parser_joins_the_last_message_and_counts_tools(self) -> None:
        parser = self.parser()
        text = (FIXTURES / "many_steps.jsonl").read_text(encoding="utf-8")
        usage = parser.parse(text, {}, None)
        self.assertEqual(usage["report"], "Final report")
        self.assertEqual(usage["cost_usd"], 0.003)
        self.assertEqual(usage["turns"], 2)
        self.assertEqual(usage["input_tokens"], 30)
        self.assertEqual(usage["output_tokens"], 6)
        self.assertEqual(usage["reasoning_tokens"], 1)
        self.assertEqual(usage["cache_read_tokens"], 10)
        self.assertEqual(usage["cache_write_tokens"], 2)
        self.assertEqual(parser.transcript_stats(FIXTURES / "many_steps.jsonl"), (1, 6))

    def test_parser_leaves_out_a_cost_that_is_missing(self) -> None:
        missing = self.parser().parse(
            (FIXTURES / "missing_cost.jsonl").read_text(encoding="utf-8"), {}, None)
        self.assertEqual(missing["report"], "NO COST")
        self.assertNotIn("cost_usd", missing)

    def test_parser_keeps_a_zero_cost(self) -> None:
        zero = self.parser().parse((FIXTURES / "bad_line.jsonl").read_text(encoding="utf-8"),
                                   {}, None)
        self.assertEqual(zero["report"], "STILL PARSED")
        self.assertEqual(zero["cost_usd"], 0.0)
        self.assertEqual(zero["input_tokens"], 2)

    def test_transcript_counts_a_tool_with_no_output(self) -> None:
        stats = self.parser().transcript_stats(FIXTURES / "tool_no_output.jsonl")
        self.assertEqual(stats, (1, 0))

    def test_unsupported_evals_print_the_adapter_reason_and_start_no_harness(self) -> None:
        cases = {
            "guidance.writing": "did not prove a guidance run",
            "trigger.issue-opened.single-ticket": "did not prove a trigger run",
        }
        for component, reason in cases.items():
            with self.subTest(component=component):
                code, out = self.component(component)
                self.assertEqual(code, 2, out)
                self.assertIn(reason, out)
                self.no_harness_started()

    def test_same_adapter_does_not_fall_back_from_a_missing_model_profile(self) -> None:
        self.write(".cornerstone/config.yaml", CONFIG.replace(
            "model_profile: opencode-default", "model_profile: nope"))
        code, out = self.component("role.tester")
        self.assertEqual(code, 2, out)
        self.assertIn("nope", out)
        self.no_harness_started()
        with self.assertRaises(evals.EvalError) as caught:
            evals._model_profile(ADAPTER, "nope", allow_fallback=False)
        message = str(caught.exception)
        self.assertIn("opencode", message)
        self.assertIn("nope", message)
        self.assertIn("set model_profile", message)

    def test_load_parser_rejects_a_missing_file(self) -> None:
        with self.assertRaises(evals.EvalError) as caught:
            evals.load_parser(EVAL_YAML, ADAPTER, {"parser": "parsers/nope.py"})
        self.assertIn("does not exist", str(caught.exception))

    def test_load_parser_rejects_a_file_with_no_parse(self) -> None:
        run_config = self.write("parser-errors/eval.yaml", "")
        self.write("parser-errors/no_parse.py", "def transcript_stats(path):\n    return None\n")
        with self.assertRaises(evals.EvalError) as caught:
            evals.load_parser(run_config, ADAPTER, {"parser": "no_parse.py"})
        self.assertIn("no 'parse' function", str(caught.exception))

    def test_load_parser_rejects_a_file_with_no_transcript_stats(self) -> None:
        run_config = self.write("parser-errors/eval.yaml", "")
        self.write("parser-errors/no_stats.py", "def parse(stdout, fields, where):\n    return {}\n")
        with self.assertRaises(evals.EvalError) as caught:
            evals.load_parser(run_config, ADAPTER, {"parser": "no_stats.py"})
        self.assertIn("no 'transcript_stats' function", str(caught.exception))

    def test_missing_parser_exits_2_and_starts_no_harness(self) -> None:
        config = evals.load_run_config(EVAL_YAML)
        config["parser"] = "parsers/nope.py"
        path = self.write("missing-parser.yaml", yaml.safe_dump(config, sort_keys=False))
        code, out = self.eval("--check-only", "--run-config", str(path))
        self.assertEqual(code, 2, out)
        self.assertIn("does not exist", out)
        self.no_harness_started()

    def test_run_config_selects_the_adapter_and_its_model_profile(self) -> None:
        claude = CONFIG.replace("harness: opencode", "harness: claude-code").replace(
            "model_profile: opencode-default", "model_profile: claude-5")
        self.write(".cornerstone/config.yaml", claude)
        self.write("evals/role-tester/fixtures/rendered/.cornerstone/config.yaml", claude)
        self.write("evals/role-tester/scenarios.yaml", yaml.safe_dump({
            "component": "role.tester",
            "role": "tester",
            "task": "Write tests for this ticket.",
            "scenarios": [{
                "id": "O3",
                "fixture": "fixtures/rendered",
                "prompt": "Do the job.",
                "expect": [{"check": "file_exists", "path": ROLE_FILE}],
            }],
        }, sort_keys=False))
        code, out = self.eval("--variant", "with", "--run-config", str(EVAL_YAML))
        self.assertEqual(code, 0, out)
        call = self.calls()[0]
        self.assertIn(ROLE_FILE, call["files"])
        result = next((self.root / "evals/results").glob("*.md"))
        self.assertIn("Harness: `opencode`.", result.read_text(encoding="utf-8"))

    def test_render_refuses_an_eval_only_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            (root / ".cornerstone").mkdir(parents=True)
            (root / ".cornerstone" / "config.yaml").write_text(CONFIG, encoding="utf-8")
            with self.assertRaises(render.RenderError) as caught:
                render.render(root, FRAMEWORK)
            self.assertIn("eval-only", str(caught.exception))

    def test_eval_renders_the_role_file_for_an_eval_only_adapter(self) -> None:
        self.write("evals/role-tester/fixtures/rendered/.cornerstone/config.yaml", CONFIG)
        self.write("evals/role-tester/scenarios.yaml", yaml.safe_dump({
            "component": "role.tester",
            "role": "tester",
            "task": "Write tests for this ticket.",
            "scenarios": [{
                "id": "O2",
                "fixture": "fixtures/rendered",
                "prompt": "Do the job.",
                "expect": [
                    {"check": "file_exists", "path": ROLE_FILE},
                    {"check": "matches", "path": ROLE_FILE, "pattern": "You are the tester"},
                ],
            }],
        }, sort_keys=False))
        code, out = self.eval("--variant", "with")
        self.assertEqual(code, 0, out)
        call = self.calls()[0]
        self.assertIn(ROLE_FILE, call["files"])

    def test_check_components_accepts_eval_only_with_no_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            framework = Path(tmp) / "framework"
            (framework / "adapters" / "h").mkdir(parents=True)
            (framework / "adapters" / "h" / "components.yaml").write_text(
                "status: eval-only\ncomponents:\n  - id: role.tester\n    kind: role\n"
                "    eval: evals/role-tester/\n", encoding="utf-8")
            self.assertEqual(framework_check.check_components(Path(tmp), framework), [])

    def test_summary_records_the_harness_and_the_model(self) -> None:
        text = evals.summary("role.tester", "opencode-go/beam-free",
                             [evals.Run("T1", "with", 1)], "opencode")
        self.assertIn("Harness: `opencode`.", text)
        self.assertIn("Model: `opencode-go/beam-free`.", text)


if __name__ == "__main__":
    unittest.main()
