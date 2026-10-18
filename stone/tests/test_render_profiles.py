"""Tests for `stone render` with all 10 profiles and the investigator role (D24, D25).

Each test class renders into a temporary repo with the real framework in this repo, or with a
copy of it when a test must change the adapter or the model profile.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import cli, render
from stone.markdown import split_frontmatter

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
TODAY = dt.date(2026, 10, 18)
CONFIG = """framework_version: 0.8.0
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
ALL_ROLES = ["implementer", "investigator", "planner", "reviewer", "shaper", "tester"]
INVESTIGATOR = ".claude/agents/investigator.md"
HOOK = ".cornerstone/hooks/protect-paths.py"
SETTINGS = ".claude/settings.json"
K6 = ".cornerstone/checks/protected_paths.py"
K7 = ".cornerstone/checks/change_size.py"
K15 = ".cornerstone/checks/instruction_size.py"
WORKFLOW = ".github/workflows/cornerstone-checks.yml"
K16_WORKFLOW = ".github/workflows/cornerstone-k16.yml"
MANIFEST = ".cornerstone/manifest.yaml"
ALWAYS = [HOOK, SETTINGS, MANIFEST]
REPORT_PROFILES = ["bug-triage", "code-audit", "spike"]


def profile_names() -> list[str]:
    return sorted(p.stem for p in (FRAMEWORK / "profiles").glob("*.md")
                  if p.stem not in {"README", "_template"})


def profile_data(name: str, framework: Path = FRAMEWORK) -> dict:
    text = (framework / "profiles" / f"{name}.md").read_text(encoding="utf-8")
    return split_frontmatter(text)[0]


def role_file(role: str) -> str:
    return f".claude/agents/{role}.md"


def trigger_files(names: list[str]) -> list[str]:
    """Return the trigger workflows for the profiles: one for each trigger but command (D31)."""
    files = []
    for name in names:
        for trigger in profile_data(name).get("triggers", []):
            kind, _, event = str(trigger).partition(":")
            kind = event if kind == "ci" else kind  # ci:issue-opened -> issue-opened
            if kind != "command":
                files.append(f".github/workflows/cornerstone-{name}-{kind}.yml")
    return files


def expected_files(names: list[str]) -> list[str]:
    """Return the files that render must write for the profiles, from the ticket rules."""
    profiles = [profile_data(name) for name in names]
    roles = {role for profile in profiles for role in profile["roles"]}
    files = [role_file(role) for role in roles] + ALWAYS + trigger_files(names)
    if any(profile["gates"].get("G3", "skip") != "skip" for profile in profiles):
        files.append(WORKFLOW)
    if any("K6" in profile["checks"] for profile in profiles):
        files.append(K6)
    if any("K7" in profile["checks"] for profile in profiles):
        files.append(K7)
    if any("K15" in profile["checks"] for profile in profiles):
        files.append(K15)
    if any("K16" in profile["checks"] for profile in profiles):
        files.append(K16_WORKFLOW)
    return sorted(files)


class RenderBase(unittest.TestCase):
    framework = FRAMEWORK

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name) / "repo"
        (self.root / ".cornerstone").mkdir(parents=True)
        self.write_config(CONFIG)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def write_config(self, text: str) -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")

    def select(self, names: list[str], extra_paths: str = "") -> None:
        text = CONFIG.replace("[single-ticket]", "[" + ", ".join(names) + "]")
        self.write_config(text.replace("  plans: docs/plans/\n",
                                       "  plans: docs/plans/\n" + extra_paths))

    def render(self, today: dt.date = TODAY) -> tuple[render.Result, str]:
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            result = render.render(self.root, self.framework, today=today)
        return result, log.getvalue()

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def written_files(self) -> list[str]:
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")
                      if p.is_file() and ".git" not in p.relative_to(self.root).parts
                      and p.relative_to(self.root).as_posix() != ".cornerstone/config.yaml")

    def manifest_ids(self) -> list[str]:
        return [c["id"] for c in yaml.safe_load(self.read(MANIFEST))["components"]]

    def run_hook(self, path: str, role: str) -> subprocess.CompletedProcess:
        event = json.dumps({"tool_input": {"file_path": str(self.root / path)}})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root), "STONE_ROLE": role}
        return subprocess.run([sys.executable, HOOK], cwd=self.root, input=event, env=env,
                              capture_output=True, text=True)

    def hook(self, path: str, role: str) -> int:
        return self.run_hook(path, role).returncode

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                        "-c", "init.defaultBranch=main", *args],
                       cwd=self.root, check=True, capture_output=True)

    def git_repo_on(self, branch: str) -> None:
        self.git("init", "-q")
        (self.root / "README.md").write_text("base\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "base")
        if branch != "main":
            self.git("checkout", "-q", "-b", branch)


class FrameworkCopy(RenderBase):
    """Render with a copy of the framework that a test can change."""

    def setUp(self) -> None:
        super().setUp()
        self.framework = Path(self.folder.name) / "framework"
        shutil.copytree(FRAMEWORK, self.framework)

    def registry_path(self) -> Path:
        return self.framework / "adapters" / "claude-code" / "components.yaml"

    def remove_roles(self, *roles: str) -> None:
        data = yaml.safe_load(self.registry_path().read_text(encoding="utf-8"))
        data["components"] = [c for c in data["components"] if c.get("role") not in roles]
        self.registry_path().write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def set_role_model(self, role: str, model: str) -> None:
        path = self.framework / "adapters" / "claude-code" / "models" / "claude-5.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["defaults"]["role_models"][role] = model
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def add_profile(self, name: str, g3: str, checks: list[str]) -> None:
        text = (self.framework / "profiles" / "single-ticket.md").read_text(encoding="utf-8")
        text = re.sub(r"^id: .*$", f"id: {name}", text, count=1, flags=re.M)
        text = re.sub(r"^  G3: .*$", f"  G3: {g3}", text, count=1, flags=re.M)
        text = re.sub(r"^checks: .*$", f"checks: [{', '.join(checks)}]", text, count=1,
                      flags=re.M)
        (self.framework / "profiles" / f"{name}.md").write_text(text, encoding="utf-8")


# AC1: each profile renders alone.

class EachProfileAloneTest(RenderBase):
    def test_ac1_there_are_ten_profiles(self) -> None:
        self.assertEqual(len(profile_names()), 10, profile_names())

    def test_ac1_each_profile_alone_exits_0_from_the_cli(self) -> None:
        for name in profile_names():
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name])
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    code = cli.main(["render", "--root", str(self.root),
                                     "--framework", str(FRAMEWORK)])
                self.assertEqual(code, 0, out.getvalue())

    def test_ac1_each_profile_alone_writes_exactly_its_role_files(self) -> None:
        for name in profile_names():
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name])
                result, log = self.render()
                self.assertEqual(result.exit_code, 0)
                self.assertNotIn("skipped profile", log)
                roles = sorted(profile_data(name)["roles"])
                agents = sorted(p for p in self.written_files() if p.startswith(".claude/agents/"))
                self.assertEqual(agents, sorted(role_file(role) for role in roles))
                ids = [i for i in self.manifest_ids() if i.startswith("role.")]
                self.assertEqual(sorted(ids), sorted(f"role.{role}" for role in roles))

    def test_ac1_each_profile_alone_writes_the_expected_file_set(self) -> None:
        for name in profile_names():
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name])
                result, _ = self.render()
                self.assertEqual(sorted(result.wrote), expected_files([name]))
                self.assertEqual(self.written_files(), expected_files([name]))

    def test_ac1_no_role_file_has_a_placeholder_left(self) -> None:
        for name in profile_names():
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name])
                self.render()
                for role in profile_data(name)["roles"]:
                    self.assertNotIn("$", self.read(role_file(role)), role)

    def test_ac1_bug_triage_writes_only_the_investigator_role(self) -> None:
        self.select(["bug-triage"])
        self.render()
        agents = [p for p in self.written_files() if p.startswith(".claude/agents/")]
        self.assertEqual(agents, [INVESTIGATOR])


# AC2: the G3 workflow and the K6 check render only when a profile needs them.

class WhenComponentsTest(RenderBase):
    def test_ac2_report_profile_alone_has_no_g3_workflow_and_no_k6(self) -> None:
        for name in REPORT_PROFILES:
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name])
                result, _ = self.render()
                self.assertEqual(result.exit_code, 0)
                self.assertFalse((self.root / WORKFLOW).exists())
                self.assertFalse((self.root / K6).exists())
                self.assertNotIn("ci-job.checks", self.manifest_ids())
                self.assertNotIn("check.k6", self.manifest_ids())

    def test_ac2_profile_with_g3_writes_the_workflow(self) -> None:
        for name in profile_names():
            if profile_data(name)["gates"].get("G3", "skip") == "skip":
                continue
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name])
                self.render()
                self.assertTrue((self.root / WORKFLOW).exists())
                self.assertIn("ci-job.checks", self.manifest_ids())

    def test_ac2_profile_with_k6_writes_the_k6_check(self) -> None:
        for name in profile_names():
            if "K6" not in profile_data(name)["checks"]:
                continue
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name])
                self.render()
                self.assertTrue((self.root / K6).exists())
                self.assertIn("check.k6", self.manifest_ids())

    def test_ac2_report_profile_with_single_ticket_gets_both(self) -> None:
        for name in REPORT_PROFILES:
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name, "single-ticket"])
                result, log = self.render()
                self.assertEqual(result.exit_code, 0)
                self.assertNotIn("skipped profile", log)
                self.assertTrue((self.root / WORKFLOW).exists())
                self.assertTrue((self.root / K6).exists())
                self.assertEqual(sorted(result.wrote), expected_files([name, "single-ticket"]))

    def test_ac2_order_of_the_profiles_does_not_change_the_files(self) -> None:
        self.select(["single-ticket", "bug-triage"])
        self.render()
        first = {path: self.read(path) for path in self.written_files() if path != MANIFEST}
        self.tearDown()
        self.setUp()
        self.select(["bug-triage", "single-ticket"])
        self.render()
        self.assertEqual({path: self.read(path) for path in self.written_files()
                          if path != MANIFEST}, first)

    def test_ac2_change_to_a_report_profile_reports_the_workflow_as_stale(self) -> None:
        self.select(["single-ticket", "bug-triage"])
        self.render()
        self.select(["bug-triage"])
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertIn("stale ci-job.checks", log)
        self.assertIn("stale check.k6", log)


class WhenComponentsWithACustomProfileTest(FrameworkCopy):
    def test_ac2_g3_without_k6_writes_the_workflow_and_not_the_k6_check(self) -> None:
        self.add_profile("g3-only", "required", ["K13", "K14", "K17"])
        self.select(["g3-only"])
        self.render()
        self.assertTrue((self.root / WORKFLOW).exists())
        self.assertFalse((self.root / K6).exists())

    def test_ac2_k6_without_g3_writes_the_k6_check_and_not_the_workflow(self) -> None:
        self.add_profile("k6-only", "skip", ["K6", "K17"])
        self.select(["k6-only"])
        self.render()
        self.assertFalse((self.root / WORKFLOW).exists())
        self.assertTrue((self.root / K6).exists())

    def test_ac2_a_g3_value_that_is_not_skip_writes_the_workflow(self) -> None:
        for value in ("human", "if-needed"):
            with self.subTest(g3=value):
                self.add_profile("g3-value", value, ["K17"])
                self.select(["g3-value"])
                self.render()
                self.assertTrue((self.root / WORKFLOW).exists())
                (self.root / WORKFLOW).unlink()
                (self.root / MANIFEST).unlink()


# AC3: a profile with a role that has no role file is skipped.

class MissingRoleFileTest(FrameworkCopy):
    def test_ac3_profile_with_a_missing_role_is_skipped_and_names_the_role(self) -> None:
        self.remove_roles("investigator")
        self.select(["single-ticket", "bug-triage"])
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        lines = [line for line in log.splitlines() if "bug-triage" in line]
        self.assertTrue(lines, log)
        self.assertTrue(any("investigator" in line for line in lines), log)
        self.assertEqual(sorted(result.wrote), expected_files(["single-ticket"]))
        self.assertFalse((self.root / INVESTIGATOR).exists())

    def test_ac3_shared_roles_of_a_skipped_profile_come_only_from_the_others(self) -> None:
        # debugging has the investigator plus the single-ticket roles except the shaper.
        self.remove_roles("investigator")
        self.select(["debugging", "app-slice"])
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertTrue(any("debugging" in line and "investigator" in line
                            for line in log.splitlines()), log)
        self.assertNotIn("skipped profile app-slice", log)
        self.assertEqual(sorted(result.wrote), expected_files(["app-slice"]))

    def test_ac3_each_skipped_profile_names_its_missing_roles(self) -> None:
        self.remove_roles("investigator", "planner")
        self.select(["single-ticket", "app-slice", "spike", "full-project"])
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        for name, role in (("app-slice", "planner"), ("spike", "investigator"),
                           ("full-project", "planner")):
            with self.subTest(profile=name):
                self.assertTrue(any(name in line and role in line
                                    for line in log.splitlines()), log)
        self.assertNotIn("skipped profile single-ticket", log)
        self.assertEqual(sorted(result.wrote), expected_files(["single-ticket"]))

    def test_ac3_the_skip_does_not_raise(self) -> None:
        self.remove_roles("investigator")
        self.select(["single-ticket", "code-audit"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["render", "--root", str(self.root),
                             "--framework", str(self.framework)])
        self.assertEqual(code, 0, out.getvalue())


# AC4: the investigator role file.

class InvestigatorFileTest(RenderBase):
    def render_investigator(self, reports: str | None) -> str:
        self.select(["bug-triage"], f"  reports: {reports}\n" if reports else "")
        result, _ = self.render()
        self.assertEqual(result.exit_code, 0)
        return self.read(INVESTIGATOR)

    def test_ac4_default_reports_path(self) -> None:
        text = self.render_investigator(None)
        self.assertIn("`docs/reports/<ticket-id>.md`", text)
        self.assertIn("Write only in `docs/reports/`", text)
        self.assertNotIn("$", text)

    def test_ac4_reports_path_from_the_config(self) -> None:
        text = self.render_investigator("work/findings/")
        self.assertIn("`work/findings/<ticket-id>.md`", text)
        self.assertIn("`work/findings/`", text)
        self.assertNotIn("docs/reports", text)
        self.assertNotIn("$", text)

    def test_ac4_reports_path_with_no_trailing_slash_gets_one(self) -> None:
        text = self.render_investigator("work/findings")
        self.assertIn("`work/findings/<ticket-id>.md`", text)
        self.assertIn("`work/findings/`", text)
        self.assertNotIn("work/findings<", text)
        self.assertNotIn("`work/findings`", text)

    def test_ac4_reports_path_with_and_without_slash_render_the_same(self) -> None:
        self.render_investigator("work/findings/")
        with_slash = {path: self.read(path) for path in self.written_files()}
        self.tearDown()
        self.setUp()
        self.render_investigator("work/findings")
        self.assertEqual({path: self.read(path) for path in self.written_files()}, with_slash)

    def test_ac4_investigator_uses_the_model_of_the_model_profile(self) -> None:
        path = FRAMEWORK / "adapters/claude-code/models/claude-5.yaml"
        model = yaml.safe_load(path.read_text(encoding="utf-8"))["defaults"]["role_models"][
            "investigator"]
        text = self.render_investigator(None)
        self.assertIn(f"model: {model}", text)
        self.assertEqual(split_frontmatter(text)[0]["model"], model)

    def test_ac4_frontmatter_names_the_investigator(self) -> None:
        meta = split_frontmatter(self.render_investigator(None))[0]
        self.assertEqual(meta["name"], "investigator")

    def test_ac4_new_reports_path_updates_the_role_file_and_the_hook(self) -> None:
        self.render_investigator(None)
        self.select(["bug-triage"], "  reports: work/findings/\n")
        result, _ = self.render()
        self.assertEqual(result.drift, [])
        self.assertIn(INVESTIGATOR, result.wrote)
        self.assertIn(HOOK, result.wrote)
        self.assertIn("`work/findings/`", self.read(INVESTIGATOR))
        self.assertEqual(self.hook("work/findings/T-1.md", "investigator"), 0)
        self.assertEqual(self.hook("docs/reports/T-1.md", "investigator"), 2)


class InvestigatorModelTest(FrameworkCopy):
    def test_ac4_investigator_model_comes_from_its_own_role_model(self) -> None:
        self.set_role_model("investigator", "model-for-investigator")
        self.select(["bug-triage", "single-ticket"])
        self.render()
        self.assertEqual(split_frontmatter(self.read(INVESTIGATOR))[0]["model"],
                         "model-for-investigator")
        self.assertNotIn("model-for-investigator", self.read(role_file("tester")))


# AC5: the hook rule for the investigator.

class InvestigatorHookTest(RenderBase):
    def setUp(self) -> None:
        super().setUp()
        self.select(["bug-triage"])
        self.render()

    def test_ac5_investigator_writes_in_the_reports_path(self) -> None:
        for path in ("docs/reports/T-1.md", "docs/reports/sub/T-1.md"):
            with self.subTest(path=path):
                self.assertEqual(self.hook(path, "investigator"), 0)

    def test_ac5_investigator_cannot_write_outside_the_reports_path(self) -> None:
        for path in ("src/a.py", "tests/test_a.py", "docs/plans/T-1.md", "docs/specs/a.md",
                     "docs/reportsx/a.md", "docs/reports.md", "docs/a.md", "README.md",
                     ".github/workflows/ci.yml", ".claude/agents/investigator.md",
                     ".claude/settings.json", ".cornerstone/config.yaml", HOOK):
            with self.subTest(path=path):
                self.assertEqual(self.hook(path, "investigator"), 2)

    def test_ac5_investigator_block_message_names_the_path(self) -> None:
        run = self.run_hook("src/a.py", "investigator")
        self.assertEqual(run.returncode, 2)
        self.assertIn("src/a.py", run.stderr)
        self.assertIn("docs/reports/", run.stderr)

    def test_ac5_investigator_on_a_main_branch_is_limited(self) -> None:
        self.git_repo_on("main")
        self.assertEqual(self.hook("docs/reports/T-1.md", "investigator"), 0)
        self.assertEqual(self.hook("src/a.py", "investigator"), 2)

    def test_ac5_investigator_on_a_spike_branch_writes_any_path(self) -> None:
        self.git_repo_on("spike/can-x-do-y")
        for path in ("src/a.py", "src/new/b.py", "tests/test_a.py", "README.md",
                     "docs/plans/T-1.md", "docs/specs/a.md", ".github/workflows/ci.yml",
                     "docs/reports/T-1.md"):
            with self.subTest(path=path):
                self.assertEqual(self.hook(path, "investigator"), 0)

    def test_ac5_investigator_on_a_spike_branch_cannot_write_harness_paths(self) -> None:
        self.git_repo_on("spike/can-x-do-y")
        for path in (".claude/settings.json", ".claude/agents/investigator.md",
                     ".claude/new.md", ".cornerstone/config.yaml", HOOK, K6,
                     ".cornerstone/manifest.yaml"):
            with self.subTest(path=path):
                self.assertEqual(self.hook(path, "investigator"), 2)

    def test_ac5_branch_names_without_the_spike_prefix_are_limited(self) -> None:
        for branch in ("spikes/x", "spike-x", "feature/spike/x", "fix/spike", "spike"):
            with self.subTest(branch=branch):
                shutil.rmtree(self.root / ".git", ignore_errors=True)
                self.git_repo_on(branch)
                self.assertEqual(self.hook("src/a.py", "investigator"), 2)
                self.assertEqual(self.hook("docs/reports/T-1.md", "investigator"), 0)

    def test_ac5_spike_rule_uses_the_branch_of_the_worktree(self) -> None:
        self.git_repo_on("main")
        self.git("worktree", "add", "-q", "-b", "spike/q", ".claude/worktrees/q")
        tree = ".claude/worktrees/q/"
        self.assertEqual(self.hook(tree + "src/a.py", "investigator"), 0)
        self.assertEqual(self.hook(tree + "tests/test_a.py", "investigator"), 0)
        self.assertEqual(self.hook(tree + ".claude/settings.json", "investigator"), 2)
        self.assertEqual(self.hook(tree + ".cornerstone/config.yaml", "investigator"), 2)
        self.assertEqual(self.hook("src/a.py", "investigator"), 2)

    def test_ac5_worktree_on_a_normal_branch_is_limited(self) -> None:
        self.git_repo_on("spike/q")
        self.git("worktree", "add", "-q", "-b", "feature/x", ".claude/worktrees/x")
        tree = ".claude/worktrees/x/"
        self.assertEqual(self.hook(tree + "src/a.py", "investigator"), 2)
        self.assertEqual(self.hook(tree + "docs/reports/T-1.md", "investigator"), 0)


class InvestigatorHookCustomPathTest(RenderBase):
    def test_ac5_hook_uses_the_reports_path_from_the_config(self) -> None:
        self.select(["bug-triage"], "  reports: work/findings\n")
        self.render()
        self.assertEqual(self.hook("work/findings/T-1.md", "investigator"), 0)
        self.assertEqual(self.hook("work/findingsx/T-1.md", "investigator"), 2)
        self.assertEqual(self.hook("work/findings.md", "investigator"), 2)
        self.assertEqual(self.hook("docs/reports/T-1.md", "investigator"), 2)

    def test_ac5_reports_path_list_of_one_folder_works(self) -> None:
        self.select(["bug-triage"], "  reports: [work/findings/]\n")
        result, _ = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.hook("work/findings/T-1.md", "investigator"), 0)
        self.assertEqual(self.hook("src/a.py", "investigator"), 2)


# AC6: the hook rules for the other roles do not change.

class OtherRoleHookTest(RenderBase):
    # (role, path, exit code) from the rules in the hook before this change.
    RULES = [
        ("implementer", "src/a.py", 0),
        ("implementer", "docs/reports/T-1.md", 0),
        ("implementer", "docs/plans/T-1.md", 0),
        ("implementer", "tests/test_a.py", 2),
        ("implementer", ".github/workflows/ci.yml", 2),
        ("implementer", ".cornerstone/checks/protected_paths.py", 2),
        ("implementer", ".claude/settings.json", 2),
        ("implementer", "docs/specs/a.md", 2),
        ("tester", "tests/test_a.py", 0),
        ("tester", "src/a.py", 2),
        ("tester", "docs/reports/T-1.md", 2),
        ("tester", "docs/plans/T-1.md", 2),
        ("planner", "docs/plans/T-1.md", 0),
        ("planner", "src/a.py", 2),
        ("planner", "docs/reports/T-1.md", 2),
        ("planner", "tests/test_a.py", 2),
        ("planner", "docs/specs/a.md", 2),
        ("reviewer", "src/a.py", 2),
        ("reviewer", "docs/reports/T-1.md", 2),
        ("reviewer", "docs/plans/T-1.md", 2),
        ("shaper", "src/a.py", 0),
        ("shaper", "docs/reports/T-1.md", 0),
    ]

    def assert_rules(self) -> None:
        for role, path, code in self.RULES:
            with self.subTest(role=role, path=path):
                self.assertEqual(self.hook(path, role), code)

    def test_ac6_other_roles_keep_their_rules_with_all_profiles(self) -> None:
        self.select(profile_names())
        self.render()
        self.assert_rules()

    def test_ac6_other_roles_keep_their_rules_with_single_ticket_only(self) -> None:
        self.render()
        self.assert_rules()

    def test_ac6_spike_branch_does_not_free_the_other_roles(self) -> None:
        self.select(profile_names())
        self.render()
        self.git_repo_on("spike/q")
        self.assert_rules()

    def test_ac6_default_role_is_still_the_implementer(self) -> None:
        self.select(["bug-triage", "single-ticket"])
        self.render()
        event = json.dumps({"tool_input": {"file_path": str(self.root / "tests/test_a.py")}})
        env = {k: v for k, v in os.environ.items() if k != "STONE_ROLE"}
        env["CLAUDE_PROJECT_DIR"] = str(self.root)
        run = subprocess.run([sys.executable, HOOK], cwd=self.root, input=event, env=env,
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)


# AC7: a second render with all profiles writes nothing.

class AllProfilesTest(RenderBase):
    def setUp(self) -> None:
        super().setUp()
        self.select(profile_names())

    def test_ac7_all_profiles_render_every_component(self) -> None:
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("skipped profile", log)
        want = ([role_file(role) for role in ALL_ROLES] + ALWAYS + [WORKFLOW, K6, K7]
                + trigger_files(profile_names()))
        if any("K15" in profile_data(name)["checks"] for name in profile_names()):
            want.append(K15)
        if any("K16" in profile_data(name)["checks"] for name in profile_names()):
            want.append(K16_WORKFLOW)
        self.assertEqual(sorted(result.wrote), sorted(want))

    def test_ac7_second_render_with_all_profiles_writes_nothing(self) -> None:
        self.render()
        before = {path: self.read(path) for path in self.written_files()}
        result, _ = self.render(today=TODAY + dt.timedelta(days=30))
        self.assertEqual(result.wrote, [])
        self.assertEqual(result.drift, [])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual({path: self.read(path) for path in self.written_files()}, before)

    def test_ac7_second_render_from_the_cli_reports_0_written(self) -> None:
        self.render()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["render", "--root", str(self.root), "--framework", str(FRAMEWORK)])
        self.assertEqual(code, 0)
        self.assertIn("0 written", out.getvalue())


if __name__ == "__main__":
    unittest.main()
