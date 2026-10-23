"""Tests for `ci.env` and `ci.secrets` (#163): the env of the All checks step."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import ci_setup, framework_check, render

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
TODAY = dt.date(2026, 10, 17)
CONFIG = """framework_version: 0.1.0
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
WORKFLOW = ".github/workflows/cornerstone-checks.yml"


def step(text: str, name: str) -> dict:
    data = yaml.safe_load(text)
    for job in data["jobs"].values():
        for item in job.get("steps", []):
            if item.get("name") == name:
                return item
    raise AssertionError(f"no step {name}")


class CiEnvRenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def workflow(self, extra: str = "") -> str:
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG + extra, encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK, today=TODAY)
        return (self.root / WORKFLOW).read_text(encoding="utf-8")

    def test_env_value_is_on_all_checks_step(self) -> None:
        text = self.workflow("ci:\n  env: {NAME: value}\n")
        self.assertIn('        env:\n          NAME: "value"\n', text)
        self.assertEqual(step(text, "All checks")["env"], {"NAME": "value"})

    def test_secret_is_passed_by_name(self) -> None:
        text = self.workflow("ci:\n  secrets: [STRIPE_SECRET_KEY]\n")
        self.assertIn("STRIPE_SECRET_KEY: ${{ secrets.STRIPE_SECRET_KEY }}", text)
        self.assertEqual(step(text, "All checks")["env"],
                         {"STRIPE_SECRET_KEY": "${{ secrets.STRIPE_SECRET_KEY }}"})

    def test_env_and_secrets_together(self) -> None:
        text = self.workflow("ci:\n  env: {MODE: test}\n  secrets: [TOKEN_A]\n")
        self.assertEqual(step(text, "All checks")["env"],
                         {"MODE": "test", "TOKEN_A": "${{ secrets.TOKEN_A }}"})

    def test_value_with_special_characters_stays_a_string(self) -> None:
        text = self.workflow('ci:\n  env: {FLAG: "yes: \\"no\\" #x", NUM: 1}\n')
        self.assertEqual(step(text, "All checks")["env"], {"FLAG": 'yes: "no" #x', "NUM": "1"})

    def test_only_all_checks_step_gets_env(self) -> None:
        text = self.workflow("ci:\n  env: {NAME: value}\n  secrets: [TOKEN_A]\n")
        for name in ("K7 change size", "Install stone", "K14 PR evidence", "Install"):
            env = step(text, name).get("env") or {}
            self.assertNotIn("NAME", env, name)
            self.assertNotIn("TOKEN_A", env, name)
        self.assertIn("env", step(text, "All checks"))
        self.assertEqual(text.count("NAME:"), 1)
        self.assertEqual(text.count("TOKEN_A:"), 1)

    def test_without_keys_output_is_clean(self) -> None:
        plain = self.workflow()
        for extra in ("ci: {}\n", "ci:\n  env: {}\n  secrets: []\n"):
            with self.subTest(extra=extra):
                self.assertEqual(self.workflow(extra), plain)
        self.assertNotIn("$all_checks_env", plain)
        self.assertNotIn("env:", step_text(plain))
        self.assertNotIn("\n\n        run:", plain)
        self.assertNotIn("\n\n\n", plain)
        self.assertNotIn("env", step(plain, "All checks"))

    def test_rendered_yaml_parses(self) -> None:
        text = self.workflow("ci:\n  env: {A: b}\n  secrets: [S_1]\n")
        self.assertIsInstance(yaml.safe_load(text), dict)
        self.assertEqual(step(text, "All checks")["run"], "make check")

    def test_render_refuses_bad_ci(self) -> None:
        with self.assertRaises(render.RenderError):
            self.workflow("ci:\n  secrets: [bad-name]\n")


def step_text(text: str) -> str:
    """Return the lines from the All checks step to the end."""
    return text[text.index("- name: All checks"):].split("\n      - name:")[0]


class CiEnvProblemsTest(unittest.TestCase):
    def problems(self, ci: object) -> list[str]:
        return framework_check.ci_env_problems({"ci": ci})

    def test_no_section_or_valid_section_has_no_problem(self) -> None:
        self.assertEqual(framework_check.ci_env_problems({}), [])
        self.assertEqual(self.problems({"env": {"A_1": "x"}, "secrets": ["_B"]}), [])

    def test_bad_env_name(self) -> None:
        self.assertTrue(self.problems({"env": {"lower": "x"}}))
        self.assertTrue(self.problems({"env": {"1ABC": "x"}}))

    def test_bad_secret_name(self) -> None:
        self.assertTrue(self.problems({"secrets": ["has-dash"]}))

    def test_name_in_both_keys(self) -> None:
        found = self.problems({"env": {"TOKEN": "x"}, "secrets": ["TOKEN"]})
        self.assertTrue(any("TOKEN" in p and "ci.env" in p and "ci.secrets" in p for p in found))

    def test_env_value_with_expression(self) -> None:
        self.assertTrue(self.problems({"env": {"TOKEN": "${{ secrets.X }}"}}))

    def test_unknown_ci_key(self) -> None:
        # The section check lives in ci_setup.section_problems, not here.
        self.assertEqual(self.problems({"vars": {}}), [])
        self.assertTrue(any("'ci.vars' is not a key" in p for p in
                            ci_setup.section_problems({"ci": {"vars": {}}})))

    def test_wrong_types(self) -> None:
        self.assertEqual(self.problems(["a"]), [])
        self.assertTrue(any("'ci' must be a map" in p for p in
                            ci_setup.section_problems({"ci": ["a"]})))
        self.assertTrue(self.problems({"env": ["A"]}))
        self.assertTrue(self.problems({"secrets": {"A": "b"}}))


class CiEnvCheckTest(unittest.TestCase):
    def test_stone_check_config_reports_problem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".cornerstone").mkdir()
            (root / ".cornerstone" / "config.yaml").write_text(
                CONFIG + "ci:\n  env: {bad: x}\n", encoding="utf-8")
            found = framework_check.check_config(root, FRAMEWORK)
            self.assertTrue(any("ci.env" in str(f) for f in found))


if __name__ == "__main__":
    unittest.main()
