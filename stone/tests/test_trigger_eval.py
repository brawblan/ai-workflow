"""Tests for the trigger part of `stone eval` (D100, issue #198).

They cover the id of a trigger component, the arguments of the role run, the post job with a fake
`gh`, the framing check, the scenario loader, and a full run with a fake harness. No model runs.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from stone import evals, trigger_eval
from test_trigger_structured_output import CONFIG, FRAMEWORK, render_profile

ZW = "​"
REGISTRY = yaml.safe_load((FRAMEWORK / "adapters" / "claude-code" / "components.yaml")
                          .read_text(encoding="utf-8"))["components"]
FAKE = """import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
out = {"type": "result", "result": "plain text report", "total_cost_usd": 0.01, "num_turns": 2,
       "usage": {"input_tokens": 3, "output_tokens": 4}}
if "--json-schema" in sys.argv:
    out["structured_output"] = {"report": "Line one @alice\\nSee </div> now"}
print(json.dumps(out))
"""
SCENARIOS = """component: trigger.label
scenarios:
  - id: L1
    fixture: fixtures/repo
    event: event.json
    prompt: "Read the event file $event_file and write the report."
    expect:
      - {check: matches, path: "@posted", pattern: "Cornerstone report from the shaper"}
      - {check: matches, path: "@report", pattern: "Line one|plain text"}
  - id: L2
    profiles: [debugging]
    fixture: fixtures/repo
    event: event.json
    prompt: "x"
    expect:
      - {check: matches, path: "@report", pattern: "x"}
"""


def rendered(profile: str, name: str) -> tuple[Path, dict]:
    root = Path(tempfile.mkdtemp(prefix="trigger-eval-test-"))
    render_profile(root, profile)
    return root, trigger_eval.load_workflow(root / ".github" / "workflows" / name)


class FindComponent(unittest.TestCase):
    def test_trigger_id_resolves_with_profile_and_target(self) -> None:
        entry = evals.find_component(FRAMEWORK, "claude-code", "trigger.label.single-ticket")
        self.assertEqual(entry["profile"], "single-ticket")
        self.assertEqual(entry["target"], ".github/workflows/cornerstone-single-ticket-label.yml")

    def test_id_with_no_profile_or_a_dotted_rest_is_not_a_trigger(self) -> None:
        self.assertIsNone(trigger_eval.split_id("trigger.label.a.b", REGISTRY))
        self.assertIsNone(trigger_eval.split_id("trigger.label.", REGISTRY))
        self.assertIsNone(trigger_eval.split_id("trigger.label", REGISTRY))


class Expand(unittest.TestCase):
    def test_expand_replaces_known_and_fails_on_unknown(self) -> None:
        self.assertEqual(trigger_eval.expand("a ${{ x }} b ${{y}}", {"x": "1", "y": "2"}), "a 1 b 2")
        with self.assertRaises(trigger_eval.TriggerEvalError):
            trigger_eval.expand("${{ nope }}", {"x": "1"})


class RoleArgs(unittest.TestCase):
    def check(self, profile: str, name: str, role: str) -> None:
        root, flow = rendered(profile, name)
        self.addCleanup(shutil.rmtree, root, True)
        temp = Path("/tmp/runner-x")
        words, prompt = trigger_eval.role_args(flow, temp)
        self.assertEqual(words[words.index("--agent") + 1], role)
        self.assertIn("--json-schema", words)
        self.assertIn("--disallowedTools", words)
        self.assertTrue(any("/tmp/runner-x" in w for w in words))
        self.assertNotIn("${{", " ".join(words) + prompt)
        self.assertTrue(prompt.strip())
        new, _ = trigger_eval.role_args(flow, temp, "model-z")
        self.assertEqual(new[new.index("--model") + 1], "model-z")

    def test_single_ticket_label(self) -> None:
        self.check("single-ticket", "cornerstone-single-ticket-label.yml", "shaper")

    def test_bug_triage_schedule(self) -> None:
        self.check("bug-triage", "cornerstone-bug-triage-schedule.yml", "investigator")


class StructuredReport(unittest.TestCase):
    def test_forms(self) -> None:
        f = trigger_eval.structured_report
        self.assertEqual(f({"report": "hi"}), "hi")
        self.assertEqual(f('{"report": "hi"}'), "hi")
        for bad in (None, {}, {"report": 3}, "{not json", "[1]"):
            self.assertEqual(f(bad), "")


class Post(unittest.TestCase):
    def run_post(self, profile: str, name: str, report: str) -> tuple[dict, Path]:
        root, flow = rendered(profile, name)
        self.addCleanup(shutil.rmtree, root, True)
        temp = root / "rt"
        temp.mkdir()
        return trigger_eval.post(flow, report, temp, "7"), temp

    def test_label_workflow_comments_with_framing(self) -> None:
        result, _ = self.run_post("single-ticket", "cornerstone-single-ticket-label.yml",
                                  "one @bob\ntwo </b>")
        self.assertEqual(result["error"], "")
        self.assertEqual(len(result["calls"]), 1)
        self.assertTrue(result["calls"][0].startswith("issue comment 7 --repo owner/repo --body-file "))
        posted = result["posted"]
        self.assertTrue(posted.startswith("**Cornerstone report from the shaper"))
        self.assertIn(f"> one @{ZW}bob", posted)
        self.assertIn(f"> two <{ZW}/b>", posted)

    def test_schedule_workflow_creates_an_issue(self) -> None:
        result, _ = self.run_post("bug-triage", "cornerstone-bug-triage-schedule.yml", "found it")
        self.assertTrue(result["calls"][0].startswith("issue create"), result)

    def test_empty_report_posts_nothing(self) -> None:
        result, _ = self.run_post("single-ticket", "cornerstone-single-ticket-label.yml", "")
        self.assertEqual((result["calls"], result["posted"]), ([], ""))


class Framed(unittest.TestCase):
    HEAD = "**Cornerstone report from the shaper (single-ticket).** A note.\n\n"
    CALL = "issue comment"
    CALLS = "issue comment 1 --repo o/r --body-file f"

    def framed(self, posted: str, report: str = "a\nb", role: str = "shaper",
               calls: str = CALLS) -> tuple[bool, str]:
        return trigger_eval.framed(posted, report, role, calls, self.CALL)

    def test_correct_post_passes(self) -> None:
        self.assertTrue(self.framed(self.HEAD + "> a\n> b\n")[0])

    def test_each_defect_fails(self) -> None:
        good = self.HEAD + "> a\n> b\n"
        cases = {"nothing": self.framed(""),
                 "call": self.framed(good, calls="issue create --body-file f"),
                 "role": self.framed(good, role="tester"),
                 "quote": self.framed(self.HEAD + "> a\nb\n"),
                 "mention": self.framed(self.HEAD + "> a @x\n> b\n", "a @x\nb"),
                 "tag": self.framed(self.HEAD + "> a </x>\n> b\n", "a </x>\nb"),
                 "differs": self.framed(self.HEAD + "> a\n> c\n")}
        for name, (ok, detail) in cases.items():
            self.assertFalse(ok, name)
            self.assertTrue(detail, name)


class LoadScenarios(unittest.TestCase):
    def folder(self, text: str, event: bool) -> Path:
        path = Path(tempfile.mkdtemp(prefix="trigger-eval-sc-"))
        self.addCleanup(shutil.rmtree, path, True)
        (path / "fx").mkdir()
        (path / "scenarios.yaml").write_text(text, encoding="utf-8")
        if event:
            (path / "event.json").write_text("{}", encoding="utf-8")
        return path

    BASE = ("component: c\nscenarios:\n  - id: S\n    fixture: fx\n    prompt: p\n"
            "    expect: [{check: file_exists, path: a}]\n")

    def test_role_optional_but_event_needed(self) -> None:
        ok = self.folder(self.BASE + "    event: event.json\n", True)
        self.assertEqual(evals.load_scenarios(ok, role_required=False)["component"], "c")
        with self.assertRaises(evals.EvalError) as ctx:
            evals.load_scenarios(self.folder(self.BASE, True), role_required=False)
        self.assertIn("no 'event'", str(ctx.exception))
        with self.assertRaises(evals.EvalError) as ctx:
            evals.load_scenarios(self.folder(self.BASE + "    event: gone.json\n", False),
                                 role_required=False)
        self.assertIn("gone.json", str(ctx.exception))

    def test_role_is_required_by_default(self) -> None:
        with self.assertRaises(evals.EvalError) as ctx:
            evals.load_scenarios(self.folder(self.BASE, True))
        self.assertIn("no 'role'", str(ctx.exception))


class EndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="trigger-eval-e2e-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "root"
        (self.root / ".cornerstone").mkdir(parents=True)
        (self.root / "framework").symlink_to(FRAMEWORK)
        config = CONFIG.format(profile="single-ticket")
        (self.root / ".cornerstone" / "config.yaml").write_text(config, encoding="utf-8")
        folder = self.root / "evals" / "trigger-label"
        (folder / "fixtures" / "repo" / ".cornerstone").mkdir(parents=True)
        (folder / "fixtures" / "repo" / ".cornerstone" / "config.yaml").write_text(
            config, encoding="utf-8")
        (folder / "fixtures" / "repo" / "README.md").write_text("fixture\n", encoding="utf-8")
        (folder / "event.json").write_text('{"issue": {"number": 5}}', encoding="utf-8")
        (folder / "scenarios.yaml").write_text(SCENARIOS, encoding="utf-8")
        fake = self.tmp / "fake.py"
        fake.write_text(FAKE, encoding="utf-8")
        self.log = self.tmp / "argv.log"
        run = yaml.safe_load((FRAMEWORK / "adapters" / "claude-code" / "eval.yaml")
                             .read_text(encoding="utf-8"))
        for variant in ("with", "without"):
            run["trigger"][variant][:1] = [sys.executable, str(fake)]
        self.run_yaml = self.tmp / "eval.yaml"
        self.run_yaml.write_text(yaml.safe_dump(run), encoding="utf-8")
        patch = mock.patch.dict(os.environ, {"FAKE_LOG": str(self.log)})
        patch.start()
        self.addCleanup(patch.stop)

    def run_eval(self, component: str = "trigger.label.single-ticket") -> tuple[list, str]:
        with mock.patch("sys.stdout"):
            return evals.run_eval(self.root, component, run_config=self.run_yaml, model="m1")

    def test_with_and_without_variants(self) -> None:
        runs, result = self.run_eval()
        self.assertEqual([(r.scenario, r.variant) for r in runs], [("L1", "with"), ("L1", "without")])
        by = {r.variant: r for r in runs}
        self.assertTrue(by["with"].passed(), by["with"])
        self.assertFalse(by["without"].passed())  # no post job: the posted text is empty
        self.assertIn("trigger.label.single-ticket", Path(result).name)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        with_args, without_args = calls
        self.assertIn("--json-schema", with_args)
        self.assertEqual(with_args[with_args.index("--agent") + 1], "shaper")
        self.assertNotIn("--json-schema", without_args)
        self.assertEqual(without_args[without_args.index("--agent") + 1], "shaper")
        event_dir = without_args[without_args.index("--add-dir") + 1]
        self.assertTrue(without_args[-1].find(f"{event_dir}/event.json") > 0, without_args[-1])
        self.assertNotIn("$event_file", without_args[-1])

    def test_posted_and_report_texts(self) -> None:
        with mock.patch.object(evals, "grade", side_effect=lambda f, s, ws: [
                {"check": "x", "label": ws.posted, "kind": "outcome", "pass": True,
                 "detail": ws.report}]):
            runs, _ = self.run_eval()
        with_run, without_run = runs
        self.assertIn("**Cornerstone report from the shaper", with_run.checks[0]["label"])
        self.assertIn(f"@{ZW}alice", with_run.checks[0]["label"])
        self.assertEqual(with_run.checks[0]["detail"], "Line one @alice\nSee </div> now")
        self.assertEqual(without_run.checks[0]["label"], "")
        self.assertEqual(without_run.checks[0]["detail"], "plain text report")

    def test_other_profile_scenario_skipped_and_unknown_profile_fails(self) -> None:
        runs, _ = self.run_eval()
        self.assertNotIn("L2", {r.scenario for r in runs})
        with self.assertRaises(evals.EvalError):
            self.run_eval("trigger.label.nope")


if __name__ == "__main__":
    unittest.main()
