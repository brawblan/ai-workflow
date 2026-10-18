"""Tests for K16: no merge to main from a spike branch (roadmap 6e, D30).

Each test renders into a temporary repo with the real framework in this repo. The behavior tests
take the `run:` script out of the rendered workflow and run it with bash, as the CI runner does.
This file is self-contained on purpose: sibling PRs add other render tests at the same time.
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
        self.assertEqual(entry["eval"], "evals/check-k16/")
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
               "MAIN_BRANCH": str(self.step["env"]["MAIN_BRANCH"])}
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
        for base in ("dev", "feature/x", "spike/other"):
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
            for base in (self.main_branch, "dev"):
                with self.subTest(head=head, base=base):
                    run = self.run_step(head, base)
                    self.assertFalse((self.work / "pwn").exists(), (head, base))
                    want_fail = head.startswith("spike/") and base == self.main_branch
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


if __name__ == "__main__":
    unittest.main()
