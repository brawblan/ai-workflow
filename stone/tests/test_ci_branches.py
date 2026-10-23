"""Issue #164: ci.branches limits the K6, K7, and K14 steps to PRs into the listed base branches."""

import contextlib
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import framework_check, render
from test_render import CONFIG, FRAMEWORK

WORKFLOW = ".github/workflows/cornerstone-checks.yml"
GATES = ("K6 protected paths", "K7 change size", "K14 PR evidence")
UNGATED = ("All checks", "Install", "Install stone")
MARKER = "steps.marker.outputs.cornerstone == 'true'"


class CiBranchesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def render(self, extra: str = "") -> str:
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG + extra, encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK, today=dt.date(2026, 10, 17))
        return (self.root / WORKFLOW).read_text(encoding="utf-8")

    def steps(self, text: str) -> dict[str, dict]:
        steps = yaml.safe_load(text)["jobs"]["checks"]["steps"]
        return {s["name"]: s for s in steps if "name" in s}

    def test_dev_only_gates_the_three_steps(self) -> None:
        steps = self.steps(self.render("ci:\n  branches: [dev]\n"))
        for name in GATES:
            self.assertEqual(steps[name].get("if"), "github.base_ref == 'dev'", name)

    def test_other_steps_and_trigger_are_not_filtered(self) -> None:
        text = self.render("ci:\n  branches: [dev]\n")
        steps = self.steps(text)
        for name in UNGATED:
            self.assertIn(name, steps)
            self.assertNotIn("if", steps[name], name)
        trigger = yaml.safe_load(text)
        trigger = trigger.get("on", trigger.get(True))
        self.assertNotIn("branches", trigger["pull_request"] or {})

    def test_no_ci_key_is_unchanged(self) -> None:
        plain = self.render()
        self.assertNotIn("github.base_ref ==", plain)
        for name in GATES:
            self.assertNotIn("if", self.steps(plain)[name])
        self.assertEqual(self.render("ci: {}\n"), plain)
        self.assertEqual(self.render("ci:\n  branches: null\n"), plain)
        self.assertNotIn("\n\n\n", plain)

    def test_two_branches_are_joined_with_or(self) -> None:
        steps = self.steps(self.render("ci:\n  branches: [dev, release]\n"))
        for name in GATES:
            self.assertEqual(steps[name]["if"],
                             "github.base_ref == 'dev' || github.base_ref == 'release'")

    def test_single_quote_is_doubled(self) -> None:
        steps = self.steps(self.render("ci:\n  branches: [dev, \"it's\"]\n"))
        self.assertEqual(steps["K6 protected paths"]["if"],
                         "github.base_ref == 'dev' || github.base_ref == 'it''s'")

    def test_opt_in_combines_marker_and_branches(self) -> None:
        steps = self.steps(self.render("adoption: opt-in\nci:\n  branches: [dev, hotfix]\n"))
        for name in GATES:
            self.assertEqual(
                steps[name]["if"],
                f"{MARKER} && (github.base_ref == 'dev' || github.base_ref == 'hotfix')", name)
        self.assertEqual(steps["All checks"]["if"], MARKER)

    def test_opt_in_with_one_branch_has_no_parentheses(self) -> None:
        steps = self.steps(self.render("adoption: opt-in\nci:\n  branches: [dev]\n"))
        for name in GATES:
            self.assertEqual(steps[name]["if"], f"{MARKER} && github.base_ref == 'dev'", name)


class CiBranchProblemsTest(unittest.TestCase):
    def config(self, ci) -> dict:
        config = yaml.safe_load(CONFIG)
        if ci is not None:
            config["ci"] = ci
        return config

    def test_valid_and_absent_have_no_problem(self) -> None:
        self.assertEqual(framework_check.ci_branch_problems(self.config({"branches": ["dev"]})), [])
        self.assertEqual(framework_check.ci_branch_problems(self.config({"branches": ["dev", "x"]})), [])
        self.assertEqual(framework_check.ci_branch_problems(self.config(None)), [])

    def test_invalid_lists_are_problems(self) -> None:
        for value in (["main"], [], "dev", ["dev", 3], ["dev", ""]):
            with self.subTest(value=value):
                self.assertTrue(framework_check.ci_branch_problems(
                    self.config({"branches": value})))

    def test_render_rejects_list_without_integration(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".cornerstone").mkdir()
            (root / ".cornerstone" / "config.yaml").write_text(
                CONFIG + "ci:\n  branches: [main]\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(render.RenderError):
                render.render(root, FRAMEWORK, today=dt.date(2026, 10, 17))

    def test_check_config_reports_missing_integration(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".cornerstone").mkdir()
            (root / ".cornerstone" / "config.yaml").write_text(
                CONFIG + "ci:\n  branches: [main]\n", encoding="utf-8")
            findings = framework_check.check_config(root, FRAMEWORK)
            self.assertTrue([f for f in findings if "ci.branches" in str(f)], findings)
            (root / ".cornerstone" / "config.yaml").write_text(
                CONFIG + "ci:\n  branches: [dev]\n", encoding="utf-8")
            findings = framework_check.check_config(root, FRAMEWORK)
            self.assertFalse([f for f in findings if "ci.branches" in str(f)], findings)


if __name__ == "__main__":
    unittest.main()
