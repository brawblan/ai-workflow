"""Tests for check K15 (instruction size) in `stone render`, roadmap item 6c.

Each test renders into a temporary repo. A test that changes the model profile or a profile
renders with a copy of the framework in this repo.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
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
MODEL_PROFILE = Path("adapters/claude-code/models/claude-5.yaml")
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
K15 = ".cornerstone/checks/instruction_size.py"
WORKFLOW = ".github/workflows/cornerstone-checks.yml"
MANIFEST = ".cornerstone/manifest.yaml"
K15_STEP = "K15 instruction size"
K15_RUN = "python3 .cornerstone/checks/instruction_size.py --mode block --format github"


def profile_names(framework: Path = FRAMEWORK) -> list[str]:
    return sorted(p.stem for p in (framework / "profiles").glob("*.md")
                  if p.stem not in {"README", "_template"})


def profile_checks(name: str, framework: Path = FRAMEWORK) -> list[str]:
    text = (framework / "profiles" / f"{name}.md").read_text(encoding="utf-8")
    return split_frontmatter(text)[0]["checks"]


def model_limit(framework: Path = FRAMEWORK) -> int:
    data = yaml.safe_load((framework / MODEL_PROFILE).read_text(encoding="utf-8"))
    return data["defaults"]["instruction_file_max_lines"]


class K15Base(unittest.TestCase):
    framework = FRAMEWORK

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name) / "repo"
        (self.root / ".cornerstone").mkdir(parents=True)
        self.select(["single-ticket"])

    def tearDown(self) -> None:
        self.folder.cleanup()

    def select(self, names: list[str]) -> None:
        text = CONFIG.replace("[single-ticket]", "[" + ", ".join(names) + "]")
        (self.root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")

    def render(self, today: dt.date = TODAY) -> render.Result:
        with contextlib.redirect_stderr(io.StringIO()):
            return render.render(self.root, self.framework, today=today)

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def written_files(self) -> list[str]:
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")
                      if p.is_file()
                      and p.relative_to(self.root).as_posix() != ".cornerstone/config.yaml")

    def manifest_entry(self, component_id: str) -> dict | None:
        components = yaml.safe_load(self.read(MANIFEST))["components"]
        return next((c for c in components if c["id"] == component_id), None)

    def workflow_steps(self) -> list[dict]:
        return yaml.safe_load(self.read(WORKFLOW))["jobs"]["checks"]["steps"]


class FrameworkCopy(K15Base):
    def setUp(self) -> None:
        super().setUp()
        self.framework = Path(self.folder.name) / "framework"
        shutil.copytree(FRAMEWORK, self.framework)

    def set_limit(self, value: object, remove: bool = False) -> None:
        path = self.framework / MODEL_PROFILE
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if remove:
            del data["defaults"]["instruction_file_max_lines"]
        else:
            data["defaults"]["instruction_file_max_lines"] = value
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def add_profile(self, name: str, g3: str, checks: list[str]) -> None:
        text = (self.framework / "profiles" / "single-ticket.md").read_text(encoding="utf-8")
        text = re.sub(r"^id: .*$", f"id: {name}", text, count=1, flags=re.M)
        text = re.sub(r"^  G3: .*$", f"  G3: {g3}", text, count=1, flags=re.M)
        text = re.sub(r"^checks: .*$", f"checks: [{', '.join(checks)}]", text, count=1,
                      flags=re.M)
        (self.framework / "profiles" / f"{name}.md").write_text(text, encoding="utf-8")


# AC1: render writes the K15 check only for a profile with K15. The limit comes from the model profile.

class K15FileTest(K15Base):
    def test_ac1_full_project_writes_the_k15_check(self) -> None:
        self.select(["full-project"])
        result = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertIn(K15, result.wrote)
        self.assertTrue((self.root / K15).is_file())

    def test_ac1_max_lines_is_the_model_profile_value(self) -> None:
        self.select(["full-project"])
        self.render()
        self.assertEqual(model_limit(), 300)
        lines = [line for line in self.read(K15).splitlines() if line.startswith("MAX_LINES")]
        self.assertEqual(lines, ["MAX_LINES = 300"])

    def test_ac1_rendered_check_has_no_placeholder_left(self) -> None:
        self.select(["full-project"])
        self.render()
        self.assertNotIn("$", self.read(K15))

    def test_ac1_rendered_check_is_valid_python(self) -> None:
        self.select(["full-project"])
        self.render()
        compile(self.read(K15), K15, "exec")

    def test_ac1_single_ticket_does_not_write_the_k15_check(self) -> None:
        result = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn(K15, result.wrote)
        self.assertFalse((self.root / K15).exists())
        self.assertIsNone(self.manifest_entry("check.k15"))

    def test_ac1_each_profile_writes_the_check_only_if_it_lists_k15(self) -> None:
        for name in profile_names():
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name])
                self.render()
                self.assertEqual((self.root / K15).exists(), "K15" in profile_checks(name))

    def test_ac1_full_project_with_single_ticket_writes_the_k15_check(self) -> None:
        self.select(["single-ticket", "full-project"])
        self.render()
        self.assertTrue((self.root / K15).is_file())

    def test_ac1_second_render_writes_nothing(self) -> None:
        self.select(["full-project"])
        self.render()
        before = self.read(K15)
        result = self.render(today=TODAY + dt.timedelta(days=30))
        self.assertEqual(result.wrote, [])
        self.assertEqual(result.drift, [])
        self.assertEqual(self.read(K15), before)


class K15LimitFromACopiedModelProfileTest(FrameworkCopy):
    def test_ac1_copied_model_profile_with_another_limit_changes_the_check(self) -> None:
        self.set_limit(120)
        self.select(["full-project"])
        self.render()
        self.assertIn("MAX_LINES = 120\n", self.read(K15))
        self.assertNotIn("300", self.read(K15))

    def test_ac1_new_limit_rewrites_the_check_on_the_next_render(self) -> None:
        self.select(["full-project"])
        self.render()
        self.set_limit(250)
        result = self.render()
        self.assertEqual(result.drift, [])
        self.assertIn(K15, result.wrote)
        self.assertIn("MAX_LINES = 250\n", self.read(K15))

    def test_ac1_custom_profile_with_k15_and_no_g3_writes_only_the_check(self) -> None:
        self.add_profile("k15-only", "skip", ["K15", "K17"])
        self.select(["k15-only"])
        result = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertTrue((self.root / K15).is_file())
        self.assertFalse((self.root / WORKFLOW).exists())


# AC2: the K15 step in the G3 workflow.

class K15WorkflowStepTest(K15Base):
    def test_ac2_full_project_workflow_has_the_k15_step(self) -> None:
        self.select(["full-project"])
        self.render()
        steps = [step for step in self.workflow_steps() if step.get("name") == K15_STEP]
        self.assertEqual(len(steps), 1, self.read(WORKFLOW))
        self.assertEqual(steps[0]["run"], K15_RUN)

    def test_ac2_k15_step_is_after_k14_and_before_install(self) -> None:
        self.select(["full-project"])
        self.render()
        names = [step.get("name") for step in self.workflow_steps()]
        self.assertIn("K14 PR evidence", names)
        self.assertIn("Install", names)
        k14, k15, install = (names.index("K14 PR evidence"), names.index(K15_STEP),
                             names.index("Install"))
        self.assertEqual(k15, k14 + 1, names)
        self.assertEqual(install, k15 + 1, names)

    def test_ac2_full_project_workflow_has_no_placeholder_and_no_double_blank_line(self) -> None:
        self.select(["full-project"])
        self.render()
        text = self.read(WORKFLOW)
        self.assertNotIn("ci_step", text)
        self.assertNotIn("\n\n\n", text)
        self.assertNotRegex(text, r"\$(command|paths|branch|framework|ci_step)")

    def test_ac2_single_ticket_workflow_has_no_k15_step(self) -> None:
        self.render()
        text = self.read(WORKFLOW)
        self.assertNotIn("K15", text)
        self.assertNotIn("instruction_size", text)
        self.assertNotIn("ci_step", text)
        self.assertNotIn(K15_STEP, [step.get("name") for step in self.workflow_steps()])

    def test_ac2_single_ticket_steps_have_exactly_one_blank_line_between_them(self) -> None:
        self.render()
        text = self.read(WORKFLOW)
        self.assertNotIn("\n\n\n", text)
        self.assertIn("--mode block --format github\n\n      - name: Install\n", text)
        lines = text.splitlines()
        steps_at = lines.index("    steps:")
        for number, line in enumerate(lines):
            if not line.startswith("      - ") or number == steps_at + 1:
                continue
            start = number
            while lines[start - 1].startswith("      #"):
                start -= 1  # a comment line belongs to the step under it
            with self.subTest(line=line):
                self.assertEqual(lines[start - 1], "", lines[start - 3:number + 1])
                self.assertNotEqual(lines[start - 2], "", lines[start - 3:number + 1])

    def test_ac2_single_ticket_workflow_is_full_project_without_the_k15_step(self) -> None:
        self.render()
        single = self.read(WORKFLOW)
        self.tearDown()
        self.setUp()
        self.select(["full-project"])
        self.render()
        full = self.read(WORKFLOW)
        block = re.search(r"(?:      #[^\n]*\n)?      - name: K15 instruction size\n.*?\n\n",
                          full, flags=re.S)
        self.assertIsNotNone(block, full)
        self.assertEqual(full.replace(block.group(0), "", 1), single)

    def test_ac2_each_profile_with_g3_has_the_k15_step_only_if_it_lists_k15(self) -> None:
        for name in profile_names():
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.select([name])
                self.render()
                if not (self.root / WORKFLOW).exists():
                    continue
                names = [step.get("name") for step in self.workflow_steps()]
                self.assertEqual(K15_STEP in names, "K15" in profile_checks(name))
                self.assertNotIn("ci_step", self.read(WORKFLOW))


# AC3: the rendered script, run in the repo root.

class K15ScriptTest(K15Base):
    def setUp(self) -> None:
        super().setUp()
        self.select(["full-project"])
        self.render()
        self.limit = model_limit()

    def write(self, name: str, lines: int) -> None:
        (self.root / name).write_text("".join(f"line {n}\n" for n in range(lines)),
                                      encoding="utf-8")

    def run_check(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, K15, *args], cwd=self.root,
                              capture_output=True, text=True)

    def test_ac3_missing_agents_md_gives_a_finding_and_exit_1(self) -> None:
        run = self.run_check()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("AGENTS.md", run.stdout)
        self.assertIn("1 finding(s)", run.stdout)

    def test_ac3_default_mode_is_block(self) -> None:
        self.write("AGENTS.md", self.limit + 1)
        self.assertEqual(self.run_check().returncode, 1)
        self.assertEqual(self.run_check("--mode", "block").returncode, 1)

    def test_ac3_line_count_equal_to_the_limit_passes(self) -> None:
        self.write("AGENTS.md", self.limit)
        run = self.run_check()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("0 finding(s)", run.stdout)

    def test_ac3_short_file_passes(self) -> None:
        self.write("AGENTS.md", 10)
        run = self.run_check()
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertIn("0 finding(s)", run.stdout)

    def test_ac3_limit_plus_1_names_the_line_count_and_the_limit(self) -> None:
        self.write("AGENTS.md", self.limit + 1)
        run = self.run_check()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("1 finding(s)", run.stdout)
        finding = [line for line in run.stdout.splitlines() if "AGENTS.md" in line]
        self.assertTrue(finding, run.stdout)
        self.assertIn(str(self.limit + 1), finding[0])
        self.assertIn(str(self.limit), finding[0].replace(str(self.limit + 1), ""))

    def test_ac3_warn_mode_exits_0_and_prints_the_finding(self) -> None:
        self.write("AGENTS.md", self.limit + 1)
        run = self.run_check("--mode", "warn")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(f"{self.limit + 1}", run.stdout)
        self.assertIn("1 finding(s)", run.stdout)

    def test_ac3_warn_mode_with_no_agents_md_exits_0_and_prints_the_finding(self) -> None:
        run = self.run_check("--mode", "warn")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("AGENTS.md", run.stdout)
        self.assertIn("1 finding(s)", run.stdout)

    def test_ac3_github_format_in_warn_mode_prints_a_warning(self) -> None:
        self.write("AGENTS.md", self.limit + 1)
        run = self.run_check("--mode", "warn", "--format", "github")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("::warning file=AGENTS.md::", run.stdout)
        self.assertNotIn("::error", run.stdout)

    def test_ac3_github_format_in_block_mode_prints_an_error(self) -> None:
        self.write("AGENTS.md", self.limit + 1)
        run = self.run_check("--mode", "block", "--format", "github")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("::error file=AGENTS.md::", run.stdout)
        self.assertNotIn("::warning", run.stdout)

    def test_ac3_github_format_with_no_finding_prints_no_annotation(self) -> None:
        self.write("AGENTS.md", self.limit)
        run = self.run_check("--mode", "block", "--format", "github")
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertNotIn("::", run.stdout)

    def test_ac3_ci_step_command_blocks_and_fails_the_job(self) -> None:
        self.write("AGENTS.md", self.limit + 1)
        steps = yaml.safe_load(self.read(WORKFLOW))["jobs"]["checks"]["steps"]
        command = next(step["run"] for step in steps if step.get("name") == K15_STEP).split()
        self.assertEqual(command[:2], ["python3", K15])
        run = self.run_check(*command[2:])
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("::error file=AGENTS.md::", run.stdout)

    def test_ac3_only_agents_md_counts(self) -> None:
        self.write("AGENTS.md", 1)
        self.write("CLAUDE.md", self.limit * 3)
        run = self.run_check()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("0 finding(s)", run.stdout)
        self.assertNotIn("CLAUDE.md", run.stdout)

    def test_ac3_long_claude_md_without_agents_md_still_fails(self) -> None:
        self.write("CLAUDE.md", 1)
        run = self.run_check()
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("AGENTS.md", run.stdout)

    def test_ac3_agents_md_in_a_subfolder_does_not_count(self) -> None:
        (self.root / "docs").mkdir()
        self.write("docs/AGENTS.md", self.limit + 50)
        self.write("AGENTS.md", 5)
        self.assertEqual(self.run_check().returncode, 0)


class K15ScriptWithACopiedLimitTest(FrameworkCopy):
    def test_ac3_script_uses_the_limit_of_the_copied_model_profile(self) -> None:
        self.set_limit(5)
        self.select(["full-project"])
        self.render()
        for lines, code in ((5, 0), (6, 1)):
            with self.subTest(lines=lines):
                (self.root / "AGENTS.md").write_text("x\n" * lines, encoding="utf-8")
                run = subprocess.run([sys.executable, K15], cwd=self.root,
                                     capture_output=True, text=True)
                self.assertEqual(run.returncode, code, run.stdout + run.stderr)


# AC4: the manifest entry.

class K15ManifestTest(K15Base):
    def test_ac4_manifest_has_the_check_k15_entry(self) -> None:
        self.select(["full-project"])
        self.render()
        entry = self.manifest_entry("check.k15")
        self.assertIsNotNone(entry, self.read(MANIFEST))
        self.assertEqual(entry["kind"], "check")
        self.assertEqual(entry["eval"], "evals/check-k15/")
        self.assertEqual(entry["files"], [K15])

    def test_ac4_review_by_is_6_months_after_added(self) -> None:
        self.select(["full-project"])
        self.render()
        entry = self.manifest_entry("check.k15")
        self.assertEqual(str(entry["added"]), "2026-10-18")
        self.assertEqual(str(entry["review_by"]), "2027-04-18")

    def test_ac4_review_by_at_the_end_of_a_month(self) -> None:
        self.select(["full-project"])
        self.render(today=dt.date(2026, 8, 31))
        entry = self.manifest_entry("check.k15")
        self.assertEqual(str(entry["added"]), "2026-08-31")
        self.assertEqual(str(entry["review_by"]), "2027-02-28")

    def test_ac4_second_render_keeps_added_and_review_by(self) -> None:
        self.select(["full-project"])
        self.render()
        self.render(today=TODAY + dt.timedelta(days=40))
        entry = self.manifest_entry("check.k15")
        self.assertEqual(str(entry["added"]), "2026-10-18")
        self.assertEqual(str(entry["review_by"]), "2027-04-18")


# AC5: a profile with K15 needs the limit in the model profile.

class K15MissingLimitTest(FrameworkCopy):
    def assert_render_error(self) -> str:
        with self.assertRaises(render.RenderError) as caught:
            self.render()
        message = str(caught.exception)
        self.assertIn("defaults.instruction_file_max_lines", message)
        self.assertIn("claude-5", message)
        self.assertEqual(self.written_files(), [])
        return message

    def test_ac5_missing_limit_with_full_project_raises_and_writes_nothing(self) -> None:
        self.set_limit(None, remove=True)
        self.select(["full-project"])
        self.assert_render_error()

    def test_ac5_null_limit_with_full_project_raises_and_writes_nothing(self) -> None:
        self.set_limit(None)
        self.select(["full-project"])
        self.assert_render_error()

    def test_ac5_missing_limit_with_k15_among_other_profiles_raises(self) -> None:
        self.set_limit(None, remove=True)
        self.select(["single-ticket", "full-project"])
        self.assert_render_error()

    def test_ac5_missing_limit_does_not_change_an_earlier_render(self) -> None:
        self.select(["full-project"])
        self.render()
        before = {path: self.read(path) for path in self.written_files()}
        self.set_limit(None, remove=True)
        with self.assertRaises(render.RenderError):
            self.render(today=TODAY + dt.timedelta(days=1))
        self.assertEqual({path: self.read(path) for path in self.written_files()}, before)

    def test_ac5_cli_prints_the_error_and_exits_1(self) -> None:
        self.set_limit(None, remove=True)
        self.select(["full-project"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["render", "--root", str(self.root),
                             "--framework", str(self.framework)])
        self.assertEqual(code, 1)
        self.assertIn("defaults.instruction_file_max_lines", out.getvalue())
        self.assertIn("claude-5", out.getvalue())
        self.assertEqual(self.written_files(), [])

    def test_ac5_missing_limit_without_a_k15_profile_renders(self) -> None:
        self.set_limit(None, remove=True)
        for names in (["single-ticket"], ["bug-triage"], ["app-slice", "debugging"]):
            with self.subTest(profiles=names):
                # A new repo for each set. Files from an earlier set (for example the K7
                # limit of another profile) are drift, which is not what this test is about.
                self.root = Path(self.folder.name) / ("repo-" + "-".join(names))
                (self.root / ".cornerstone").mkdir(parents=True)
                self.select(names)
                result = self.render()
                self.assertEqual(result.exit_code, 0)
                self.assertFalse((self.root / K15).exists())
                self.assertNotIn("instruction_size", self.read(WORKFLOW)
                                 if (self.root / WORKFLOW).exists() else "")


if __name__ == "__main__":
    unittest.main()
