"""Tests for the trigger part of `stone eval` (D101, issue #198).

They cover the id of a trigger component, the arguments of the role run, the post job with a fake
`gh`, the framing check, the scenario loader, and a full run with a fake harness. No model runs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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
if "--json-schema" in sys.argv and not os.environ.get("FAKE_NO_STRUCT"):
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


class ClosedPostEnv(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="trigger-eval-env-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def caller(self) -> dict[str, str]:
        rc = self.tmp / "rc.sh"
        rc.write_text("touch " + str(self.tmp / "bashenv-ran") + "\n", encoding="utf-8")
        real = self.tmp / "realbin"
        real.mkdir()
        (real / "gh").write_text(f"#!/bin/sh\ntouch {self.tmp}/real-gh-ran\n", encoding="utf-8")
        (real / "gh").chmod(0o755)
        return {"GITHUB_TOKEN": "real", "CLAUDE_CODE_OAUTH_TOKEN": "real", "BASH_ENV": str(rc),
                "BASH_FUNC_gh%%": "() { touch " + str(self.tmp / "func-ran") + "; }",
                "PATH": f"{real}{os.pathsep}{os.environ['PATH']}"}

    def test_step_env_is_closed(self) -> None:
        temp = self.tmp / "rt"
        with mock.patch.dict(os.environ, self.caller()):
            env = trigger_eval.step_env(temp, temp / "log", {"GH_TOKEN": "step", "X": "y"})
        for name in ("CLAUDE_CODE_OAUTH_TOKEN", "BASH_ENV"):
            self.assertNotIn(name, env)
        self.assertFalse([k for k in env if k.startswith("BASH_FUNC_")])
        self.assertEqual((env["GH_TOKEN"], env["GITHUB_TOKEN"]),
                         (trigger_eval.FAKE_TOKEN, trigger_eval.FAKE_TOKEN))
        self.assertEqual(env["X"], "y")
        config = Path(env["GH_CONFIG_DIR"])
        self.assertEqual((config.parent, list(config.iterdir())), (temp, []))
        folders = env["PATH"].split(os.pathsep)
        self.assertEqual(folders[0], str(temp / "bin"))
        self.assertEqual(folders.count(str(temp / "bin")), 1)
        # The system folders stay after the fake bin (the stub folder may stay too).
        self.assertIn(str(self.tmp / "realbin"), folders[1:])

    def test_real_gh_function_and_bash_env_do_not_run(self) -> None:
        root, flow = rendered("single-ticket", "cornerstone-single-ticket-label.yml")
        self.addCleanup(shutil.rmtree, root, True)
        temp = root / "rt"
        temp.mkdir()
        with mock.patch.dict(os.environ, self.caller()):
            result = trigger_eval.post(flow, "report", temp, "7")
        self.assertEqual(result["error"], "")
        self.assertEqual(len(result["calls"]), 1)
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.name.endswith("-ran")], [])

    def test_bash_folder_with_a_real_gh_still_posts_and_gh_does_not_run(self) -> None:
        # Like /usr/bin on Linux: the one folder with bash, the shell tools, and a real gh.
        real = self.tmp / "usrbin"
        real.mkdir()
        for tool in ("bash", "sh", "cat", "sed", "date", "mkdir", "printf", "env", "touch"):
            found = shutil.which(tool)
            if found:
                (real / tool).symlink_to(found)
        (real / "gh").write_text(f"#!/bin/sh\ntouch {self.tmp}/real-gh-ran\n", encoding="utf-8")
        (real / "gh").chmod(0o755)
        root, flow = rendered("single-ticket", "cornerstone-single-ticket-label.yml")
        self.addCleanup(shutil.rmtree, root, True)
        temp = root / "rt"
        temp.mkdir()
        with mock.patch.dict(os.environ, {"PATH": str(real)}):
            result = trigger_eval.post(flow, "report", temp, "7")
        self.assertEqual(result["error"], "")
        self.assertEqual(len(result["calls"]), 1)
        self.assertTrue(result["posted"].startswith("**Cornerstone report from the"), result)
        self.assertFalse((self.tmp / "real-gh-ran").exists())

    def test_post_names_bash_when_it_is_missing(self) -> None:
        root, flow = rendered("single-ticket", "cornerstone-single-ticket-label.yml")
        self.addCleanup(shutil.rmtree, root, True)
        temp = root / "rt"
        temp.mkdir()
        with mock.patch("shutil.which", return_value=None):
            result = trigger_eval.post(flow, "report", temp, "7")
        self.assertIn("bash", result["error"])
        self.assertEqual((result["posted"], result["calls"]), ("", []))

    def test_failed_post_step_names_the_step(self) -> None:
        flow = {"jobs": {"post": {"steps": [{"name": "Boom", "run": "exit 3"}]}}}
        temp = self.tmp / "rt"
        temp.mkdir()
        result = trigger_eval.post(flow, "report", temp, "1")
        self.assertIn("Boom", result["error"])
        self.assertEqual(result["posted"], "")


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

    def graded(self, **env: str) -> tuple[list, list]:
        seen: list = []

        def grab(folder, scenario, ws):
            seen.append((ws.posted, ws.gh_calls))
            return []
        with mock.patch.dict(os.environ, env), mock.patch.object(evals, "grade", side_effect=grab):
            runs, _ = self.run_eval()
        return runs, seen

    def test_post_error_is_a_failed_run_not_a_traceback(self) -> None:
        for error in (subprocess.TimeoutExpired("bash", 60), trigger_eval.TriggerEvalError("bad")):
            with mock.patch.object(trigger_eval, "post", side_effect=error):
                runs, _ = self.graded()
            with_run = next(r for r in runs if r.variant == "with")
            self.assertTrue(with_run.error.startswith("the post job failed"), with_run.error)

    def test_no_structured_output_posts_nothing(self) -> None:
        runs, seen = self.graded(FAKE_NO_STRUCT="1")
        self.assertEqual(seen[0], ("", ""))

    def test_scenario_number_reaches_gh(self) -> None:
        text = SCENARIOS.replace("    event: event.json\n    prompt: \"Read", "    event: event.json\n"
                                 "    number: 42\n    prompt: \"Read", 1)
        (self.root / "evals" / "trigger-label" / "scenarios.yaml").write_text(text, encoding="utf-8")
        _, seen = self.graded()
        self.assertTrue(seen[0][1].startswith("issue comment 42 "), seen[0])

    def test_missing_trigger_without_is_a_setup_failure(self) -> None:
        run = yaml.safe_load(self.run_yaml.read_text(encoding="utf-8"))
        del run["trigger"]["without"]
        self.run_yaml.write_text(yaml.safe_dump(run), encoding="utf-8")
        runs, _ = self.graded()
        without = next(r for r in runs if r.variant == "without")
        self.assertTrue(without.error.startswith("the setup failed:"), without.error)

    def test_profile_without_the_trigger_and_bare_id_stop_early(self) -> None:
        with self.assertRaises(evals.EvalError):
            self.run_eval("trigger.label.bug-triage")
        with self.assertRaises(evals.EvalError) as ctx:
            self.run_eval("trigger.label")
        self.assertIn("profile", str(ctx.exception))
        self.assertFalse(self.log.exists())

    def test_model_replaces_the_model_in_the_with_argv(self) -> None:
        self.graded()
        argv = json.loads(self.log.read_text().splitlines()[0])
        self.assertEqual(argv[argv.index("--model") + 1], "m1")


if __name__ == "__main__":
    unittest.main()
