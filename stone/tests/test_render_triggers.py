"""Tests for the trigger workflows of `stone render` (roadmap 6g parts 1 and 2, D31)."""

from __future__ import annotations

import contextlib
import io
import json
import re
import shlex
import unittest

import yaml

from stone import cli
from test_render_profiles import (FRAMEWORK, MANIFEST, TODAY, FrameworkCopy, RenderBase,
                                  profile_data, profile_names, trigger_files)

TRIGGER = re.compile(
    r"^\.github/workflows/cornerstone-(.+)-(label|schedule|issue-opened|dependency-pr)\.yml$")
ISSUE_TOKENS = ({"contents": "read", "issues": "read"}, {"issues": "write"})
TOKENS = {"label": ISSUE_TOKENS, "schedule": ISSUE_TOKENS, "issue-opened": ISSUE_TOKENS,
          "dependency-pr": ({"contents": "read", "pull-requests": "read"},
                            {"pull-requests": "write"})}
BOTS = "dependabot[bot],renovate[bot]"
# (allowed_non_write_users, allowed_bots) of the run step, for each trigger type.
ALLOWED = {"label": ("", ""), "schedule": ("", ""), "issue-opened": ("*", ""),
           "dependency-pr": ("", BOTS)}


def on(data: dict) -> dict:
    return data.get("on", data.get(True))  # YAML 1.1 reads on as True


def run_step(data: dict) -> dict:
    return next(s for s in data["jobs"]["run"]["steps"] if s.get("id") == "run")


def parts(path: str) -> tuple[str, str]:
    """Return the profile and the trigger type of a trigger workflow path."""
    return TRIGGER.match(path).groups()


def flow(name: str) -> str:
    text = (FRAMEWORK / "profiles" / f"{name}.md").read_text(encoding="utf-8")
    return text.split("\n## Flow\n", 1)[1].split("\n## ", 1)[0].strip()


def strip_links(text: str) -> str:
    return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)


class TriggerBase(RenderBase):
    def workflows(self) -> dict[str, dict]:
        return {p: yaml.safe_load(self.read(p)) for p in self.written_files() if TRIGGER.match(p)}

    def run_if(self, name: str) -> str:
        return self.workflows()[f".github/workflows/cornerstone-{name}-label.yml"]["jobs"]["run"]["if"]

    def cli_render(self) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(["render", "--root", str(self.root), "--framework", str(self.framework)])


class TriggerFilesTest(TriggerBase):
    def test_ac1_each_profile_writes_one_workflow_for_each_label_and_schedule(self) -> None:
        for name in profile_names():
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name])
                result, log = self.render()
                self.assertEqual(result.exit_code, 0)
                self.assertNotIn("skipped trigger", log)
                self.assertEqual(sorted(self.workflows()), sorted(trigger_files([name])))

    def test_ac1_command_trigger_writes_no_workflow(self) -> None:
        self.select(["spike"])  # triggers: [command]
        self.render()
        self.assertEqual(self.workflows(), {})

    def test_p2_ac1_ci_trigger_writes_its_workflow(self) -> None:
        for name, event in (("bug-triage", "issue-opened"), ("dependency-upgrade", "dependency-pr")):
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name])
                _, log = self.render()
                self.assertNotIn("skipped trigger", log)
                self.assertEqual(sorted(self.workflows()),
                                 [f".github/workflows/cornerstone-{name}-{event}.yml",
                                  f".github/workflows/cornerstone-{name}-schedule.yml"])

    def test_p2_ac1_no_profile_logs_a_skipped_trigger(self) -> None:
        self.select(profile_names())
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("skipped trigger", log)


class TriggerContentTest(TriggerBase):
    def setUp(self) -> None:
        super().setUp()
        self.select(profile_names())
        self.result, _ = self.render()

    def test_ac2_p2_ac2_ac3_permissions_are_exact(self) -> None:
        self.assertEqual(len(self.workflows()), len(trigger_files(profile_names())))
        self.assertEqual({parts(p)[1] for p in self.workflows()}, set(TOKENS))
        for path, data in self.workflows().items():
            with self.subTest(path=path):
                self.assertEqual(data["permissions"], {})
                run, post = TOKENS[parts(path)[1]]
                self.assertEqual(data["jobs"]["run"]["permissions"], run)
                self.assertEqual(data["jobs"]["post"]["permissions"], post)

    def test_p2_ac5_only_the_post_job_has_a_write_permission(self) -> None:
        for path, data in self.workflows().items():
            for job_name, job in data["jobs"].items():
                with self.subTest(path=path, job=job_name):
                    writes = "write" in (job.get("permissions") or {}).values()
                    self.assertEqual(writes, job_name == "post")

    def test_p2_ac2_ac3_events(self) -> None:
        wf = self.workflows()
        issue = wf[".github/workflows/cornerstone-bug-triage-issue-opened.yml"]
        self.assertEqual(on(issue), {"issues": {"types": ["opened"]}})
        pr = wf[".github/workflows/cornerstone-dependency-upgrade-dependency-pr.yml"]
        self.assertEqual(on(pr), {"pull_request": {"types": ["opened", "reopened"]}})
        for bot in BOTS.split(","):
            self.assertIn(f'"{bot}"', pr["jobs"]["run"]["if"])
        self.assertIn("github.event.pull_request.user.login", pr["jobs"]["run"]["if"])

    def test_p2_ac2_ac3_ac4_run_step_allows_only_the_trigger_users(self) -> None:
        for path, data in self.workflows().items():
            with self.subTest(path=path):
                step = run_step(data)["with"]
                self.assertEqual((step["allowed_non_write_users"], step["allowed_bots"]),
                                 ALLOWED[parts(path)[1]])

    def test_ac3_no_run_script_has_an_expression_and_events_come_through_env(self) -> None:
        for path, data in self.workflows().items():
            for job in data["jobs"].values():
                for step in job["steps"]:
                    with self.subTest(path=path, step=step.get("name", step.get("uses"))):
                        self.assertNotIn("${{", step.get("run", ""))
                        outside_env = json.dumps({k: v for k, v in step.items() if k != "env"})
                        self.assertNotIn("github.event", outside_env)

    def test_ac4_run_step_is_pinned_and_has_the_first_role_and_the_flow(self) -> None:
        for path, data in self.workflows().items():
            name = parts(path)[0]
            role = profile_data(name)["roles"][0]
            with self.subTest(path=path):
                step = next(s for s in data["jobs"]["run"]["steps"] if s.get("id") == "run")
                self.assertRegex(step["uses"], r"^[^@\s]+@[0-9a-f]{40}$")
                self.assertIn(f"You are the {role}.", step["with"]["prompt"])
                if role != "shaper" or parts(path)[1] != "label":  # D41
                    self.assertIn(strip_links(flow(name)), step["with"]["prompt"])
                args = shlex.split(step["with"]["claude_args"])
                self.assertEqual(args[args.index("--agent") + 1], role)
                # D32: each allow rule has a path. A rule with no path allows reads anywhere.
                allowed = args[args.index("--allowedTools") + 1].split(",")
                self.assertEqual(allowed, ["Read(./**)", "Read(/${{ runner.temp }}/cornerstone/**)"])
                denied = args[args.index("--disallowedTools") + 1].split(",")
                self.assertLessEqual({"Bash", "Edit", "Write"}, set(denied))

    def test_d41_prompt_has_no_relative_link(self) -> None:
        for path, data in self.workflows().items():
            prompt = next(s for s in data["jobs"]["run"]["steps"]
                          if s.get("id") == "run")["with"]["prompt"]
            with self.subTest(path=path):
                self.assertNotRegex(prompt, r"\]\((?!https?:)[^)]*\)")
                self.assertNotIn("../", prompt)

    def test_d41_label_run_of_the_shaper_reports_and_does_not_interview(self) -> None:
        found = 0
        for path, data in self.workflows().items():
            name, kind = parts(path)
            if kind != "label" or profile_data(name)["roles"][0] != "shaper":
                continue
            found += 1
            prompt = next(s for s in data["jobs"]["run"]["steps"]
                          if s.get("id") == "run")["with"]["prompt"]
            with self.subTest(path=path):
                self.assertIn("readiness check", prompt)
                self.assertIn("In the `report`, list each missing field", prompt)
                self.assertIn("Do not interview anyone", prompt)
                self.assertNotIn("with the human", prompt)
                self.assertNotIn("with the ticket author", prompt)
                self.assertNotIn("Run the shaper", prompt)
        self.assertGreater(found, 0)

    def test_d41_flow_steps_rewrites_a_relative_link_to_text(self) -> None:
        from stone import triggers
        text = triggers.flow_steps(FRAMEWORK, "app-slice")
        self.assertNotIn("../workflow-model.md", text)
        self.assertIn("(see Specs)", text)

    def test_ac8_manifest_has_one_entry_for_each_workflow(self) -> None:
        entries = {c["id"]: c for c in yaml.safe_load(self.read(MANIFEST))["components"]}
        for path in self.workflows():
            name, kind = parts(path)
            with self.subTest(path=path):
                entry = entries[f"trigger.{kind}.{name}"]
                self.assertEqual((entry["kind"], entry["eval"], entry["files"]),
                                 ("ci-job", f"evals/trigger-{kind}/", [path]))
                self.assertEqual((str(entry["added"]), str(entry["review_by"])),
                                 (TODAY.isoformat(), "2027-04-18"))
        self.assertEqual(len([i for i in entries if i.startswith("trigger.")]),
                         len(self.workflows()))
        for entry_id, kind in (("trigger.issue-opened.bug-triage", "issue-opened"),
                               ("trigger.dependency-pr.dependency-upgrade", "dependency-pr")):
            with self.subTest(entry=entry_id):  # p2 AC6
                self.assertEqual((entries[entry_id]["kind"], entries[entry_id]["eval"]),
                                 ("ci-job", f"evals/trigger-{kind}/"))

    def test_ac9_second_render_writes_nothing(self) -> None:
        before = {path: self.read(path) for path in self.written_files()}
        result, _ = self.render()
        self.assertEqual((result.wrote, result.drift, result.exit_code), ([], [], 0))
        self.assertEqual({path: self.read(path) for path in self.written_files()}, before)


class SharedLabelTest(TriggerBase):
    def test_ac6_one_profile_with_the_label_needs_only_the_label(self) -> None:
        self.select(["single-ticket", "bug-triage"])
        self.render()
        condition = self.run_if("single-ticket")
        self.assertIn("github.event.label.name == 'agent-ready'", condition)
        self.assertIn("labels.*.name, 'agent-ready')", condition)
        self.assertNotIn("profile:", condition)

    def test_ac6_shared_label_also_needs_the_profile_label(self) -> None:
        for names in (["single-ticket", "debugging"], ["single-ticket", "debugging", "app-slice"]):
            with self.subTest(profiles=names):
                self.select(names)
                self.render()
                for name in names:
                    condition = self.run_if(name)
                    self.assertIn("github.event.label.name == 'agent-ready'", condition)
                    self.assertIn(f"labels.*.name, 'profile:{name}')", condition)


class EditedTriggerTest(FrameworkCopy, TriggerBase):
    def set_triggers(self, triggers: list[str]) -> None:
        path = self.framework / "profiles" / "code-audit.md"
        text = path.read_text(encoding="utf-8")
        path.write_text(re.sub(r"^triggers: .*$", "triggers: " + json.dumps(triggers), text,
                               count=1, flags=re.M), encoding="utf-8")
        self.select(["code-audit"])

    def cron(self) -> str:
        data = yaml.safe_load(self.read(".github/workflows/cornerstone-code-audit-schedule.yml"))
        return data.get("on", data.get(True))["schedule"][0]["cron"]  # YAML 1.1 reads on as True

    def test_ac5_schedule_words_and_cron_lines(self) -> None:
        for value, want in (("daily", "0 6 * * *"), ("weekly", "0 6 * * 1"),
                            ("monthly", "0 6 1 * *"), ("15 3 * * 2", "15 3 * * 2"),
                            ("*/30 1-5 1,15 * MON", "*/30 1-5 1,15 * MON")):
            with self.subTest(schedule=value):
                self.set_triggers(["command", f"schedule:{value}"])
                self.assertEqual(self.cli_render(), 0)
                self.assertEqual(self.cron(), want)

    def test_ac5_invalid_schedule_fails_and_writes_no_file(self) -> None:
        for value in ("hourly", "0 6 * *", "0 6 * * * *", ""):
            with self.subTest(schedule=value):
                self.set_triggers(["command", f"schedule:{value}"])
                self.assertEqual(self.cli_render(), 1)
                self.assertEqual(self.written_files(), [])

    def test_p2_ci_trigger_in_another_profile_gets_its_own_workflow(self) -> None:
        self.set_triggers(["command", "ci:dependency-pr"])
        self.assertEqual(self.cli_render(), 0)
        data = yaml.safe_load(self.read(
            ".github/workflows/cornerstone-code-audit-dependency-pr.yml"))
        self.assertEqual(run_step(data)["with"]["allowed_bots"], BOTS)
        self.assertEqual(data["jobs"]["post"]["permissions"], {"pull-requests": "write"})

    def test_p2_unknown_ci_event_is_still_skipped_with_a_log_line(self) -> None:
        self.set_triggers(["command", "ci:push"])
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertIn("skipped trigger ci:push of profile code-audit", log)
        self.assertEqual(self.workflows(), {})

    def test_ac7_two_label_triggers_fail_and_write_no_file(self) -> None:
        # Finding (2026-10-18): render exits 0. Both labels get the id trigger.label.code-audit,
        # so check_targets in triggers.py sees one target and does not fail.
        self.set_triggers(["command", "label:agent-ready", "label:audit-now"])
        self.assertEqual(self.cli_render(), 1)
        self.assertEqual(self.written_files(), [])


if __name__ == "__main__":
    unittest.main()
