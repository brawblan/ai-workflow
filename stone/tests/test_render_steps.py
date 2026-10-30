"""Tests for the optional G3 steps of the "by profile" checks K4, K5, K8, K10, K11, K12 (D29).

Each test class renders into a temporary repo with the real framework in this repo, or with a
copy of it when a test must change a template or add a profile.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from stone import cli, render

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
COMPONENTS = FRAMEWORK / "adapters" / "claude-code" / "components.yaml"
TEMPLATE = "adapters/claude-code/templates/workflows/cornerstone-checks.yml"
TODAY = dt.date(2026, 10, 18)
WORKFLOW = ".github/workflows/cornerstone-checks.yml"
MANIFEST = ".cornerstone/manifest.yaml"
BASE_COMMANDS = {"install": "pip install .", "test_unit": "python -m unittest",
                 "all_checks": "make check"}
# The example commands of customization.md, "Commands for the by-profile checks".
CHECK_COMMANDS = {"test_integration": "pytest tests/integration",
                  "test_acceptance": "npx playwright test",
                  "architecture": "lint-imports",
                  "property": "pytest tests/property",
                  "differential": "pytest tests/differential",
                  "mutation": "scripts/mutation-score.sh"}
# check -> (step name, command key), from the ticket and the steps of ci-job.checks.
STEPS = {"K4": ("K4 integration tests", "test_integration"),
         "K5": ("K5 acceptance tests", "test_acceptance"),
         "K8": ("K8 architecture fitness", "architecture"),
         "K10": ("K10 mutation score", "mutation"),
         "K11": ("K11 property and fuzz tests", "property"),
         "K12": ("K12 differential tests", "differential")}
K20_STEP = "K20 specialist findings"  # no command key: it renders only with a specialists section (D66)
K23_STEP = "K23 new dependencies"  # no command key; it renders from framework 1.5.0 (D90)
K24_STEP = "K24 unpinned tools"  # no command key; it renders from framework 1.5.0 (D93)
STEP_NAMES = {name for name, _ in STEPS.values()} | {K20_STEP}
LIMIT = "limits.mutation_score_changed_code"
CHECK_WARNING = re.compile(r"\bK(4|5|8|10|11|12)\b|commands\.")


def config_text(profiles: list[str], commands: dict[str, Any] | None = None,
                limits: dict[str, Any] | None = None) -> str:
    data: dict[str, Any] = {
        "framework_version": "0.8.0",
        "harness": "claude-code",
        "model_profile": "claude-5",
        "profiles": profiles,
        "branches": {"integration": "dev", "main": "main"},
        "commands": {**BASE_COMMANDS, **(commands or {})},
        "paths": {"tests": ["tests/"], "checks": [".github/workflows/", ".cornerstone/checks/"],
                  "plans": "docs/plans/"},
        "owners": {"default": "octocat"},
    }
    if limits is not None:
        data["limits"] = limits
    return yaml.safe_dump(data, sort_keys=False)


def registry_step_names() -> list[str]:
    """Return the step names of ci-job.checks in the order of components.yaml."""
    data = yaml.safe_load(COMPONENTS.read_text(encoding="utf-8"))
    entry = next(c for c in data["components"] if c["id"] == "ci-job.checks")
    return [step["name"] for step in entry["steps"]]


class StepsBase(unittest.TestCase):
    framework = FRAMEWORK

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name) / "repo"
        (self.root / ".cornerstone").mkdir(parents=True)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def configure(self, profiles: list[str], commands: dict[str, Any] | None = None,
                  limits: dict[str, Any] | None = None) -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(
            config_text(profiles, commands, limits), encoding="utf-8")

    def render(self, today: dt.date = TODAY) -> tuple[render.Result, str]:
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            result = render.render(self.root, self.framework, today=today)
        return result, log.getvalue()

    def cli_render(self) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["render", "--root", str(self.root),
                             "--framework", str(self.framework)])
        return code, out.getvalue(), err.getvalue()

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def written_files(self) -> list[str]:
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*")
                      if p.is_file()
                      and p.relative_to(self.root).as_posix() != ".cornerstone/config.yaml")

    def steps(self) -> list[dict[str, Any]]:
        return yaml.safe_load(self.read(WORKFLOW))["jobs"]["checks"]["steps"]

    def step_names(self) -> list[str]:
        return [step.get("name", "") for step in self.steps()]

    def step(self, name: str) -> dict[str, Any]:
        found = [step for step in self.steps() if step.get("name") == name]
        self.assertEqual(len(found), 1, f"{name!r} in {self.step_names()}")
        return found[0]

    def optional_steps(self) -> list[str]:
        return [name for name in self.step_names() if name in STEP_NAMES]

    def warnings(self, log: str) -> list[str]:
        """Return the warnings about a "by profile" check. Other warnings are out of scope."""
        return [line for line in log.splitlines()
                if line.startswith("warning:") and CHECK_WARNING.search(line)]


class FrameworkCopy(StepsBase):
    """Render with a copy of the framework that a test can change."""

    def setUp(self) -> None:
        super().setUp()
        self.framework = Path(self.folder.name) / "framework"
        shutil.copytree(FRAMEWORK, self.framework)

    def add_profile(self, name: str, checks: list[str]) -> None:
        """Add a profile with a G3 gate, from single-ticket, with these checks."""
        text = (self.framework / "profiles" / "single-ticket.md").read_text(encoding="utf-8")
        text = re.sub(r"^id: .*$", f"id: {name}", text, count=1, flags=re.M)
        text = re.sub(r"^checks: .*$", f"checks: [{', '.join(checks)}]", text, count=1,
                      flags=re.M)
        (self.framework / "profiles" / f"{name}.md").write_text(text, encoding="utf-8")


# AC1: the K10 step.

class K10StepTest(StepsBase):
    def test_ac1_refactor_migration_has_the_k10_step_with_the_command(self) -> None:
        self.configure(["refactor-migration"], CHECK_COMMANDS,
                       {"mutation_score_changed_code": 0.6})
        result, _ = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.step("K10 mutation score")["run"], CHECK_COMMANDS["mutation"])

    def test_ac1_k10_step_has_base_ref_and_mutation_score_min(self) -> None:
        self.configure(["refactor-migration"], {"mutation": "mutmut run"},
                       {"mutation_score_changed_code": 0.6})
        self.render()
        env = self.step("K10 mutation score")["env"]
        self.assertEqual(sorted(env), ["BASE_REF", "MUTATION_SCORE_MIN"])
        self.assertEqual(str(env["MUTATION_SCORE_MIN"]), "0.6")
        self.assertIn("github.base_ref", str(env["BASE_REF"]))
        self.assertTrue(str(env["BASE_REF"]).startswith("origin/"), env["BASE_REF"])

    def test_ac1_mutation_score_min_comes_from_the_limit_in_the_config(self) -> None:
        for limit in (0.75, 0.8, 1):
            with self.subTest(limit=limit):
                self.configure(["refactor-migration"], {"mutation": "mutmut run"},
                               {"mutation_score_changed_code": limit})
                self.render()
                env = self.step("K10 mutation score")["env"]
                self.assertEqual(str(env["MUTATION_SCORE_MIN"]), str(limit))

    def test_ac1_app_slice_also_gets_the_k10_step(self) -> None:
        self.configure(["app-slice"], {"mutation": "npx stryker run"},
                       {"mutation_score_changed_code": 0.6})
        result, _ = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.step("K10 mutation score")["run"], "npx stryker run")

    def test_ac1_k10_command_with_a_shell_variable_is_kept(self) -> None:
        command = 'mutmut run --since "$BASE_REF" --min "$MUTATION_SCORE_MIN"'
        self.configure(["refactor-migration"], {"mutation": command},
                       {"mutation_score_changed_code": 0.6})
        self.render()
        self.assertEqual(self.step("K10 mutation score")["run"], command)


# AC2: the K12 step.

class K12StepTest(StepsBase):
    def test_ac2_refactor_migration_has_the_k12_step_with_the_command(self) -> None:
        self.configure(["refactor-migration"], CHECK_COMMANDS,
                       {"mutation_score_changed_code": 0.6})
        self.render()
        self.assertEqual(self.step("K12 differential tests")["run"],
                         CHECK_COMMANDS["differential"])

    def test_ac2_debugging_has_only_the_k12_step(self) -> None:
        # debugging lists K12 and no other "by profile" check.
        self.configure(["debugging"], CHECK_COMMANDS)
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.optional_steps(), ["K12 differential tests"])
        self.assertEqual(self.step("K12 differential tests")["run"],
                         CHECK_COMMANDS["differential"])
        self.assertEqual(self.warnings(log), [])

    def test_ac2_k12_step_does_not_need_the_mutation_limit(self) -> None:
        self.configure(["debugging"], {"differential": "pytest tests/differential"})
        result, _ = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertIn("K12 differential tests", self.step_names())


# AC3: the same rule for K4, K5, K8, and K11.

class OtherChecksTest(StepsBase):
    def test_ac3_dependency_upgrade_has_the_k4_and_k5_steps(self) -> None:
        self.configure(["dependency-upgrade"], CHECK_COMMANDS)
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.optional_steps(), ["K4 integration tests", "K5 acceptance tests"])
        self.assertEqual(self.step("K4 integration tests")["run"],
                         CHECK_COMMANDS["test_integration"])
        self.assertEqual(self.step("K5 acceptance tests")["run"],
                         CHECK_COMMANDS["test_acceptance"])
        self.assertEqual(self.warnings(log), [])

    def test_ac3_full_project_has_the_k4_k5_and_k8_steps(self) -> None:
        self.configure(["full-project"], CHECK_COMMANDS)
        self.render()
        self.assertEqual(self.optional_steps(), ["K4 integration tests", "K5 acceptance tests",
                                                 "K8 architecture fitness"])
        self.assertEqual(self.step("K8 architecture fitness")["run"],
                         CHECK_COMMANDS["architecture"])

    def test_ac3_steps_without_k10_have_no_env(self) -> None:
        self.configure(["full-project"], CHECK_COMMANDS)
        self.render()
        for name in self.optional_steps():
            with self.subTest(step=name):
                self.assertNotIn("env", self.step(name))

    def test_ac3_k4_without_its_command_has_no_step_and_k5_still_has_one(self) -> None:
        self.configure(["dependency-upgrade"], {"test_acceptance": "npx playwright test"})
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.optional_steps(), ["K5 acceptance tests"])
        warnings = self.warnings(log)
        self.assertEqual(len(warnings), 1, log)
        self.assertIn("K4", warnings[0])
        self.assertIn("commands.test_integration", warnings[0])


class K11StepTest(FrameworkCopy):
    # No profile in the framework lists K11. This test adds one.
    def test_ac3_profile_with_k11_has_the_k11_step(self) -> None:
        self.add_profile("property-ticket", ["K6", "K11", "K14", "K17"])
        self.configure(["property-ticket"], CHECK_COMMANDS)
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.optional_steps(), ["K11 property and fuzz tests"])
        self.assertEqual(self.step("K11 property and fuzz tests")["run"],
                         CHECK_COMMANDS["property"])
        self.assertEqual(self.warnings(log), [])

    def test_ac3_profile_with_k11_and_no_command_warns(self) -> None:
        self.add_profile("property-ticket", ["K6", "K11", "K14", "K17"])
        self.configure(["property-ticket"])
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.optional_steps(), [])
        warnings = self.warnings(log)
        self.assertEqual(len(warnings), 1, log)
        for text in ("property-ticket", "K11", "commands.property"):
            self.assertIn(text, warnings[0])


# AC4: a listed check with no command has no step and one warning.

class MissingCommandTest(StepsBase):
    LIMITS = {"mutation_score_changed_code": 0.6}

    def assert_skipped_with_warning(self, profile: str, check: str, log: str) -> None:
        name, key = STEPS[check]
        self.assertNotIn(name, self.step_names())
        lines = [line for line in self.warnings(log) if check in line]
        self.assertEqual(len(lines), 1, log)
        self.assertIn(profile, lines[0])
        self.assertIn(f"commands.{key}", lines[0])

    def test_ac4_missing_mutation_command_skips_the_step_and_warns(self) -> None:
        commands = {k: v for k, v in CHECK_COMMANDS.items() if k != "mutation"}
        self.configure(["refactor-migration"], commands, self.LIMITS)
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assert_skipped_with_warning("refactor-migration", "K10", log)
        self.assertIn("K12 differential tests", self.step_names())
        self.assertIn("K8 architecture fitness", self.step_names())

    def test_ac4_missing_differential_command_skips_the_step_and_warns(self) -> None:
        commands = {k: v for k, v in CHECK_COMMANDS.items() if k != "differential"}
        self.configure(["refactor-migration"], commands, self.LIMITS)
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assert_skipped_with_warning("refactor-migration", "K12", log)
        self.assertIn("K10 mutation score", self.step_names())

    def test_ac4_todo_command_skips_the_step_and_warns(self) -> None:
        for key, check in (("mutation", "K10"), ("differential", "K12"),
                           ("architecture", "K8")):
            with self.subTest(check=check):
                self.tearDown()
                self.setUp()
                self.configure(["refactor-migration"],
                               {**CHECK_COMMANDS, key: "TODO(octocat)"}, self.LIMITS)
                result, log = self.render()
                self.assertEqual(result.exit_code, 0)
                self.assert_skipped_with_warning("refactor-migration", check, log)
                self.assertNotIn("TODO(", self.read(WORKFLOW))

    def test_ac4_command_with_no_value_skips_the_step_and_warns(self) -> None:
        # customization.md: "If a profile lists the check and the command has no value,
        # stone render skips the step and writes a warning."
        for value in (None, ""):
            with self.subTest(value=value):
                self.tearDown()
                self.setUp()
                self.configure(["refactor-migration"],
                               {**CHECK_COMMANDS, "differential": value}, self.LIMITS)
                result, log = self.render()
                self.assertEqual(result.exit_code, 0)
                runs = [step.get("run") for step in self.steps()
                        if step.get("name") == "K12 differential tests"]
                self.assertEqual(runs, [], f"the K12 step runs {runs!r}")
                self.assert_skipped_with_warning("refactor-migration", "K12", log)

    def test_ac4_each_missing_check_has_its_own_warning(self) -> None:
        self.configure(["refactor-migration"], {}, self.LIMITS)
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.optional_steps(), [])
        self.assertEqual(len(self.warnings(log)), 3, log)
        for check in ("K8", "K10", "K12"):
            with self.subTest(check=check):
                self.assert_skipped_with_warning("refactor-migration", check, log)

    def test_ac4_two_profiles_that_list_the_check_give_one_warning(self) -> None:
        # app-slice and refactor-migration both list K8 and K10.
        self.configure(["refactor-migration", "app-slice"], {}, self.LIMITS)
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        for check in ("K8", "K10"):
            with self.subTest(check=check):
                lines = [line for line in self.warnings(log) if check in line]
                self.assertEqual(len(lines), 1, log)
                self.assertTrue("refactor-migration" in lines[0] or "app-slice" in lines[0],
                                lines[0])

    def test_ac4_warning_goes_to_stderr_and_the_cli_exits_0(self) -> None:
        self.configure(["refactor-migration"], {}, self.LIMITS)
        code, out, err = self.cli_render()
        self.assertEqual(code, 0, out)
        self.assertNotIn("warning:", out)
        lines = [line for line in self.warnings(err) if "K10" in line]
        self.assertEqual(len(lines), 1, err)
        self.assertIn("commands.mutation", lines[0])
        self.assertTrue((self.root / WORKFLOW).exists())

    def test_ac4_missing_mutation_command_does_not_need_the_limit(self) -> None:
        # The K10 step is not rendered, so render does not need its limit.
        self.configure(["refactor-migration"], {"differential": "pytest tests/differential"})
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assert_skipped_with_warning("refactor-migration", "K10", log)
        self.assertIn("K12 differential tests", self.step_names())


# AC5: no selected profile lists the check.

class NotListedTest(StepsBase):
    def test_ac5_single_ticket_with_all_commands_has_no_step_and_no_warning(self) -> None:
        self.configure(["single-ticket"], CHECK_COMMANDS)
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.optional_steps(), [])
        self.assertEqual(self.warnings(log), [])

    def test_ac5_unlisted_mutation_command_does_not_need_the_limit(self) -> None:
        self.configure(["single-ticket"], {"mutation": "mutmut run"})
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("K10 mutation score", self.step_names())
        self.assertNotIn(LIMIT, log)

    def test_ac5_commands_do_not_change_the_workflow_of_single_ticket(self) -> None:
        self.configure(["single-ticket"])
        self.render()
        without = self.read(WORKFLOW)
        self.tearDown()
        self.setUp()
        self.configure(["single-ticket"], CHECK_COMMANDS, {"mutation_score_changed_code": 0.6})
        self.render()
        self.assertEqual(self.read(WORKFLOW), without)

    def test_ac5_debugging_does_not_get_k8_or_k10(self) -> None:
        self.configure(["debugging"], CHECK_COMMANDS, {"mutation_score_changed_code": 0.6})
        _, log = self.render()
        self.assertNotIn("K8 architecture fitness", self.step_names())
        self.assertNotIn("K10 mutation score", self.step_names())
        self.assertEqual(self.warnings(log), [])

    def test_ac5_report_profile_with_all_commands_has_no_workflow_and_no_warning(self) -> None:
        # code-audit reads K8 and K10 results, but its checks list has neither and it has no G3.
        self.configure(["code-audit"], CHECK_COMMANDS)
        result, log = self.render()
        self.assertEqual(result.exit_code, 0)
        self.assertFalse((self.root / WORKFLOW).exists())
        self.assertEqual(self.warnings(log), [])


# AC6: with no optional step, the workflow is the same as before this change.

class NoStepOutputTest(FrameworkCopy):
    def old_workflow(self, profiles: list[str], commands: dict[str, Any] | None = None,
                     limits: dict[str, Any] | None = None) -> str:
        """Render with the template from before this change: no `$check_steps` line."""
        root = Path(self.folder.name) / "old-repo"
        (root / ".cornerstone").mkdir(parents=True)
        (root / ".cornerstone" / "config.yaml").write_text(
            config_text(profiles, commands, limits), encoding="utf-8")
        template = self.framework / TEMPLATE
        text = template.read_text(encoding="utf-8")
        self.assertEqual(text.count("$check_steps\n"), 1)
        template.write_text(text.replace("$check_steps\n", ""), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(root, self.framework, today=TODAY)
        return (root / WORKFLOW).read_text(encoding="utf-8")

    def new_workflow(self, profiles: list[str], commands: dict[str, Any] | None = None,
                     limits: dict[str, Any] | None = None) -> str:
        self.configure(profiles, commands, limits)
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            render.render(self.root, FRAMEWORK, today=TODAY)
        return self.read(WORKFLOW)

    def test_ac6_single_ticket_workflow_is_byte_identical_to_the_old_one(self) -> None:
        new = self.new_workflow(["single-ticket"])
        self.assertEqual(new, self.old_workflow(["single-ticket"]))

    def test_ac6_listed_checks_with_no_commands_give_the_old_workflow(self) -> None:
        new = self.new_workflow(["refactor-migration"])
        self.assertEqual(new, self.old_workflow(["refactor-migration"]))

    def test_ac6_workflow_ends_with_all_checks_and_one_newline(self) -> None:
        new = self.new_workflow(["single-ticket"], CHECK_COMMANDS)
        self.assertTrue(new.endswith("      - name: All checks\n        run: make check\n"),
                        repr(new[-80:]))
        self.assertFalse(new.endswith("\n\n"))
        self.assertNotIn("$", new.replace("${{", "").replace("${", ""))
        self.assertNotIn("check_steps", new)

    def test_ac6_all_checks_is_the_last_step(self) -> None:
        self.new_workflow(["single-ticket"])
        self.assertEqual(self.step_names()[-1], "All checks")


# K23 renders only from framework 1.5.0, the first tag with `stone check-dependencies` (D90).

class K23GateTest(FrameworkCopy):
    STEP = "K23 new dependencies"

    def names_with(self, version: str, profiles: list[str] | None = None,
                   commands: dict[str, Any] | None = None) -> list[str]:
        self.configure(profiles or ["single-ticket"], commands)
        path = self.root / ".cornerstone" / "config.yaml"
        path.write_text(path.read_text(encoding="utf-8").replace(
            'framework_version: 0.8.0', f'framework_version: "{version}"').replace(
            'framework_version: "0.8.0"', f'framework_version: "{version}"'), encoding="utf-8")
        self.assertIn(f'"{version}"', path.read_text(encoding="utf-8"))
        self.render()
        return self.step_names()

    def test_k23_step_renders_from_1_5_0(self) -> None:
        for version in ("1.5.0", "1.10.0", "2.0.0"):
            with self.subTest(version=version):
                self.assertEqual(self.names_with(version)[-2:], [self.STEP, K24_STEP])
                step = self.step(self.STEP)
                self.assertIn("check-dependencies", step["run"])
                self.assertIn("--mode warn", step["run"])

    def test_k23_step_does_not_render_below_1_5_0_or_for_a_bad_version(self) -> None:
        for version in ("1.4.0", "1.4.99", "0.8.0", "banana", "1.x"):
            with self.subTest(version=version):
                self.assertNotIn(self.STEP, self.names_with(version))

    def test_k23_step_follows_all_checks_with_every_check_profile(self) -> None:
        self.add_profile("with-k23", ["K4", "K5", "K6", "K14", "K23"])
        names = self.names_with("1.5.0", ["with-k23"], CHECK_COMMANDS)
        self.assertLess(names.index("All checks"), names.index(self.STEP))
        self.assertLess(names.index(self.STEP), names.index("K4 integration tests"))

    def test_framework_at_least(self) -> None:
        since = render.K23_SINCE
        self.assertEqual(since, (1, 5, 0))
        for version, expected in (("1.5.0", True), ("1.10.0", True), ("2.0.0", True),
                                  ("1.4.0", False), ("0.8.0", False), ("banana", False),
                                  ("", False), (None, False), ("1.5", False)):
            with self.subTest(version=version):
                self.assertIs(render.framework_at_least(version, since), expected)


# K24 renders only from framework 1.5.0, the first tag with `stone check-workflows` (D93).

class K24GateTest(FrameworkCopy):
    names_with = K23GateTest.names_with

    def test_k24_step_renders_from_1_5_0_with_the_command(self) -> None:
        self.add_profile("with-k24", ["K4", "K5", "K6", "K14", "K24"])
        for version in ("1.5.0", "1.10.0", "2.0.0"):
            with self.subTest(version=version):
                self.assertIn(K24_STEP, self.names_with(version, ["with-k24"]))
                run = self.step(K24_STEP)["run"]
                self.assertIn('check-workflows - --base "origin/${BASE_REF}" --mode warn '
                              '--format github', " ".join(run.replace("\\\n", " ").split()))

    def test_k24_step_does_not_render_below_1_5_0_or_for_a_bad_version(self) -> None:
        self.add_profile("with-k24", ["K4", "K5", "K6", "K14", "K24"])
        for version in ("1.4.0", "1.4.99", "0.8.0", "banana", "1.x"):
            with self.subTest(version=version):
                self.assertNotIn(K24_STEP, self.names_with(version, ["with-k24"]))

    def test_k24_step_does_not_render_for_a_profile_without_k24(self) -> None:
        self.add_profile("no-k24", ["K4", "K5", "K6", "K14", "K23"])
        self.assertNotIn(K24_STEP, self.names_with("1.5.0", ["no-k24"]))

    def test_k24_is_not_in_the_checks_of_bug_triage_or_spike(self) -> None:
        for name in ("bug-triage", "spike"):
            text = (FRAMEWORK / "profiles" / f"{name}.md").read_text(encoding="utf-8")
            self.assertNotIn("K24", re.search(r"^checks: .*$", text, flags=re.M).group(0))

    def test_k24_gate_version_is_1_5_0(self) -> None:
        self.assertEqual(render.K24_SINCE, (1, 5, 0))

    def test_k24_is_in_the_checks_of_each_profile_that_has_k23(self) -> None:
        for path in sorted((FRAMEWORK / "profiles").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            match = re.search(r"^checks: \[(.*)\]", text, flags=re.M)
            if match and "K23" in match.group(1):
                with self.subTest(profile=path.name):
                    self.assertIn("K24", match.group(1))


# AC7: valid YAML, the order of components.yaml, and warn mode.

class AllStepsTest(FrameworkCopy):
    def setUp(self) -> None:
        super().setUp()
        self.add_profile("every-check",
                         ["K4", "K5", "K6", "K8", "K10", "K11", "K12", "K14", "K20", "K23", "K24"])
        self.configure(["every-check"], CHECK_COMMANDS, {"mutation_score_changed_code": 0.6})
        config = self.root / ".cornerstone" / "config.yaml"  # K23 needs framework 1.5.0 (D90)
        config.write_text(config.read_text(encoding="utf-8").replace("0.8.0", "1.5.0"),
                          encoding="utf-8")
        with (self.root / ".cornerstone" / "config.yaml").open("a", encoding="utf-8") as config:
            config.write("specialists:\n  - id: security\n    run: /security-review\n")
        self.result, self.log = self.render()

    def test_ac7_render_exits_0_with_no_warning(self) -> None:
        self.assertEqual(self.result.exit_code, 0)
        self.assertEqual(self.warnings(self.log), [])

    def test_ac7_workflow_is_valid_yaml(self) -> None:
        data = yaml.safe_load(self.read(WORKFLOW))
        self.assertIsInstance(data["jobs"]["checks"]["steps"], list)
        for step in data["jobs"]["checks"]["steps"]:
            self.assertIsInstance(step, dict)

    def test_ac7_steps_have_the_order_of_components_yaml(self) -> None:
        names = [name for name in self.step_names() if name in STEP_NAMES | {K23_STEP, K24_STEP}]
        self.assertEqual(names, registry_step_names())

    def test_ac7_k20_is_the_first_optional_step(self) -> None:
        names = self.step_names()
        self.assertEqual(names[names.index("All checks") + 1], K20_STEP)

    def test_ac7_k10_is_the_last_step(self) -> None:
        self.assertEqual(self.step_names()[-1], "K10 mutation score")

    def test_ac7_optional_steps_come_after_all_checks(self) -> None:
        names = self.step_names()
        after = names[names.index("All checks") + 1:]
        self.assertEqual(after, registry_step_names())

    def test_ac7_no_optional_step_has_continue_on_error(self) -> None:
        for name in self.optional_steps():
            with self.subTest(step=name):
                self.assertNotIn("continue-on-error", self.step(name))

    def test_ac7_each_optional_step_runs_its_command(self) -> None:
        for name, key in STEPS.values():
            with self.subTest(step=name):
                self.assertEqual(self.step(name)["run"], CHECK_COMMANDS[key])

    def test_ac7_the_steps_before_all_checks_do_not_change(self) -> None:
        names = self.step_names()
        before = names[:names.index("All checks") + 1]
        self.tearDown()
        self.setUp()
        self.configure(["single-ticket"])
        self.render()
        self.assertEqual(before, self.step_names())

    def test_ac7_workflow_has_no_placeholder_left(self) -> None:
        text = self.read(WORKFLOW)
        self.assertNotIn("check_steps", text)
        self.assertNotIn("$step_", text)
        self.assertNotIn("$limit_", text)
        self.assertFalse(text.endswith("\n\n"))


class EachProfileYamlTest(StepsBase):
    def test_ac7_each_profile_with_all_commands_renders_valid_yaml(self) -> None:
        names = sorted(p.stem for p in (FRAMEWORK / "profiles").glob("*.md")
                       if p.stem not in {"README", "_template"})
        for name in names:
            with self.subTest(profile=name):
                self.tearDown()
                self.setUp()
                self.configure([name], CHECK_COMMANDS, {"mutation_score_changed_code": 0.6})
                result, _ = self.render()
                self.assertEqual(result.exit_code, 0)
                if (self.root / WORKFLOW).exists():
                    names_in_order = [n for n in registry_step_names()
                                      if n in self.optional_steps()]
                    self.assertEqual(self.optional_steps(), names_in_order)
                    for step in self.optional_steps():
                        self.assertNotIn("continue-on-error", self.step(step))


# AC8: the K10 step needs limits.mutation_score_changed_code.

class MissingLimitTest(StepsBase):
    def test_ac8_render_raises_and_names_the_limit(self) -> None:
        self.configure(["refactor-migration"], CHECK_COMMANDS)
        with self.assertRaisesRegex(render.RenderError, re.escape(LIMIT)):
            self.render()

    def test_ac8_cli_exits_1_and_names_the_limit(self) -> None:
        self.configure(["refactor-migration"], CHECK_COMMANDS)
        code, out, _ = self.cli_render()
        self.assertEqual(code, 1)
        self.assertIn(LIMIT, out)

    def test_ac8_render_writes_nothing(self) -> None:
        self.configure(["refactor-migration"], CHECK_COMMANDS)
        self.cli_render()
        self.assertEqual(self.written_files(), [])

    def test_ac8_limits_with_other_keys_only_still_fails(self) -> None:
        self.configure(["refactor-migration"], CHECK_COMMANDS, {"pr_changed_lines": 600})
        code, out, _ = self.cli_render()
        self.assertEqual(code, 1)
        self.assertIn(LIMIT, out)
        self.assertEqual(self.written_files(), [])

    def test_ac8_todo_limit_fails(self) -> None:
        self.configure(["refactor-migration"], CHECK_COMMANDS,
                       {"mutation_score_changed_code": "TODO(octocat)"})
        code, out, _ = self.cli_render()
        self.assertEqual(code, 1)
        self.assertIn(LIMIT, out)
        self.assertEqual(self.written_files(), [])

    def test_ac8_failed_render_does_not_change_the_files_of_an_earlier_render(self) -> None:
        self.configure(["refactor-migration"], CHECK_COMMANDS,
                       {"mutation_score_changed_code": 0.6})
        self.render()
        before = {path: self.read(path) for path in self.written_files()}
        self.configure(["refactor-migration"], CHECK_COMMANDS)
        code, out, _ = self.cli_render()
        self.assertEqual(code, 1)
        self.assertIn(LIMIT, out)
        self.assertEqual({path: self.read(path) for path in self.written_files()}, before)


# AC11: a blank limit is the same as no limit. The K10 step needs a value.

BLANK_LIMITS = {"null": None, "empty string": "", "spaces": "  "}


class BlankLimitTest(StepsBase):
    def configure_blank(self, value: Any, profiles: list[str] | None = None,
                        commands: dict[str, Any] | None = None) -> None:
        self.configure(profiles or ["refactor-migration"],
                       CHECK_COMMANDS if commands is None else commands,
                       {"mutation_score_changed_code": value})

    def test_ac11_blank_limit_cli_exits_1_writes_nothing_and_names_the_limit(self) -> None:
        for label, value in BLANK_LIMITS.items():
            with self.subTest(limit=label):
                self.tearDown()
                self.setUp()
                self.configure_blank(value)
                code, out, _ = self.cli_render()
                self.assertEqual(code, 1, out)
                self.assertIn(LIMIT, out)
                self.assertEqual(self.written_files(), [])

    def test_ac11_blank_limit_render_raises_and_names_the_limit(self) -> None:
        for label, value in BLANK_LIMITS.items():
            with self.subTest(limit=label):
                self.configure_blank(value)
                with self.assertRaisesRegex(render.RenderError, re.escape(LIMIT)):
                    self.render()

    def test_ac11_key_with_no_value_in_the_config_text_fails(self) -> None:
        # The way a person writes it: the key is there, the value is not.
        text = config_text(["refactor-migration"], CHECK_COMMANDS)
        text += "limits:\n  mutation_score_changed_code:\n"
        (self.root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")
        code, out, _ = self.cli_render()
        self.assertEqual(code, 1, out)
        self.assertIn(LIMIT, out)
        self.assertEqual(self.written_files(), [])

    def test_ac11_blank_limit_does_not_write_an_empty_mutation_score_min(self) -> None:
        self.configure_blank("")
        self.cli_render()
        self.assertFalse((self.root / WORKFLOW).exists())

    def test_ac11_blank_limit_does_not_change_the_files_of_an_earlier_render(self) -> None:
        self.configure(["refactor-migration"], CHECK_COMMANDS,
                       {"mutation_score_changed_code": 0.6})
        self.render()
        before = {path: self.read(path) for path in self.written_files()}
        for label, value in BLANK_LIMITS.items():
            with self.subTest(limit=label):
                self.configure_blank(value)
                code, out, _ = self.cli_render()
                self.assertEqual(code, 1, out)
                self.assertIn(LIMIT, out)
                self.assertEqual({path: self.read(path) for path in self.written_files()},
                                 before)

    def test_ac11_blank_limit_without_the_mutation_command_renders(self) -> None:
        # No K10 step, so render does not need the limit.
        commands = {k: v for k, v in CHECK_COMMANDS.items() if k != "mutation"}
        for label, value in BLANK_LIMITS.items():
            with self.subTest(limit=label):
                self.tearDown()
                self.setUp()
                self.configure_blank(value, commands=commands)
                result, log = self.render()
                self.assertEqual(result.exit_code, 0)
                self.assertNotIn("K10 mutation score", self.step_names())
                self.assertNotIn(LIMIT, log)

    def test_ac11_blank_limit_with_a_profile_without_k10_renders(self) -> None:
        for label, value in BLANK_LIMITS.items():
            with self.subTest(limit=label):
                self.tearDown()
                self.setUp()
                self.configure_blank(value, profiles=["single-ticket"])
                result, _ = self.render()
                self.assertEqual(result.exit_code, 0)
                self.assertNotIn("K10 mutation score", self.step_names())


# AC9: a second render with the same inputs writes nothing.

class IdempotentTest(StepsBase):
    def assert_second_render_writes_nothing(self) -> None:
        self.render()
        before = {path: self.read(path) for path in self.written_files()}
        result, _ = self.render(today=TODAY + dt.timedelta(days=30))
        self.assertEqual(result.wrote, [])
        self.assertEqual(result.drift, [])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual({path: self.read(path) for path in self.written_files()}, before)

    def test_ac9_second_render_with_steps_writes_nothing(self) -> None:
        self.configure(["refactor-migration"], CHECK_COMMANDS,
                       {"mutation_score_changed_code": 0.6})
        self.assert_second_render_writes_nothing()

    def test_ac9_second_render_with_a_skipped_step_writes_nothing(self) -> None:
        self.configure(["refactor-migration"], {"differential": "pytest tests/differential"})
        self.assert_second_render_writes_nothing()

    def test_ac9_second_render_from_the_cli_reports_0_written(self) -> None:
        self.configure(["refactor-migration", "app-slice", "dependency-upgrade"],
                       CHECK_COMMANDS, {"mutation_score_changed_code": 0.6})
        self.render()
        code, out, _ = self.cli_render()
        self.assertEqual(code, 0)
        self.assertIn("0 written", out)

    def test_ac9_a_new_command_updates_the_workflow_with_no_drift(self) -> None:
        # The warning tells the user: "Add the command and render again."
        self.configure(["refactor-migration"], {"differential": "pytest tests/differential"})
        self.render()
        self.configure(["refactor-migration"], CHECK_COMMANDS,
                       {"mutation_score_changed_code": 0.6})
        result, log = self.render()
        self.assertEqual(result.drift, [])
        self.assertIn(WORKFLOW, result.wrote)
        self.assertIn("K10 mutation score", self.step_names())
        self.assertEqual(self.warnings(log), [])


if __name__ == "__main__":
    unittest.main()
