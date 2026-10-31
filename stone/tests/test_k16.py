"""Tests for K16: no merge to main from a spike branch (roadmap 6e, D30, D33).

Each test renders into a temporary repo with the real framework in this repo. The behavior tests
take the `run:` script out of the rendered workflow and run it with bash, as the CI runner does.
This file is self-contained on purpose: sibling PRs add other render tests at the same time.
The `test_d33_cN_` tests cover criterion N of the D33 ticket: K16 also blocks a spike PR into
branches.integration.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from stone import cli, render

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
TODAY = dt.date(2026, 10, 18)
REVIEW_BY = "2027-04-18"  # 6 months after TODAY
CONFIG = """framework_version: 0.8.0
harness: claude-code
model_profile: claude-5
profiles: [PROFILES]
BRANCHES
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
MAIN_AND_DEV = "branches: {integration: dev, main: main}"
K16 = ".github/workflows/cornerstone-k16.yml"
G3 = ".github/workflows/cornerstone-checks.yml"
MANIFEST = ".cornerstone/manifest.yaml"
NO_K16_PROFILES = ["single-ticket", "bug-triage", "code-audit"]
BASH = shutil.which("bash")
SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


class K16Base(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name) / "repo"
        (self.root / ".cornerstone").mkdir(parents=True)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def configure(self, profiles: list[str], branches: str = MAIN_AND_DEV) -> None:
        text = CONFIG.replace("PROFILES", ", ".join(profiles))
        text = text.replace("BRANCHES\n", branches + "\n" if branches else "")
        (self.root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")

    def render(self, today: dt.date = TODAY) -> tuple[render.Result, str]:
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            result = render.render(self.root, FRAMEWORK, today=today)
        return result, log.getvalue()

    def cli_render(self) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["render", "--root", str(self.root), "--framework", str(FRAMEWORK)])
        return code, out.getvalue()

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def written_files(self) -> list[str]:
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")
                      if p.is_file()
                      and p.relative_to(self.root).as_posix() != ".cornerstone/config.yaml")

    def manifest_entries(self) -> dict[str, dict[str, Any]]:
        data = yaml.safe_load(self.read(MANIFEST))
        return {entry["id"]: entry for entry in data["components"]}

    def workflow(self) -> dict[str, Any]:
        return yaml.safe_load(self.read(K16))

    def steps(self) -> list[dict[str, Any]]:
        return [step for job in self.workflow()["jobs"].values() for step in job["steps"]]

    def k16_step(self) -> dict[str, Any]:
        runs = [step for step in self.steps() if "run" in step]
        self.assertEqual(len(runs), 1, "the K16 workflow must have one run step")
        return runs[0]


def triggers(workflow: dict[str, Any]) -> Any:
    # YAML 1.1 reads the bare key `on` as True.
    return workflow.get("on", workflow.get(True))


# AC1: render writes K16 only when a selected profile lists K16.

class K16WhenTest(K16Base):
    def test_ac1_spike_writes_the_k16_workflow(self) -> None:
        self.configure(["spike"])
        result, _ = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertIn(K16, result.wrote)
        self.assertTrue((self.root / K16).is_file())

    def test_ac1_spike_writes_the_manifest_entry(self) -> None:
        self.configure(["spike"])
        self.render()
        entries = self.manifest_entries()
        self.assertIn("check.k16", entries)
        entry = entries["check.k16"]
        self.assertEqual(entry["kind"], "ci-job")
        self.assertEqual(entry["eval"], "")  # D99: the unit tests are the eval
        self.assertEqual(str(entry["review_by"]), REVIEW_BY)
        self.assertEqual(str(entry["added"]), TODAY.isoformat())
        self.assertEqual(entry["files"], [K16])
        self.assertEqual(entry["owner"], "octocat")

    def test_ac1_review_by_is_6_months_after_the_render_date(self) -> None:
        self.configure(["spike"])
        self.render(today=dt.date(2026, 8, 31))
        self.assertEqual(str(self.manifest_entries()["check.k16"]["review_by"]), "2027-02-28")

    def test_ac1_spike_from_the_cli_exits_0(self) -> None:
        self.configure(["spike"])
        code, out = self.cli_render()
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / K16).is_file())

    def test_ac1_spike_alone_writes_no_g3_workflow(self) -> None:
        self.configure(["spike"])
        self.render()
        self.assertFalse((self.root / G3).exists())
        self.assertNotIn("ci-job.checks", self.manifest_entries())

    def test_ac1_profile_without_k16_writes_no_k16(self) -> None:
        for name in NO_K16_PROFILES:
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.configure([name])
                result, _ = self.render()
                self.assertEqual(result.exit_code, 0)
                self.assertFalse((self.root / K16).exists())
                self.assertNotIn(K16, result.wrote)
                self.assertNotIn("check.k16", self.manifest_entries())

    def test_ac1_all_profiles_without_k16_together_write_no_k16(self) -> None:
        self.configure(NO_K16_PROFILES)
        self.render()
        self.assertFalse((self.root / K16).exists())
        self.assertNotIn("check.k16", self.manifest_entries())

    def test_ac1_spike_plus_single_ticket_writes_both_workflows(self) -> None:
        self.configure(["spike", "single-ticket"])
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("skipped profile", log)
        self.assertTrue((self.root / G3).is_file())
        self.assertTrue((self.root / K16).is_file())
        entries = self.manifest_entries()
        self.assertIn("ci-job.checks", entries)
        self.assertIn("check.k16", entries)

    def test_ac1_spike_plus_single_ticket_in_either_order_renders_the_same_k16(self) -> None:
        self.configure(["single-ticket", "spike"])
        self.render()
        first = self.read(K16)
        self.tearDown()
        self.setUp()
        self.configure(["spike", "single-ticket"])
        self.render()
        self.assertEqual(self.read(K16), first)

    def test_ac1_second_render_with_spike_writes_nothing(self) -> None:
        self.configure(["spike"])
        self.render()
        result, _ = self.render(today=TODAY + dt.timedelta(days=30))
        self.assertEqual(result.wrote, [])
        self.assertEqual(result.drift, [])
        self.assertEqual(str(self.manifest_entries()["check.k16"]["review_by"]), REVIEW_BY)

    def test_ac1_drop_spike_reports_k16_as_stale(self) -> None:
        self.configure(["spike", "single-ticket"])
        self.render()
        self.configure(["single-ticket"])
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertIn("stale check.k16", log)
        self.assertNotIn("check.k16", self.manifest_entries())


# AC2: the shape of the rendered workflow.

class K16WorkflowShapeTest(K16Base):
    def setUp(self) -> None:
        super().setUp()
        self.configure(["spike"])
        self.render()

    def test_ac2_workflow_is_valid_yaml(self) -> None:
        self.assertIsInstance(self.workflow(), dict)

    def test_ac2_trigger_is_pull_request_target_with_the_four_types(self) -> None:
        on = triggers(self.workflow())
        self.assertEqual(set(on), {"pull_request_target"})
        self.assertEqual(set(on["pull_request_target"]["types"]),
                         {"opened", "edited", "reopened", "synchronize"})

    def test_ac2_top_level_permissions_are_empty(self) -> None:
        workflow = self.workflow()
        self.assertIn("permissions", workflow)
        self.assertEqual(workflow["permissions"], {})

    def test_ac2_no_job_adds_permissions(self) -> None:
        for name, job in self.workflow()["jobs"].items():
            with self.subTest(job=name):
                self.assertIn(job.get("permissions", {}), ({}, None))

    def test_ac2_no_checkout_and_no_unpinned_uses(self) -> None:
        for step in self.steps():
            with self.subTest(step=step.get("name")):
                uses = step.get("uses")
                if uses is not None:
                    self.assertRegex(uses, SHA)
                    self.assertNotIn("checkout", uses)
                self.assertNotIn("checkout", step.get("run", ""))
                self.assertNotIn("git clone", step.get("run", ""))

    def test_ac2_no_uses_step_at_all(self) -> None:
        self.assertEqual([step for step in self.steps() if "uses" in step], [])

    def test_ac2_no_expression_inside_a_run_script(self) -> None:
        for step in self.steps():
            with self.subTest(step=step.get("name")):
                self.assertNotIn("${{", step.get("run", ""))

    def test_ac2_branch_names_come_only_through_env(self) -> None:
        env = self.k16_step()["env"]
        self.assertEqual(env["HEAD_REF"].replace(" ", ""), "${{github.head_ref}}")
        self.assertEqual(env["BASE_REF"].replace(" ", ""), "${{github.base_ref}}")
        self.assertEqual(env["MAIN_BRANCH"], "main")
        self.assertEqual(env["INTEGRATION_BRANCH"], "dev")

    def test_ac2_no_github_expression_outside_env(self) -> None:
        # The only expressions in the file are the two env values.
        self.assertEqual(len(re.findall(r"\$\{\{", self.read(K16))), 2)

    def test_ac2_no_template_placeholder_is_left(self) -> None:
        text = self.read(K16)
        self.assertNotIn("$$", text)
        # A `$` in the output must start `${{ ... }}` or a shell `${NAME}`.
        self.assertEqual(re.findall(r"\$(?!\{)\S*", text), [])
        self.assertNotIn("branch_main", text)


class K16MainBranchFromConfigTest(K16Base):
    def test_ac2_main_branch_value_comes_from_the_config(self) -> None:
        for value in ("trunk", "release/v1.0", "production"):
            with self.subTest(main=value):
                self.tearDown()
                self.setUp()
                self.configure(["spike"], f"branches: {{integration: dev, main: {value}}}")
                result, _ = self.render()
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(self.k16_step()["env"]["MAIN_BRANCH"], value)
                self.assertNotIn("$branch", self.read(K16))

    def test_ac2_new_main_branch_value_updates_the_workflow(self) -> None:
        self.configure(["spike"])
        self.render()
        self.configure(["spike"], "branches: {integration: dev, main: trunk}")
        result, _ = self.render()
        self.assertEqual(result.drift, [])
        self.assertIn(K16, result.wrote)
        self.assertEqual(self.k16_step()["env"]["MAIN_BRANCH"], "trunk")


# AC3: the behavior of the rendered step.

@unittest.skipIf(BASH is None, "bash is not installed")
class K16BehaviorTest(K16Base):
    main_branch = "trunk"

    def setUp(self) -> None:
        super().setUp()
        self.configure(["spike"], f"branches: {{integration: dev, main: {self.main_branch}}}")
        self.render()
        self.step = self.k16_step()
        self.work = Path(self.folder.name) / "work"
        self.work.mkdir()

    def run_step(self, head: str, base: str) -> subprocess.CompletedProcess:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "HEAD_REF": head, "BASE_REF": base,
               "MAIN_BRANCH": str(self.step["env"]["MAIN_BRANCH"]),
               "INTEGRATION_BRANCH": str(self.step["env"]["INTEGRATION_BRANCH"])}
        return subprocess.run([BASH, "-e", "-c", self.step["run"]], cwd=self.work, env=env,
                              capture_output=True, text=True)

    def error_lines(self, run: subprocess.CompletedProcess) -> list[str]:
        return [line for line in (run.stdout + run.stderr).splitlines()
                if line.startswith("::error")]

    def test_ac3_spike_into_main_fails(self) -> None:
        run = self.run_step("spike/can-x-do-y", self.main_branch)
        self.assertNotEqual(run.returncode, 0, run.stdout)

    def test_ac3_spike_into_main_prints_an_error_with_the_fix(self) -> None:
        run = self.run_step("spike/can-x-do-y", self.main_branch)
        lines = self.error_lines(run)
        self.assertEqual(len(lines), 1, run.stdout + run.stderr)
        line = lines[0]
        self.assertIn("spike/can-x-do-y", line)
        self.assertIn(self.main_branch, line)
        # The line tells the person what to do, not only what is wrong.
        self.assertTrue(any(word in line for word in ("Close", "close", "Rebuild", "rebuild",
                                                      "new branch")), line)

    def test_ac3_spike_into_another_base_passes(self) -> None:
        # `dev` is the integration branch here, so a spike PR into it fails (D33).
        for base in ("feature/x", "spike/other", "develop"):
            with self.subTest(base=base):
                run = self.run_step("spike/can-x-do-y", base)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertEqual(self.error_lines(run), [])

    def test_ac3_non_spike_branch_into_main_passes(self) -> None:
        for head in ("feature/x", "fix/y", "chore/z", "dev"):
            with self.subTest(head=head):
                run = self.run_step(head, self.main_branch)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertEqual(self.error_lines(run), [])

    def test_ac3_head_named_spike_without_slash_passes(self) -> None:
        run = self.run_step("spike", self.main_branch)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_ac3_head_with_spike_in_the_middle_passes(self) -> None:
        for head in ("my-spike/x", "feature/spike/x", "spikes/x", "spike-x", "xspike/y"):
            with self.subTest(head=head):
                run = self.run_step(head, self.main_branch)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_ac3_literal_main_is_not_the_main_branch_when_the_config_says_trunk(self) -> None:
        run = self.run_step("spike/can-x-do-y", "main")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_ac3_deep_spike_branch_into_main_fails(self) -> None:
        run = self.run_step("spike/a/b/c", self.main_branch)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(len(self.error_lines(run)), 1)

    def test_ac3_shell_text_in_a_branch_name_does_not_run(self) -> None:
        names = ["spike/$(touch pwn)", "spike/`touch pwn`", 'spike/";touch pwn;"',
                 "spike/${IFS}x$(touch${IFS}pwn)", "feature/$(touch pwn)"]
        for head in names:
            for base in (self.main_branch, "dev", "feature/y"):
                with self.subTest(head=head, base=base):
                    run = self.run_step(head, base)
                    self.assertFalse((self.work / "pwn").exists(), (head, base))
                    # `dev` is the integration branch, so a spike PR into it fails too (D33).
                    want_fail = head.startswith("spike/") and base in (self.main_branch, "dev")
                    self.assertEqual(run.returncode != 0, want_fail, run.stdout + run.stderr)

    def test_ac3_shell_text_in_the_base_name_does_not_run(self) -> None:
        run = self.run_step("spike/x", "$(touch pwn)")
        self.assertFalse((self.work / "pwn").exists())
        self.assertEqual(run.returncode, 0)


class K16BehaviorDefaultMainTest(K16BehaviorTest):
    """The same cases with the main branch named `main`."""
    main_branch = "main"

    def test_ac3_literal_main_is_not_the_main_branch_when_the_config_says_trunk(self) -> None:
        run = self.run_step("spike/can-x-do-y", "trunk")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


# AC4: K16 blocks from the start.

class K16BlocksTest(K16Base):
    def setUp(self) -> None:
        super().setUp()
        self.configure(["spike"])
        self.render()

    def test_ac4_no_continue_on_error(self) -> None:
        self.assertNotIn("continue-on-error", self.read(K16))
        for name, job in self.workflow()["jobs"].items():
            with self.subTest(job=name):
                self.assertNotIn("continue-on-error", job)
                for step in job["steps"]:
                    self.assertNotIn("continue-on-error", step)

    def test_ac4_no_warn_mode(self) -> None:
        text = self.read(K16)
        self.assertNotIn("--mode warn", text)
        self.assertNotIn("--mode", text)

    def test_ac4_job_and_step_have_no_condition_that_skips_them(self) -> None:
        for name, job in self.workflow()["jobs"].items():
            with self.subTest(job=name):
                self.assertNotIn("if", job)
                for step in job["steps"]:
                    self.assertNotIn("if", step)


# AC5: a K16 profile needs branches.main.

class K16NeedsMainBranchTest(K16Base):
    CASES = {
        "no branches section": "",
        "branches without main": "branches: {integration: dev}",
        "branches.main is a TODO value": "branches: {integration: dev, main: TODO(owner)}",
    }

    def test_ac5_render_raises_and_names_branches_main(self) -> None:
        for label, branches in self.CASES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure(["spike"], branches)
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(render.RenderError) as caught:
                        render.render(self.root, FRAMEWORK, today=TODAY)
                self.assertIn("branches.main", str(caught.exception))
                self.assertEqual(self.written_files(), [])

    def test_ac5_cli_exits_1_and_names_branches_main(self) -> None:
        for label, branches in self.CASES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure(["spike"], branches)
                code, out = self.cli_render()
                self.assertEqual(code, 1, out)
                self.assertIn("branches.main", out)
                self.assertEqual(self.written_files(), [])

    def test_ac5_spike_with_single_ticket_also_writes_nothing(self) -> None:
        self.configure(["single-ticket", "spike"], "branches: {integration: dev}")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(render.RenderError) as caught:
                render.render(self.root, FRAMEWORK, today=TODAY)
        self.assertIn("branches.main", str(caught.exception))
        self.assertEqual(self.written_files(), [])

    def test_ac5_missing_main_does_not_change_existing_files(self) -> None:
        self.configure(["spike"])
        self.render()
        before = {path: self.read(path) for path in self.written_files()}
        self.configure(["spike"], "branches: {integration: dev}")
        code, out = self.cli_render()
        self.assertEqual(code, 1, out)
        self.assertEqual({path: self.read(path) for path in self.written_files()}, before)

    def test_ac5_profile_without_k16_does_not_need_branches_main(self) -> None:
        for name in ("bug-triage", "code-audit"):
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.configure([name], "branches: {integration: dev}")
                result, _ = self.render()
                self.assertEqual(result.exit_code, 0)
                self.assertFalse((self.root / K16).exists())

    # AC8: an empty, null, or blank branches.main is the same as no branches.main.

    BLANK_CASES = {
        "branches.main is an empty string": 'branches: {integration: dev, main: ""}',
        "branches.main is an empty single-quoted string": "branches: {integration: dev, main: ''}",
        "branches.main is null": "branches: {integration: dev, main: null}",
        "branches.main is ~": "branches: {integration: dev, main: ~}",
        "branches.main has no value": "branches:\n  integration: dev\n  main:",
        "branches.main is only spaces": 'branches: {integration: dev, main: "   "}',
        "branches.main is one space": 'branches: {integration: dev, main: " "}',
        "branches.main is spaces and a tab": 'branches: {integration: dev, main: "  \\t "}',
    }

    def test_ac8_blank_main_render_raises_and_names_branches_main(self) -> None:
        for label, branches in self.BLANK_CASES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure(["spike"], branches)
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(render.RenderError) as caught:
                        render.render(self.root, FRAMEWORK, today=TODAY)
                self.assertIn("branches.main", str(caught.exception))
                self.assertEqual(self.written_files(), [])

    def test_ac8_blank_main_cli_exits_1_and_names_branches_main(self) -> None:
        for label, branches in self.BLANK_CASES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure(["spike"], branches)
                code, out = self.cli_render()
                self.assertEqual(code, 1, out)
                self.assertIn("branches.main", out)
                self.assertEqual(self.written_files(), [])
                self.assertFalse((self.root / K16).exists())

    def test_ac8_blank_main_with_single_ticket_also_writes_nothing(self) -> None:
        for label, branches in self.BLANK_CASES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure(["single-ticket", "spike"], branches)
                code, out = self.cli_render()
                self.assertEqual(code, 1, out)
                self.assertIn("branches.main", out)
                self.assertEqual(self.written_files(), [])

    def test_ac8_blank_main_does_not_change_existing_files(self) -> None:
        for label, branches in self.BLANK_CASES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure(["spike"])
                self.render()
                before = {path: self.read(path) for path in self.written_files()}
                self.configure(["spike"], branches)
                code, out = self.cli_render()
                self.assertEqual(code, 1, out)
                self.assertEqual({path: self.read(path) for path in self.written_files()},
                                 before)
                self.assertEqual(self.k16_step()["env"]["MAIN_BRANCH"], "main")


# AC9: a main branch name with YAML or shell text renders a valid workflow with the exact name.

QUOTED_MAIN_NAMES = {
    # label: (the name, the YAML text for the config value)
    "double quote": ('rel"x', "'rel\"x'"),
    "space and hash": ("rel #x", '"rel #x"'),
    "double quote and hash": ('rel"x #y', "'rel\"x #y'"),
    "single quote": ("rel'x", '"rel\'x"'),
    "backslash": ("rel\\x", "'rel\\x'"),
    "colon and space": ("rel: x", '"rel: x"'),
    "dollar text": ("rel$(x)", "'rel$(x)'"),
}


class K16QuotedMainBranchTest(K16Base):
    def configure_main(self, config_value: str) -> None:
        self.configure(["spike"], f"branches: {{integration: dev, main: {config_value}}}")

    def test_ac9_config_fixture_holds_the_exact_name(self) -> None:
        # Guard the test data: the config YAML must hold the name that the test expects.
        for label, (name, config_value) in QUOTED_MAIN_NAMES.items():
            with self.subTest(case=label):
                parsed = yaml.safe_load(f"main: {config_value}")
                self.assertEqual(parsed["main"], name)

    def test_ac9_render_writes_valid_yaml_with_the_exact_main_branch(self) -> None:
        for label, (name, config_value) in QUOTED_MAIN_NAMES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure_main(config_value)
                result, _ = self.render()
                self.assertEqual(result.exit_code, 0)
                workflow = self.workflow()
                self.assertIsInstance(workflow, dict)
                self.assertEqual(set(triggers(workflow)), {"pull_request_target"})
                self.assertEqual(workflow["permissions"], {})
                env = self.k16_step()["env"]
                self.assertIsInstance(env["MAIN_BRANCH"], str)
                self.assertEqual(env["MAIN_BRANCH"], name)
                self.assertEqual(env["HEAD_REF"].replace(" ", ""), "${{github.head_ref}}")
                self.assertEqual(env["BASE_REF"].replace(" ", ""), "${{github.base_ref}}")

    def test_ac9_cli_render_exits_0(self) -> None:
        for label, (_, config_value) in QUOTED_MAIN_NAMES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure_main(config_value)
                code, out = self.cli_render()
                self.assertEqual(code, 0, out)
                self.assertTrue((self.root / K16).is_file())

    def test_ac9_second_render_writes_nothing(self) -> None:
        for label, (_, config_value) in QUOTED_MAIN_NAMES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure_main(config_value)
                self.render()
                result, _ = self.render()
                self.assertEqual(result.wrote, [])
                self.assertEqual(result.drift, [])

    def test_ac9_plain_name_is_unchanged(self) -> None:
        self.configure(["spike"])
        self.render()
        self.assertEqual(self.k16_step()["env"]["MAIN_BRANCH"], "main")

    @unittest.skipIf(BASH is None, "bash is not installed")
    def test_ac9_spike_into_the_quoted_main_fails(self) -> None:
        for label, (name, config_value) in QUOTED_MAIN_NAMES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure_main(config_value)
                self.render()
                run = self.run_step("spike/can-x-do-y", name)
                self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
                errors = [line for line in (run.stdout + run.stderr).splitlines()
                          if line.startswith("::error")]
                self.assertEqual(len(errors), 1, run.stdout + run.stderr)
                self.assertIn(name, errors[0])
                self.assertFalse((self.work / "x").exists())

    @unittest.skipIf(BASH is None, "bash is not installed")
    def test_ac9_other_heads_and_bases_pass_with_the_quoted_main(self) -> None:
        for label, (name, config_value) in QUOTED_MAIN_NAMES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure_main(config_value)
                self.render()
                # Near names: the name without its special text, and the YAML-quoted text.
                # `dev` is the integration branch, so the other base is feature/y (D33).
                for head, base in (("feature/x", name), ("spike/x", "feature/y"),
                                   ("spike/x", "rel"), ("spike/x", config_value),
                                   ("spike/x", name + " ")):
                    run = self.run_step(head, base)
                    self.assertEqual(run.returncode, 0, (head, base, run.stdout + run.stderr))

    def run_step(self, head: str, base: str) -> subprocess.CompletedProcess:
        step = self.k16_step()
        self.work = Path(self.folder.name) / "work"
        self.work.mkdir(exist_ok=True)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "HEAD_REF": head, "BASE_REF": base, "MAIN_BRANCH": step["env"]["MAIN_BRANCH"],
               "INTEGRATION_BRANCH": step["env"]["INTEGRATION_BRANCH"]}
        return subprocess.run([BASH, "-e", "-c", step["run"]], cwd=self.work, env=env,
                              capture_output=True, text=True)


# D33: K16 also blocks a spike PR into branches.integration.

SPIKE_HEAD = "spike/can-x-do-y"


def run_k16(step: dict[str, Any], work: Path, head: str,
            base: str) -> subprocess.CompletedProcess:
    """Run the rendered step with bash. All four values come from the env, as on the runner."""
    work.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HEAD_REF": head, "BASE_REF": base,
           "MAIN_BRANCH": str(step["env"]["MAIN_BRANCH"]),
           "INTEGRATION_BRANCH": str(step["env"]["INTEGRATION_BRANCH"])}
    return subprocess.run([BASH, "-e", "-c", step["run"]], cwd=work, env=env,
                          capture_output=True, text=True)


def error_lines(run: subprocess.CompletedProcess) -> list[str]:
    return [line for line in (run.stdout + run.stderr).splitlines() if line.startswith("::error")]


class D33Base(K16Base):
    def render_branches(self, main: str, integration: str) -> None:
        self.configure(["spike"], f"branches: {{integration: {integration}, main: {main}}}")
        result, _ = self.render()
        self.assertEqual(result.exit_code, 0)

    def run_step(self, head: str, base: str) -> subprocess.CompletedProcess:
        return run_k16(self.k16_step(), Path(self.folder.name) / "work", head, base)

    def assert_fails_naming(self, head: str, base: str) -> None:
        run = self.run_step(head, base)
        output = run.stdout + run.stderr
        self.assertNotEqual(run.returncode, 0, (head, base, output))
        lines = error_lines(run)
        self.assertEqual(len(lines), 1, output)
        self.assertIn(head, lines[0])
        self.assertIn(base, lines[0])

    def assert_passes(self, head: str, base: str) -> None:
        run = self.run_step(head, base)
        output = run.stdout + run.stderr
        self.assertEqual(run.returncode, 0, (head, base, output))
        self.assertEqual(error_lines(run), [], (head, base, output))


@unittest.skipIf(BASH is None, "bash is not installed")
class D33DistinctBranchesTest(D33Base):
    """branches.main is `trunk` and branches.integration is `develop`: two different branches."""

    def setUp(self) -> None:
        super().setUp()
        self.render_branches("trunk", "develop")

    def test_d33_c1_spike_into_main_fails_with_one_error_naming_head_and_base(self) -> None:
        self.assert_fails_naming(SPIKE_HEAD, "trunk")

    def test_d33_c1_deep_spike_into_main_fails(self) -> None:
        self.assert_fails_naming("spike/a/b/c", "trunk")

    def test_d33_c2_spike_into_integration_fails_with_one_error_naming_head_and_base(self) -> None:
        self.assert_fails_naming(SPIKE_HEAD, "develop")

    def test_d33_c2_deep_spike_into_integration_fails(self) -> None:
        self.assert_fails_naming("spike/a/b/c", "develop")

    def test_d33_c2_error_tells_the_person_what_to_do(self) -> None:
        line = error_lines(self.run_step(SPIKE_HEAD, "develop"))[0]
        self.assertTrue(any(word in line for word in ("Close", "close", "Rebuild", "rebuild",
                                                      "new branch")), line)

    def test_d33_c4_spike_into_a_feature_or_spike_branch_passes(self) -> None:
        for base in ("feature/x", "spike/other", "fix/y"):
            with self.subTest(base=base):
                self.assert_passes(SPIKE_HEAD, base)

    def test_d33_c4_near_names_of_the_integration_branch_pass(self) -> None:
        for base in ("develop ", " develop", "Develop", "develop/x", "develop2", "dev",
                     "main", ""):
            with self.subTest(base=base):
                self.assert_passes(SPIKE_HEAD, base)

    def test_d33_c5_non_spike_head_into_main_or_integration_passes(self) -> None:
        for head in ("feature/x", "fix/y", "chore/z", "develop", "spike", "my-spike/x",
                     "spikes/x", "feature/spike/x"):
            for base in ("trunk", "develop"):
                with self.subTest(head=head, base=base):
                    self.assert_passes(head, base)

    def test_d33_c5_shell_text_in_the_names_does_not_run(self) -> None:
        heads = ["spike/$(touch pwn)", "spike/`touch pwn`", 'spike/";touch pwn;"',
                 "feature/$(touch pwn)"]
        work = Path(self.folder.name) / "work"
        for head in heads:
            for base in ("trunk", "develop", "feature/y", "$(touch pwn)"):
                with self.subTest(head=head, base=base):
                    run = self.run_step(head, base)
                    self.assertFalse((work / "pwn").exists(), (head, base))
                    want_fail = head.startswith("spike/") and base in ("trunk", "develop")
                    self.assertEqual(run.returncode != 0, want_fail, run.stdout + run.stderr)


@unittest.skipIf(BASH is None, "bash is not installed")
class D33SameBranchTest(D33Base):
    """branches.main and branches.integration name the same branch (D33 allows it)."""

    def test_d33_c3_spike_into_the_shared_branch_fails(self) -> None:
        for name in ("main", "trunk"):
            with self.subTest(branch=name):
                self.tearDown()
                self.setUp()
                self.render_branches(name, name)
                self.assertEqual(self.k16_step()["env"]["MAIN_BRANCH"], name)
                self.assertEqual(self.k16_step()["env"]["INTEGRATION_BRANCH"], name)
                self.assert_fails_naming(SPIKE_HEAD, name)

    def test_d33_c3_spike_into_a_different_branch_passes(self) -> None:
        for name in ("main", "trunk"):
            with self.subTest(branch=name):
                self.tearDown()
                self.setUp()
                self.render_branches(name, name)
                for base in ("dev", "develop", "feature/x", "spike/other", name + "/x"):
                    self.assert_passes(SPIKE_HEAD, base)

    def test_d33_c3_non_spike_into_the_shared_branch_passes(self) -> None:
        self.render_branches("main", "main")
        for head in ("feature/x", "fix/y", "dev"):
            with self.subTest(head=head):
                self.assert_passes(head, "main")


class D33IntegrationFromConfigTest(D33Base):
    def test_d33_c7_step_env_has_the_four_values(self) -> None:
        self.render_branches("trunk", "develop")
        env = self.k16_step()["env"]
        self.assertEqual(set(env), {"HEAD_REF", "BASE_REF", "MAIN_BRANCH", "INTEGRATION_BRANCH"})
        self.assertEqual(env["INTEGRATION_BRANCH"], "develop")
        self.assertEqual(env["MAIN_BRANCH"], "trunk")

    def test_d33_c7_integration_value_comes_from_the_config(self) -> None:
        for value in ("staging", "release/v1.0", "integration-k16-unique"):
            with self.subTest(integration=value):
                self.tearDown()
                self.setUp()
                self.render_branches("main", value)
                self.assertEqual(self.k16_step()["env"]["INTEGRATION_BRANCH"], value)

    def test_d33_c7_names_are_not_inlined_into_the_run_script(self) -> None:
        self.render_branches("main-k16-unique", "integration-k16-unique")
        run = self.k16_step()["run"]
        self.assertNotIn("integration-k16-unique", run)
        self.assertNotIn("main-k16-unique", run)
        self.assertIn("INTEGRATION_BRANCH", run)

    def test_d33_c7_only_expressions_are_head_ref_and_base_ref(self) -> None:
        self.render_branches("trunk", "develop")
        text = self.read(K16)
        self.assertEqual(len(re.findall(r"\$\{\{", text)), 2)
        env = self.k16_step()["env"]
        self.assertEqual(env["HEAD_REF"].replace(" ", ""), "${{github.head_ref}}")
        self.assertEqual(env["BASE_REF"].replace(" ", ""), "${{github.base_ref}}")
        self.assertNotIn("${{", self.k16_step()["run"])

    def test_d33_c7_permissions_empty_and_no_uses_or_checkout(self) -> None:
        self.render_branches("trunk", "develop")
        workflow = self.workflow()
        self.assertEqual(workflow["permissions"], {})
        for name, job in workflow["jobs"].items():
            with self.subTest(job=name):
                self.assertIn(job.get("permissions", {}), ({}, None))
        self.assertEqual([step for step in self.steps() if "uses" in step], [])
        text = self.read(K16)
        self.assertNotIn("checkout", text.replace("checks out no code", ""))
        self.assertNotIn("git clone", text)

    def test_d33_c9_second_render_writes_nothing(self) -> None:
        self.render_branches("trunk", "develop")
        result, _ = self.render(today=TODAY + dt.timedelta(days=30))
        self.assertEqual(result.wrote, [])
        self.assertEqual(result.drift, [])

    def test_d33_c9_new_integration_value_updates_the_workflow(self) -> None:
        self.render_branches("main", "dev")
        self.render_branches("main", "staging")
        result, _ = self.render()
        self.assertEqual(result.wrote, [])
        self.configure(["spike"], "branches: {integration: release, main: main}")
        result, _ = self.render()
        self.assertEqual(result.drift, [])
        self.assertIn(K16, result.wrote)
        self.assertEqual(self.k16_step()["env"]["INTEGRATION_BRANCH"], "release")
        self.assertEqual(self.k16_step()["env"]["MAIN_BRANCH"], "main")

    @unittest.skipIf(BASH is None, "bash is not installed")
    def test_d33_c9_updated_workflow_blocks_the_new_integration_branch(self) -> None:
        self.render_branches("main", "dev")
        self.render_branches("main", "staging")
        self.assert_fails_naming(SPIKE_HEAD, "staging")
        self.assert_passes(SPIKE_HEAD, "dev")


QUOTED_INTEGRATION_NAMES = dict(QUOTED_MAIN_NAMES)
QUOTED_INTEGRATION_NAMES["shell command"] = ("int$(touch pwn)", "'int$(touch pwn)'")
QUOTED_INTEGRATION_NAMES["backticks"] = ("int`touch pwn`", "'int`touch pwn`'")


class D33QuotedIntegrationBranchTest(D33Base):
    def configure_integration(self, config_value: str) -> None:
        self.configure(["spike"], f"branches: {{integration: {config_value}, main: main}}")

    def test_d33_c6_config_fixture_holds_the_exact_name(self) -> None:
        # Guard the test data: the config YAML must hold the name that the test expects.
        for label, (name, config_value) in QUOTED_INTEGRATION_NAMES.items():
            with self.subTest(case=label):
                self.assertEqual(yaml.safe_load(f"integration: {config_value}")["integration"],
                                 name)

    def test_d33_c6_render_writes_valid_yaml_with_the_exact_integration_branch(self) -> None:
        for label, (name, config_value) in QUOTED_INTEGRATION_NAMES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure_integration(config_value)
                result, _ = self.render()
                self.assertEqual(result.exit_code, 0)
                workflow = self.workflow()
                self.assertIsInstance(workflow, dict)
                self.assertEqual(set(triggers(workflow)), {"pull_request_target"})
                self.assertEqual(workflow["permissions"], {})
                env = self.k16_step()["env"]
                self.assertIsInstance(env["INTEGRATION_BRANCH"], str)
                self.assertEqual(env["INTEGRATION_BRANCH"], name)
                self.assertEqual(env["MAIN_BRANCH"], "main")
                self.assertEqual(env["HEAD_REF"].replace(" ", ""), "${{github.head_ref}}")
                self.assertEqual(env["BASE_REF"].replace(" ", ""), "${{github.base_ref}}")
                self.assertEqual(len(re.findall(r"\$\{\{", self.read(K16))), 2)

    def test_d33_c6_cli_render_exits_0(self) -> None:
        for label, (_, config_value) in QUOTED_INTEGRATION_NAMES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure_integration(config_value)
                code, out = self.cli_render()
                self.assertEqual(code, 0, out)
                self.assertTrue((self.root / K16).is_file())

    def test_d33_c6_second_render_writes_nothing(self) -> None:
        for label, (_, config_value) in QUOTED_INTEGRATION_NAMES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure_integration(config_value)
                self.render()
                result, _ = self.render()
                self.assertEqual(result.wrote, [])
                self.assertEqual(result.drift, [])

    @unittest.skipIf(BASH is None, "bash is not installed")
    def test_d33_c6_spike_into_the_quoted_integration_fails(self) -> None:
        for label, (name, config_value) in QUOTED_INTEGRATION_NAMES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure_integration(config_value)
                self.render()
                self.assert_fails_naming(SPIKE_HEAD, name)
                work = Path(self.folder.name) / "work"
                self.assertFalse((work / "pwn").exists())
                self.assertFalse((work / "x").exists())

    @unittest.skipIf(BASH is None, "bash is not installed")
    def test_d33_c6_near_names_pass_with_the_quoted_integration(self) -> None:
        for label, (name, config_value) in QUOTED_INTEGRATION_NAMES.items():
            with self.subTest(case=label):
                self.tearDown()
                self.setUp()
                self.configure_integration(config_value)
                self.render()
                # Near names: a prefix of the name, the YAML-quoted text, and added spaces.
                for head, base in (("feature/x", name), ("spike/x", "feature/y"),
                                   ("spike/x", name[:3]), ("spike/x", config_value),
                                   ("spike/x", name + " "), ("spike/x", " " + name)):
                    self.assert_passes(head, base)
                self.assertFalse((Path(self.folder.name) / "work" / "pwn").exists())


class D33NeedsIntegrationBranchTest(K16Base):
    CASES = {
        "branches without integration": "branches: {main: main}",
        "integration is a TODO value": "branches: {integration: TODO(owner), main: main}",
        "integration is null": "branches: {integration: null, main: main}",
        "integration is ~": "branches: {integration: ~, main: main}",
        "integration has no value": "branches:\n  main: main\n  integration:",
        "integration is an empty string": 'branches: {integration: "", main: main}',
        "integration is an empty single-quoted string": "branches: {integration: '', main: main}",
        "integration is only spaces": 'branches: {integration: "   ", main: main}',
        "integration is spaces and a tab": 'branches: {integration: "  \\t ", main: main}',
    }
    BOTH_MISSING = {
        "no branches section": "",
        "both null": "branches: {integration: null, main: null}",
        "both empty": 'branches: {integration: "", main: ""}',
        "both TODO": "branches: {integration: TODO(owner), main: TODO(owner)}",
    }

    def reset(self, profiles: list[str], branches: str) -> None:
        self.tearDown()
        self.setUp()
        self.configure(profiles, branches)

    def test_d33_c8_render_raises_and_names_branches_integration(self) -> None:
        for label, branches in self.CASES.items():
            with self.subTest(case=label):
                self.reset(["spike"], branches)
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(render.RenderError) as caught:
                        render.render(self.root, FRAMEWORK, today=TODAY)
                self.assertIn("branches.integration", str(caught.exception))
                self.assertEqual(self.written_files(), [])

    def test_d33_c8_cli_exits_1_and_names_branches_integration(self) -> None:
        for label, branches in self.CASES.items():
            with self.subTest(case=label):
                self.reset(["spike"], branches)
                code, out = self.cli_render()
                self.assertEqual(code, 1, out)
                self.assertIn("branches.integration", out)
                self.assertEqual(self.written_files(), [])
                self.assertFalse((self.root / K16).exists())

    def test_d33_c8_with_single_ticket_also_writes_nothing(self) -> None:
        for label, branches in self.CASES.items():
            with self.subTest(case=label):
                self.reset(["single-ticket", "spike"], branches)
                code, out = self.cli_render()
                self.assertEqual(code, 1, out)
                self.assertIn("branches.integration", out)
                self.assertEqual(self.written_files(), [])

    def test_d33_c8_missing_integration_does_not_change_existing_files(self) -> None:
        for label, branches in self.CASES.items():
            with self.subTest(case=label):
                self.reset(["spike"], MAIN_AND_DEV)
                self.render()
                before = {path: self.read(path) for path in self.written_files()}
                self.configure(["spike"], branches)
                code, out = self.cli_render()
                self.assertEqual(code, 1, out)
                self.assertEqual({path: self.read(path) for path in self.written_files()},
                                 before)
                self.assertEqual(self.k16_step()["env"]["INTEGRATION_BRANCH"], "dev")

    def test_d33_c8_main_also_missing_names_branches_main(self) -> None:
        for label, branches in self.BOTH_MISSING.items():
            with self.subTest(case=label):
                self.reset(["spike"], branches)
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(render.RenderError) as caught:
                        render.render(self.root, FRAMEWORK, today=TODAY)
                self.assertIn("branches.main", str(caught.exception))
                self.assertEqual(self.written_files(), [])
                code, out = self.cli_render()
                self.assertEqual(code, 1, out)
                self.assertIn("branches.main", out)
                self.assertEqual(self.written_files(), [])

    def test_d33_c8_profile_without_k16_does_not_need_branches_integration(self) -> None:
        # code-audit is not here: its reviewer role needs branches.integration without K16.
        self.reset(["bug-triage"], "branches: {main: main}")
        result, _ = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertFalse((self.root / K16).exists())


if __name__ == "__main__":
    unittest.main()
