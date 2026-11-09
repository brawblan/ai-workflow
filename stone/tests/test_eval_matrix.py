"""Tests for the model matrix of `stone eval` (#304): many models, `<harness>:<model>`, `--budget`,
and `--summary ... --by model`.

No real model starts. Fake `opencode` and `claude` programs on `PATH` record each call. The summary
tests read the fixture `fixtures/eval_matrix/runs.jsonl`.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from stone import cli, eval_matrix, evals

REPO = Path(__file__).resolve().parents[2]
FRAMEWORK = REPO / "framework"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "eval_matrix"
RUNS = FIXTURES / "runs.jsonl"

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

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
state = Path(os.environ["FAKE_STATE"])
state.mkdir(parents=True, exist_ok=True)
with (state / "calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"program": Path(sys.argv[0]).name, "argv": sys.argv[1:]}) + "\n")
print(json.dumps({"type": "text", "part": {"type": "text", "messageID": "m1", "text": "REPORT"}}))
print(json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "stop",
                  "cost": 0.0, "tokens": {"input": 1, "output": 1}}}))
'''


def fixture_run(variant: str, ok: bool, usage: dict, component: str = "c", harness: str = "h",
                model: str = "m") -> evals.Run:
    return evals.Run("S", variant, 1, checks=[{"check": "x", "kind": "outcome", "pass": ok}], usage=usage,
                     component=component, harness=harness, model=model)


def rounded(value):
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rounded(item) for item in value]
    return value


class MatrixTableTest(unittest.TestCase):
    """The table, built from fixture runs, without the CLI."""

    def rows(self) -> dict[tuple[str, str], dict]:
        found = eval_matrix.rows(evals.load_runs(RUNS))
        return {(row["component"], row["model"]): row for row in found}

    def test_one_row_for_each_component_and_model(self) -> None:
        self.assertEqual(set(self.rows()), {
            ("role.tester", "claude-code:m-big"), ("role.tester", "claude-code:m-none"),
            ("role.tester", "opencode:vendor/m-one"), ("role.reviewer", "opencode:vendor/m-one")})

    def test_two_harnesses_stay_apart_for_one_model_name(self) -> None:
        runs = [fixture_run("with", True, {}, harness="a"), fixture_run("with", True, {}, harness="b")]
        self.assertEqual([r["model"] for r in eval_matrix.rows(runs)], ["a:m", "b:m"])

    def test_without_variant_is_left_out(self) -> None:
        row = self.rows()[("role.tester", "claude-code:m-big")]
        self.assertEqual(row["runs"], 2)  # the fixture also has a "without" run with cost 9.0
        self.assertAlmostEqual(row["cost_usd"]["mean"], 0.2)
        only_base = [fixture_run("without", True, {}), fixture_run("none", True, {})]
        self.assertEqual(eval_matrix.rows(only_base), [])

    def test_means_and_standard_errors(self) -> None:
        row = self.rows()[("role.tester", "claude-code:m-big")]
        self.assertAlmostEqual(row["pass_rate"]["mean"], 0.5)
        self.assertAlmostEqual(row["pass_rate"]["se"], 0.5)
        for key, mean, error in (("cost_usd", 0.2, 0.1), ("turns", 5, 1), ("tool_bytes", 200, 100),
                                 ("seconds", 15, 5), ("input_tokens", 1500, 500),
                                 ("output_tokens", 200, 100)):
            with self.subTest(key=key):
                self.assertAlmostEqual(row[key]["mean"], mean)
                self.assertAlmostEqual(row[key]["se"], error)

    def test_cost_per_pass_is_total_cost_over_passing_runs(self) -> None:
        row = self.rows()[("role.tester", "claude-code:m-big")]
        self.assertAlmostEqual(row["cost_per_pass"], 0.4)  # (0.1 + 0.3) / 1 pass

    def test_cost_per_pass_with_two_passes(self) -> None:
        runs = [fixture_run("with", True, {"cost_usd": 0.1}),
                fixture_run("with", True, {"cost_usd": 0.2}),
                fixture_run("with", False, {"cost_usd": 0.3})]
        self.assertAlmostEqual(eval_matrix.rows(runs)[0]["cost_per_pass"], 0.3)

    def test_model_with_no_passing_run_has_no_cost_per_pass(self) -> None:
        row = self.rows()[("role.tester", "claude-code:m-none")]
        self.assertIsNone(row["cost_per_pass"])
        self.assertIn("| — |", eval_matrix.text([row], ["with"]))

    def test_run_with_no_cost_gives_no_cost_per_pass(self) -> None:
        runs = [fixture_run("with", True, {"cost_usd": 0.1}), fixture_run("with", True, {})]
        self.assertIsNone(eval_matrix.rows(runs)[0]["cost_per_pass"])

    def test_model_with_one_run_has_no_standard_error(self) -> None:
        row = self.rows()[("role.tester", "opencode:vendor/m-one")]
        self.assertIsNone(row["cost_usd"]["se"])
        text = eval_matrix.text([row], ["with"])
        self.assertIn("0.2000 ±—", text)
        self.assertIn("1.00 ±—", text)

    def test_missing_key_shows_a_dash_never_zero(self) -> None:
        text = eval_matrix.text(eval_matrix.rows([fixture_run("with", True, {})]), ["with"])
        row = next(line for line in text.splitlines() if line.startswith("| c "))
        self.assertIn("| — |", row)
        self.assertNotIn("0.0000", row)

    def test_token_note_is_in_the_text(self) -> None:
        text = eval_matrix.text(eval_matrix.rows(evals.load_runs(RUNS)), ["with"])
        self.assertIn(eval_matrix.TOKEN_NOTE, text)
        self.assertIn("tokenizer", eval_matrix.TOKEN_NOTE)


class SummaryCliTest(unittest.TestCase):
    def main(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["eval", "--root", str(FIXTURES), *argv])
        return code, out.getvalue()

    def test_golden_text_table(self) -> None:
        code, out = self.main("--summary", str(RUNS), "--by", "model")
        self.assertEqual(code, 0, out)
        self.assertEqual(out, (FIXTURES / "expected.txt").read_text(encoding="utf-8"))

    def test_golden_json(self) -> None:
        code, out = self.main("--summary", str(RUNS), "--by", "model", "--json")
        self.assertEqual(code, 0, out)
        expected = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
        self.assertEqual(rounded(json.loads(out)), rounded(expected))

    def test_json_has_rows_and_token_note(self) -> None:
        _, out = self.main("--summary", str(RUNS), "--by", "model", "--json")
        data = json.loads(out)
        self.assertEqual(len(data["rows"]), 4)
        self.assertEqual(data["token_note"], eval_matrix.TOKEN_NOTE)
        self.assertEqual(data["variants"], ["with"])

    def test_json_and_text_show_the_same_rows(self) -> None:
        _, text = self.main("--summary", str(RUNS), "--by", "model")
        _, out = self.main("--summary", str(RUNS), "--by", "model", "--json")
        for row in json.loads(out)["rows"]:
            self.assertIn(f"| {row['component']} | {row['model']} | {row['runs']} |", text)

    def test_several_summary_files_join_with_by(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            second = Path(tmp) / "runs.jsonl"
            run = evals.Run("S", "with", 1, checks=[{"kind": "outcome", "pass": True}], usage={"cost_usd": 1.0},
                            component="role.planner", harness="opencode", model="z")
            second.write_text(json.dumps(run.__dict__) + "\n", encoding="utf-8")
            code, out = self.main("--summary", str(RUNS), "--summary", str(second), "--by", "model",
                                  "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(json.loads(out)["rows"]), 5)

    def test_several_summary_without_by_exits_2(self) -> None:
        code, out = self.main("--summary", str(RUNS), "--summary", str(RUNS))
        self.assertEqual(code, 2, out)

    def test_json_without_by_exits_2(self) -> None:
        code, _ = self.main("--summary", str(RUNS), "--json")
        self.assertEqual(code, 2)

    def test_by_without_summary_exits_2(self) -> None:
        code, _ = self.main("role.tester", "--by", "model")
        self.assertEqual(code, 2)

    def test_json_without_summary_exits_2(self) -> None:
        code, _ = self.main("role.tester", "--json")
        self.assertEqual(code, 2)

    def test_summary_without_by_still_prints_the_old_tables(self) -> None:
        code, out = self.main("--summary", str(RUNS))
        self.assertEqual(code, 0, out)
        self.assertIn("| Scenario", out)

    def test_bad_runs_file_exits_2(self) -> None:
        code, _ = self.main("--summary", str(FIXTURES / "missing.jsonl"), "--by", "model")
        self.assertEqual(code, 2)


class FakeHarnessCase(unittest.TestCase):
    """A repo with fake harness programs. It has no test of its own."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "repo"
        self.state = self.base / "state"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.framework = FRAMEWORK
        self.write(".cornerstone/config.yaml", CONFIG)
        self.write("evals/role-tester/fixtures/basic/.opencode/agents/tester.md",
                   "---\ndescription: t\nmode: primary\n---\n\nWrite tests.\n")
        self.write("evals/role-tester/fixtures/basic/.claude/agents/tester.md",
                   "---\nname: tester\ndescription: t\n---\n\nWrite tests.\n")
        self.write("evals/role-tester/scenarios.yaml", yaml.safe_dump({
            "component": "role.tester", "role": "tester", "task": "Write tests.",
            "scenarios": [{"id": "O1", "fixture": "fixtures/basic", "prompt": "Do it.",
                           "expect": [{"check": "matches", "path": "@report",
                                       "pattern": "REPORT"}]}]}, sort_keys=False))
        for name in ("opencode", "claude"):
            fake = self.bin / name
            fake.write_text(FAKE, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        patcher = mock.patch.dict(os.environ, {
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_STATE": str(self.state)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, path: str, text: str) -> None:
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")

    def eval(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["eval", "role.tester", "--root", str(self.root),
                             "--framework", str(self.framework), *args])
        return code, out.getvalue()

    def calls(self) -> list[dict]:
        path = self.state / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def model_args(self) -> list[str]:
        return [c["argv"][c["argv"].index("--model") + 1] for c in self.calls()]

    def runs(self) -> list[dict]:
        folders = list((self.root / ".cornerstone/eval-runs").iterdir())
        self.assertEqual(len(folders), 1, folders)
        text = (folders[0] / "runs.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def results(self) -> list[Path]:
        return sorted((self.root / evals.RESULTS).glob("*.md"))


class ManyModelsTest(FakeHarnessCase):
    def test_each_model_runs_each_trial_and_has_a_result_file(self) -> None:
        code, out = self.eval("--model", "p/a", "--model", "p/b", "--variant", "with",
                              "--trials", "2")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(self.model_args()), ["p/a", "p/a", "p/b", "p/b"])
        files = self.results()
        self.assertEqual(len(files), 2)
        self.assertEqual({"p-a" in f.name for f in files}, {True, False})
        self.assertTrue(any("p-b" in f.name for f in files))

    def test_runs_jsonl_records_component_harness_and_model(self) -> None:
        self.eval("--model", "p/a", "--model", "p/b", "--variant", "with")
        rows = self.runs()
        self.assertEqual([(r["component"], r["harness"], r["model"]) for r in rows],
                         [("role.tester", "opencode", "p/a"), ("role.tester", "opencode", "p/b")])

    def test_many_models_print_the_matrix(self) -> None:
        _, out = self.eval("--model", "p/a", "--model", "p/b", "--variant", "with")
        self.assertIn("| Component | Model |", out)
        self.assertIn(eval_matrix.TOKEN_NOTE, out)

    def test_one_model_prints_no_matrix(self) -> None:
        _, out = self.eval("--model", "p/a", "--variant", "with")
        self.assertNotIn("| Component | Model |", out)

    def test_run_eval_takes_a_models_list(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            runs, result = evals.run_eval(self.root, "role.tester", framework=FRAMEWORK,
                                          models=["p/a", "p/b"], variant="with")
        self.assertEqual([r.model for r in runs], ["p/a", "p/b"])
        self.assertEqual(len(result.split(", ")), 2)

    def test_prefix_selects_that_adapter(self) -> None:
        self.eval("--model", "claude-code:sonnet", "--variant", "with")  # the fake output may fail a check
        self.assertEqual([c["program"] for c in self.calls()], ["claude"])
        self.assertEqual(self.model_args(), ["sonnet"])
        row = self.runs()[0]
        self.assertEqual((row["harness"], row["model"]), ("claude-code", "sonnet"))

    def test_no_prefix_uses_the_repo_config_harness(self) -> None:
        self.eval("--model", "p/a", "--variant", "with")
        self.assertEqual([c["program"] for c in self.calls()], ["opencode"])

    def test_two_harnesses_in_one_command(self) -> None:
        self.eval("--model", "p/a", "--model", "claude-code:sonnet", "--variant", "with")
        self.assertEqual([c["program"] for c in self.calls()], ["opencode", "claude"])

    def test_prefix_that_is_not_an_adapter_stays_in_the_model_id(self) -> None:
        self.assertEqual(evals.split_model(FRAMEWORK, "opencode-go:beam"), ("", "opencode-go:beam"))
        self.assertEqual(evals.split_model(FRAMEWORK, "claude-code:x:y"), ("claude-code", "x:y"))
        self.assertEqual(evals.split_model(FRAMEWORK, "plain"), ("", "plain"))
        self.eval("--model", "vendor:beam", "--variant", "with")
        self.assertEqual(self.model_args(), ["vendor:beam"])
        self.assertEqual([c["program"] for c in self.calls()], ["opencode"])

    def test_prefixed_model_with_run_config_exits_2(self) -> None:
        code, out = self.eval("--model", "claude-code:x", "--run-config",
                              str(FRAMEWORK / "adapters/opencode/eval.yaml"))
        self.assertEqual(code, 2, out)
        self.assertEqual(self.calls(), [])

    def test_plain_model_with_run_config_still_runs(self) -> None:
        code, out = self.eval("--model", "p/a", "--variant", "with", "--run-config",
                              str(FRAMEWORK / "adapters/opencode/eval.yaml"))
        self.assertEqual(code, 0, out)

    def test_bad_second_model_starts_no_harness(self) -> None:
        framework = self.base / "framework"
        shutil.copytree(FRAMEWORK, framework)
        shutil.rmtree(framework / "adapters" / "claude-code" / "models")
        self.framework = framework
        code, out = self.eval("--model", "p/a", "--model", "claude-code:x", "--variant", "with")
        self.assertEqual(code, 2, out)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.root / ".cornerstone/eval-runs").exists())


class BudgetNoteTest(FakeHarnessCase):
    NOTE = "has no cost limit"

    def test_opencode_with_budget_prints_the_note_before_the_first_run(self) -> None:
        code, out = self.eval("--model", "p/a", "--variant", "with", "--budget", "3")
        self.assertEqual(code, 0, out)
        self.assertIn(self.NOTE, out)
        self.assertLess(out.index(self.NOTE), out.index("O1 with 1"))

    def test_claude_code_with_budget_prints_no_note(self) -> None:
        _, out = self.eval("--model", "claude-code:s", "--variant", "with", "--budget", "3")
        self.assertNotIn(self.NOTE, out)
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "3")

    def test_no_budget_prints_no_note(self) -> None:
        _, out = self.eval("--model", "p/a", "--variant", "with")
        self.assertNotIn(self.NOTE, out)

    def test_note_covers_only_the_harness_without_a_limit(self) -> None:
        _, out = self.eval("--model", "p/a", "--model", "claude-code:s", "--variant", "with",
                           "--budget", "3")
        self.assertEqual(out.count(self.NOTE), 1)
        self.assertIn("'opencode'", out)
        self.assertNotIn("'claude-code'", out)

    def test_budget_default_is_5_for_claude_code(self) -> None:
        self.eval("--model", "claude-code:s", "--variant", "with")
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "5")


if __name__ == "__main__":
    unittest.main()
