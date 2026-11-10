"""Independent tests for issue #303: the eval-only OpenCode adapter.

Written from the ticket. Each test name holds the acceptance criterion (AC1 to AC9).
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
from test_eval_opencode import eval_only_framework

REPO = Path(__file__).resolve().parents[2]
FRAMEWORK = REPO / "framework"
OC = FRAMEWORK / "adapters" / "opencode"
CC = FRAMEWORK / "adapters" / "claude-code"
OC_EVAL = OC / "eval.yaml"
ROLES = ["shaper", "planner", "implementer", "tester", "reviewer", "investigator"]
# Claude Code tool name -> OpenCode action (the neutral meaning of each tool).
TOOL_MAP = {"Read": "read", "Grep": "grep", "Glob": "glob", "Bash": "shell",
            "Write": "edit", "Edit": "edit"}

CONFIG = """framework_version: 1.6.0
harness: opencode
model_profile: opencode-default
profiles: [single-ticket]
branches: {integration: main, main: main}
commands: {install: "true", test_unit: "true", all_checks: "true"}
paths: {tests: [tests/], checks: [.cornerstone/checks/], plans: docs/plans/}
owners: {default: eval}
"""


def split_frontmatter(text: str) -> tuple[dict, str]:
    parts = text.split("---\n", 2)
    return parts[1], parts[2]


def fm_lines(front: str) -> dict:
    return dict(re.findall(r"^(\w+):\s*(.*)$", front, re.M))


def run_jsonl(*events: dict | str) -> str:
    return "\n".join(e if isinstance(e, str) else json.dumps(e) for e in events) + "\n"


def step(cost=None, inp=1, out=1, reasoning=0, cache=None, drop_tokens=False) -> dict:
    part: dict = {"type": "step-finish", "reason": "stop"}
    if cost is not None:
        part["cost"] = cost
    if not drop_tokens:
        tokens = {"input": inp, "output": out, "reasoning": reasoning}
        if cache is not None:
            tokens["cache"] = cache
        part["tokens"] = tokens
    return {"type": "step_finish", "part": part}


def text(message: str, body: str) -> dict:
    return {"type": "text", "part": {"type": "text", "messageID": message, "text": body}}


class Ac1MappingTest(unittest.TestCase):
    def test_ac1_mapping_table_has_support_level_for_each_row(self) -> None:
        doc = (FRAMEWORK / "adapters" / "opencode.md").read_text(encoding="utf-8")
        rows = [line for line in doc.splitlines() if line.startswith("|")]
        header = next(r for r in rows if r.lower().startswith("| concept"))
        cols = [c.strip().lower() for c in header.strip("|").split("|")]
        self.assertIn("support", cols)
        idx = cols.index("support")
        levels = set()
        for row in rows[rows.index(header) + 2:]:
            cells = [c.strip() for c in row.strip("|").split("|")]
            if len(cells) != len(cols):
                break
            levels.add(cells[idx].split()[0])
        self.assertTrue(levels, "no mapping rows")
        self.assertLessEqual(levels, {"full", "partial", "none"})

    def test_ac1_mapping_covers_each_concept_of_the_contract(self) -> None:
        contract = (FRAMEWORK / "adapters" / "contract.md").read_text(encoding="utf-8")
        start = contract.index("## What a harness adapter MUST provide")
        end = contract.index("### Adapter template values")
        table = [l for l in contract[start:end].splitlines() if l.startswith("|")]
        concepts = [l.strip("|").split("|")[0].strip() for l in table[2:]]
        concepts = [c for c in concepts if c]
        doc = (FRAMEWORK / "adapters" / "opencode.md").read_text(encoding="utf-8").lower()
        self.assertGreaterEqual(len(concepts), 5)
        for concept in concepts:
            # Compare on the first two words; the OpenCode table may phrase a concept longer.
            key = re.sub(r"\s*\(.*", "", concept.lower()).split()[0]
            self.assertIn(key, doc, f"concept missing from opencode.md: {concept}")

    def test_ac1_unproven_facts_are_marked(self) -> None:
        doc = (FRAMEWORK / "adapters" / "opencode.md").read_text(encoding="utf-8")
        self.assertIn("[TO CONFIRM]", doc)


class Ac2StatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        (self.root / ".cornerstone").mkdir(parents=True)
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG, encoding="utf-8")
        self.eval_only = eval_only_framework(Path(self.tmp.name) / "eval-only-fw")

    def test_ac2_contract_documents_eval_only(self) -> None:
        contract = (FRAMEWORK / "adapters" / "contract.md").read_text(encoding="utf-8")
        self.assertIn("eval-only", contract)

    def test_ac2_render_api_refuses_with_clear_message_and_writes_nothing(self) -> None:
        with self.assertRaises(render.RenderError) as caught:
            render.render(self.root, self.eval_only)
        message = str(caught.exception)
        self.assertIn("eval-only", message)
        self.assertIn("opencode", message)
        self.assertFalse((self.root / ".opencode").exists())
        self.assertFalse((self.root / ".cornerstone" / "manifest.yaml").exists())

    def test_ac2_render_cli_exits_nonzero_with_message(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(["render", "--root", str(self.root),
                                 "--framework", str(self.eval_only)])
            except SystemExit as exit_:
                code = exit_.code
        self.assertNotEqual(code, 0)
        self.assertIn("eval-only", out.getvalue())

    def test_ac2_render_check_mode_also_refuses(self) -> None:
        with self.assertRaises(render.RenderError):
            render.build_components(self.eval_only, {"harness": "opencode",
                                                "model_profile": "opencode-default"})

    def test_ac2_full_adapter_still_renders(self) -> None:
        config = CONFIG.replace("opencode", "claude-code").replace(
            "claude-code-default", "claude-5")
        (self.root / ".cornerstone" / "config.yaml").write_text(config, encoding="utf-8")
        render.render(self.root, FRAMEWORK)
        self.assertTrue((self.root / ".claude" / "agents" / "tester.md").exists())

    def _check(self, components_yaml: str) -> list:
        framework = Path(self.tmp.name) / "fw"
        (framework / "adapters" / "h").mkdir(parents=True)
        (framework / "adapters" / "h" / "components.yaml").write_text(components_yaml,
                                                                      encoding="utf-8")
        return framework_check.check_components(Path(self.tmp.name), framework)

    def test_ac2_check_needs_no_templates_for_eval_only(self) -> None:
        findings = self._check("status: eval-only\ncomponents:\n  - id: role.x\n    kind: role\n"
                               "    target: .h/x.md\n    template: agents/missing.md\n"
                               "    eval: evals/role-x/\n")
        self.assertEqual(findings, [])

    def test_ac2_check_rejects_unknown_status(self) -> None:
        findings = self._check("status: bogus\ncomponents: []\n")
        self.assertEqual(len(findings), 1)
        self.assertIn("bogus", findings[0].message)

    def test_ac2_check_still_requires_eval_plan_in_eval_only(self) -> None:
        findings = self._check("status: eval-only\ncomponents:\n  - id: role.x\n    kind: role\n")
        self.assertTrue(findings)

    def test_ac2_stone_check_passes_on_repo(self) -> None:
        findings = framework_check.run(REPO)
        errors = [f for f in findings if f.severity == "error"]
        self.assertEqual([str(f) for f in errors], [])


class Ac3RoleTemplateTest(unittest.TestCase):
    def test_ac3_each_eval_role_has_a_file(self) -> None:
        reg = yaml.safe_load((OC / "components.yaml").read_text(encoding="utf-8"))
        roles = {c["role"]: c for c in reg["components"] if c.get("kind") == "role"}
        self.assertEqual(set(roles), set(ROLES))
        for role, entry in roles.items():
            self.assertTrue((OC / "templates" / entry["template"]).is_file(), role)
            self.assertEqual(entry["target"], f".opencode/agents/{role}.md")
            self.assertTrue(entry.get("eval"))

    def test_ac3_body_text_matches_the_claude_code_template(self) -> None:
        for role in ROLES:
            _, oc_body = split_frontmatter(
                (OC / "templates" / "agents" / f"{role}.md").read_text(encoding="utf-8"))
            _, cc_body = split_frontmatter(
                (CC / "templates" / "agents" / f"{role}.md").read_text(encoding="utf-8"))
            oc_lines, cc_lines = oc_body.strip().splitlines(), cc_body.strip().splitlines()
            self.assertEqual(len(oc_lines), len(cc_lines), role)
            for oc_line, cc_line in zip(oc_lines, cc_lines):
                if oc_line != cc_line:
                    # Only the line that says how the harness enforces a path may differ.
                    self.assertRegex(cc_line, r"hook", f"{role}: {cc_line!r} vs {oc_line!r}")
                    self.assertRegex(oc_line, r"role text", f"{role}: {oc_line!r}")

    def test_ac3_description_matches_the_claude_code_template(self) -> None:
        for role in ROLES:
            oc = fm_lines(split_frontmatter(
                (OC / "templates" / "agents" / f"{role}.md").read_text(encoding="utf-8"))[0])
            cc = fm_lines(split_frontmatter(
                (CC / "templates" / "agents" / f"{role}.md").read_text(encoding="utf-8"))[0])
            self.assertEqual(oc["description"], cc["description"], role)

    def _allowed_actions(self, role: str) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            (root / ".cornerstone").mkdir(parents=True)
            (root / ".cornerstone" / "config.yaml").write_text(
                CONFIG.replace("[single-ticket]", "[single-ticket, spike, full-project]"),
                encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                render.render(root, FRAMEWORK)
            text = (root / ".opencode" / "agents" / f"{role}.md").read_text(encoding="utf-8")
        rules = yaml.safe_load(split_frontmatter(text)[0])["permissions"]
        self.assertEqual(rules[0]["effect"], "deny", f"{role}: must deny by default first")
        self.assertEqual(rules[0]["action"], "*")
        return {r["action"] for r in rules if r["effect"] == "allow"}

    def test_ac3_permissions_equal_the_tools_of_the_claude_code_template(self) -> None:
        for role in ROLES:
            front, _ = split_frontmatter(
                (CC / "templates" / "agents" / f"{role}.md").read_text(encoding="utf-8"))
            tools = [t.strip() for t in fm_lines(front)["tools"].split(",")]
            expected = {TOOL_MAP[t] for t in tools if t in TOOL_MAP}
            if "$shaper_tools" in tools or any("$" in t for t in tools):
                continue  # the shaper tools depend on the ticket source; see next test
            self.assertEqual(self._allowed_actions(role), expected, role)

    def test_ac3_shaper_file_ticket_adds_edit_only_for_file_source(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ocv2", OC / "values.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plain = {r["action"] for r in json.loads(module.values({})["shaper_permissions"])
                 if r["effect"] == "allow"}
        filed = {r["action"] for r in json.loads(module.values(
            {"tickets": {"source": "file", "path": "t/"}})["shaper_permissions"])
                 if r["effect"] == "allow"}
        self.assertNotIn("edit", plain)
        self.assertIn("edit", filed)
        self.assertEqual(filed - {"edit"}, plain)

    def test_ac3_eval_yaml_tools_equal_role_file_permissions(self) -> None:
        tools = yaml.safe_load(OC_EVAL.read_text(encoding="utf-8"))["tools"]
        self.assertEqual(set(tools), set(ROLES))
        for role in ROLES:
            if role == "shaper":
                continue  # the shaper list is the file-ticket superset
            self.assertEqual(set(tools[role]), self._allowed_actions(role), role)

    def test_ac3_reviewer_cannot_edit(self) -> None:
        self.assertNotIn("edit", self._allowed_actions("reviewer"))
        self.assertNotIn("edit", yaml.safe_load(
            OC_EVAL.read_text(encoding="utf-8"))["tools"]["reviewer"])

    def test_ac3_planner_cannot_run_shell(self) -> None:
        self.assertNotIn("shell", self._allowed_actions("planner"))


class Ac4EvalYamlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data = yaml.safe_load(OC_EVAL.read_text(encoding="utf-8"))

    def test_ac4_role_run_commands_for_both_variants(self) -> None:
        for variant in ("with", "without"):
            argv = self.data["run"][variant]
            self.assertEqual(argv[0], "opencode")
            for token in ("$model", "$prompt"):
                self.assertIn(token, argv)
            self.assertIn("json", argv)
        self.assertIn("$role", self.data["run"]["with"])
        self.assertNotIn("$role", self.data["run"]["without"])

    def test_ac4_unproven_kinds_are_marked_unsupported_with_a_reason(self) -> None:
        for kind in ("guidance", "trigger"):
            self.assertNotIn(kind, self.data["run"])
            self.assertTrue(self.data["unsupported"][kind])

    def test_ac4_stone_eval_names_the_reason_for_an_unsupported_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            (root / ".cornerstone").mkdir(parents=True)
            (root / ".cornerstone" / "config.yaml").write_text(CONFIG, encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = cli.main(["eval", "guidance.nothing", "--root", str(root),
                                 "--framework", str(FRAMEWORK), "--run-config", str(OC_EVAL),
                                 "--check-only"])
            self.assertNotEqual(code, 0)
            self.assertIn("guidance", out.getvalue())
            self.assertIn(self.data["unsupported"]["guidance"], out.getvalue())


class ParserTest(unittest.TestCase):
    def parse(self, stdout: str) -> dict:
        parser = evals.load_parser(OC_EVAL, OC, evals.load_run_config(OC_EVAL))
        return parser.parse(stdout, {})

    # AC6
    def test_ac6_one_step(self) -> None:
        usage = self.parse(run_jsonl(text("m1", "hello"),
                                     step(cost=0.5, inp=7, out=3, reasoning=2,
                                          cache={"read": 4, "write": 1})))
        self.assertEqual(usage["report"], "hello")
        self.assertEqual(usage["turns"], 1)
        self.assertEqual(usage["cost_usd"], 0.5)
        self.assertEqual(usage["input_tokens"], 7)
        self.assertEqual(usage["output_tokens"], 3)

    def test_ac6_many_steps_sum(self) -> None:
        usage = self.parse(run_jsonl(step(cost=0.25, inp=1, out=2), text("m1", "a"),
                                     step(cost=0.5, inp=10, out=20), text("m2", "last"),
                                     step(cost=0.25, inp=100, out=200)))
        self.assertEqual(usage["turns"], 3)
        self.assertAlmostEqual(usage["cost_usd"], 1.0)
        self.assertEqual(usage["input_tokens"], 111)
        self.assertEqual(usage["output_tokens"], 222)
        self.assertEqual(usage["report"], "last")

    def test_ac6_cost_zero_is_zero_not_missing(self) -> None:
        usage = self.parse(run_jsonl(text("m", "x"), step(cost=0)))
        self.assertIn("cost_usd", usage)
        self.assertEqual(usage["cost_usd"], 0)

    def test_ac6_missing_cost_is_absent(self) -> None:
        usage = self.parse(run_jsonl(text("m", "x"), step(cost=None)))
        self.assertNotIn("cost_usd", usage)
        self.assertEqual(usage["turns"], 1)

    def test_ac6_partial_cost_sums_the_present_values(self) -> None:
        usage = self.parse(run_jsonl(step(cost=None), step(cost=0.5)))
        self.assertEqual(usage["cost_usd"], 0.5)

    def test_ac6_missing_tokens_are_absent_not_zero(self) -> None:
        usage = self.parse(run_jsonl(step(cost=0.1, drop_tokens=True)))
        self.assertNotIn("input_tokens", usage)
        self.assertNotIn("output_tokens", usage)

    def test_ac6_bad_line_is_skipped(self) -> None:
        usage = self.parse(run_jsonl("not json at all", "{broken", "[1,2]", "42",
                                     text("m", "ok"), step(cost=0.1, inp=5)))
        self.assertEqual(usage["report"], "ok")
        self.assertEqual(usage["input_tokens"], 5)

    def test_ac6_empty_and_garbage_output_gives_no_metrics_and_no_crash(self) -> None:
        self.assertEqual(self.parse(""), {})
        self.assertEqual(self.parse("garbage\n\n"), {})

    def test_ac6_bool_cost_is_not_a_number(self) -> None:
        usage = self.parse(run_jsonl(step(cost=True)))
        self.assertNotIn("cost_usd", usage)

    def test_ac6_report_is_last_message_only(self) -> None:
        usage = self.parse(run_jsonl(text("m1", "first"), text("m2", "se"), text("m2", "cond")))
        self.assertEqual(usage["report"], "second")

    def _stats(self, body: str):
        parser = evals.load_parser(OC_EVAL, OC, evals.load_run_config(OC_EVAL))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text(body, encoding="utf-8")
            return parser.transcript_stats(path)

    def test_ac6_tool_calls_and_bytes(self) -> None:
        body = run_jsonl(
            {"type": "tool_use", "part": {"tool": "read", "state": {"output": "abc"}}},
            {"type": "tool_use", "part": {"tool": "bash", "state": {"output": "héllo"}}},
            text("m", "not a tool"), "junk")
        self.assertEqual(self._stats(body), (2, 3 + len("héllo".encode("utf-8"))))

    def test_ac6_tool_without_output_counts_as_a_call_of_zero_bytes(self) -> None:
        body = run_jsonl({"type": "tool_use", "part": {"tool": "read", "state": {}}})
        self.assertEqual(self._stats(body), (1, 0))

    def test_ac6_no_tools_is_zero_zero(self) -> None:
        self.assertEqual(self._stats(run_jsonl(text("m", "x"))), (0, 0))

    def test_ac6_missing_transcript_gives_none(self) -> None:
        parser = evals.load_parser(OC_EVAL, OC, evals.load_run_config(OC_EVAL))
        self.assertIsNone(parser.transcript_stats(Path("/nonexistent/zzz.jsonl")))

    def test_ac6_table_shows_dash_for_missing_fields(self) -> None:
        run = evals.Run("S1", "with", 1)
        run.usage = {"report": "x", "turns": 1}  # no cost, no tokens
        table = evals.summary("role.tester", "m", [run], "opencode")
        self.assertIn("—", table)

    # AC5
    def test_ac5_every_eval_yaml_names_an_existing_parser(self) -> None:
        for path in sorted((FRAMEWORK / "adapters").glob("*/eval.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertIn("parser", data, path)
            self.assertTrue((path.parent / data["parser"]).is_file(), path)

    def test_ac5_parser_selected_by_run_config_differs_by_adapter(self) -> None:
        cc_cfg = CC / "eval.yaml"
        cc = evals.load_parser(cc_cfg, CC, evals.load_run_config(cc_cfg))
        oc = evals.load_parser(OC_EVAL, OC, evals.load_run_config(OC_EVAL))
        stdout = run_jsonl(text("m", "x"), step(cost=0.5, inp=3))
        self.assertIn("turns", oc.parse(stdout, {}))
        self.assertNotEqual(cc.parse, oc.parse)
        self.assertNotIn("turns", cc.parse(stdout, {}))

    def test_ac5_run_config_without_parser_keeps_the_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "eval.yaml"
            cfg.write_text("run: {with: [x], without: [x]}\n", encoding="utf-8")
            parser = evals.load_parser(cfg, Path(tmp), evals.load_run_config(cfg))
            self.assertEqual(parser.parse('{"a": 1}\n', {"n": "a"}), {"n": 1})

    def test_ac5_parser_key_must_be_a_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "eval.yaml"
            cfg.write_text("run: {with: [x]}\nparser: [a]\n", encoding="utf-8")
            with self.assertRaises(evals.EvalError):
                evals.load_run_config(cfg)

    def test_ac5_claude_parser_still_reads_a_result_event(self) -> None:
        cc_cfg = CC / "eval.yaml"
        cc = evals.load_parser(cc_cfg, CC, evals.load_run_config(cc_cfg))
        out = cc.parse('{"type":"result","result":"R","total_cost_usd":0.25}\n',
                       {"report": "result", "cost_usd": "total_cost_usd"},
                       {"type": "result"})
        self.assertEqual(out, {"report": "R", "cost_usd": 0.25})


FAKE = r'''#!/usr/bin/env python3
import json
print(json.dumps({"type": "text", "part": {"messageID": "m", "text": "REPORT"}}))
print(json.dumps({"type": "step_finish", "part": {"cost": 0.0,
      "tokens": {"input": 4, "output": 5}}}))
'''


class Ac7ResultFileTest(unittest.TestCase):
    def test_ac7_summary_records_harness_and_model(self) -> None:
        out = evals.summary("role.tester", "prov/model-x", [evals.Run("S", "with", 1)], "opencode")
        self.assertIn("opencode", out)
        self.assertIn("prov/model-x", out)

    def test_ac7_end_to_end_result_file_via_run_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            (base / "bin").mkdir()
            fake = base / "bin" / "opencode"
            fake.write_text(FAKE, encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            files = {
                ".cornerstone/config.yaml": CONFIG.replace("harness: opencode",
                                                           "harness: claude-code").replace(
                    "opencode-default", "claude-5"),
                "evals/role-tester/fixtures/f/.cornerstone/config.yaml": CONFIG,
                "evals/role-tester/scenarios.yaml": yaml.safe_dump({
                    "component": "role.tester", "role": "tester", "task": "t",
                    "scenarios": [{"id": "I1", "fixture": "fixtures/f", "prompt": "go",
                                   "expect": [{"check": "matches", "path": "@report",
                                               "pattern": "REPORT"}]}]}),
            }
            for rel, body in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(body, encoding="utf-8")
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"PATH": f"{base / 'bin'}{os.pathsep}"
                                                       f"{os.environ['PATH']}"}):
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                    code = cli.main(["eval", "role.tester", "--root", str(root),
                                     "--framework", str(FRAMEWORK), "--model", "p/m-1",
                                     "--variant", "with", "--run-config", str(OC_EVAL)])
            self.assertEqual(code, 0, out.getvalue())
            result = next((root / "evals/results").glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("opencode", result)
            self.assertIn("p/m-1", result)
            # The OpenCode parser read the tokens (the default parser would show dashes).
            self.assertRegex(result, r"\b4\b")

    def test_ac7_claude_code_run_records_its_harness(self) -> None:
        out = evals.summary("role.tester", "m", [evals.Run("S", "with", 1)], "claude-code")
        self.assertIn("claude-code", out)


class Ac8NeutralCoreTest(unittest.TestCase):
    def test_ac8_core_docs_do_not_name_the_harness(self) -> None:
        offenders = []
        for path in FRAMEWORK.rglob("*.md"):
            if "adapters" in path.relative_to(FRAMEWORK).parts:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"open\s*code", line, re.I):
                    offenders.append(f"{path.relative_to(REPO)}:{number}")
        self.assertEqual(offenders, [])

    def test_ac8_core_code_does_not_name_the_harness(self) -> None:
        offenders = []
        for path in (REPO / "stone" / "src" / "stone").rglob("*.py"):
            if re.search(r"opencode", path.read_text(encoding="utf-8"), re.I):
                offenders.append(path.name)
        self.assertEqual(offenders, [])

    def test_ac8_neutral_checks_pass(self) -> None:
        self.assertEqual(framework_check.check_neutral(FRAMEWORK), [])
        self.assertEqual(framework_check.check_neutral_code(REPO / "stone" / "src" / "stone"), [])


class Ac9DecisionTest(unittest.TestCase):
    def test_ac9_decision_record_has_reason_options_risks_review_date(self) -> None:
        doc = (FRAMEWORK / "adapters" / "opencode.md").read_text(encoding="utf-8")
        section = doc[doc.index("## Decision record"):]
        for field in ("Reason", "Options", "Risks", "Review"):
            self.assertRegex(section, rf"\|\s*{field}\s*\|")
        self.assertRegex(section, r"\d{4}-\d{2}-\d{2}")

    def test_ac9_framework_log_has_the_decision(self) -> None:
        readme = (FRAMEWORK / "README.md").read_text(encoding="utf-8")
        self.assertRegex(readme, r"\| D112 \|.*eval-only.*Review it by \d{4}-\d{2}-\d{2}")


if __name__ == "__main__":
    unittest.main()
