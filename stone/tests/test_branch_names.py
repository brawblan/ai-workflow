"""Tests for D34: a branches.* value in the config must be a YAML string.

YAML reads an unquoted 1.10 as a float, yes as a bool, and 42 as an int. `stone render` must
raise a RenderError and `stone check` must report a Finding. Each names the key and says to quote it.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import cli, framework_check, render

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
TODAY = dt.date(2026, 10, 18)
CONFIG = """framework_version: 0.8.0
harness: claude-code
model_profile: claude-5
profiles: [single-ticket, spike]
branches: {integration: INTEGRATION, main: MAIN}
commands: {install: pip install ., test_unit: python -m unittest, all_checks: make check}
paths: {tests: [tests/], checks: [.github/workflows/, .cornerstone/checks/], plans: docs/plans/}
owners: {default: octocat}
"""
K16 = ".github/workflows/cornerstone-k16.yml"
NOT_STRINGS = {"float 1.10": "1.10", "bool yes": "yes", "bool no": "no", "int 42": "42"}
STRINGS = {'"1.10"': ("1.10", '"1.10"'), "'yes'": ("yes", "'yes'"), "trunk": ("trunk", "trunk")}
BLANK = {"null": "null", "~": "~", "empty string": '""'}


class BranchNameTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def configure(self, main: str = "main", integration: str = "dev") -> None:
        text = CONFIG.replace("INTEGRATION", integration).replace("MAIN", main)
        (self.root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")

    def render_error(self) -> str:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(render.RenderError) as caught:
                render.render(self.root, FRAMEWORK, today=TODAY)
        return str(caught.exception)

    def branch_findings(self) -> list[str]:
        return [f.message for f in framework_check.check_config(self.root, FRAMEWORK)
                if "branches." in f.message]

    def test_render_raises_for_a_main_value_that_is_not_a_string(self) -> None:
        for label, value in NOT_STRINGS.items():
            with self.subTest(case=label):
                self.configure(main=value)
                message = self.render_error()
                self.assertIn("branches.main", message)
                self.assertIn("quote", message.lower())
                self.assertFalse((self.root / ".claude").exists())
                self.assertFalse((self.root / K16).exists())

    def test_render_names_the_integration_key(self) -> None:
        self.configure(integration="1.10")
        message = self.render_error()
        self.assertIn("branches.integration", message)
        self.assertIn("quote", message.lower())

    def test_cli_render_exits_1_and_names_the_key(self) -> None:
        self.configure(main="yes")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["render", "--root", str(self.root), "--framework", str(FRAMEWORK)])
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("branches.main", out.getvalue())

    def test_quoted_and_plain_strings_render_the_exact_name(self) -> None:
        for label, (name, value) in STRINGS.items():
            with self.subTest(case=label):
                self.configure(main=value)
                with contextlib.redirect_stderr(io.StringIO()):
                    result = render.render(self.root, FRAMEWORK, today=TODAY)
                self.assertEqual(result.exit_code, 0)
                workflow = yaml.safe_load((self.root / K16).read_text(encoding="utf-8"))
                env = [s["env"] for j in workflow["jobs"].values() for s in j["steps"] if "run" in s]
                self.assertEqual(env[0]["MAIN_BRANCH"], name)

    def test_blank_main_keeps_the_old_error_and_not_the_quote_error(self) -> None:
        for label, value in BLANK.items():
            with self.subTest(case=label):
                self.configure(main=value)
                message = self.render_error()
                self.assertIn("branches.main", message)
                self.assertNotIn("not a YAML string", message)

    def test_check_reports_a_finding_for_each_value_that_is_not_a_string(self) -> None:
        for label, value in NOT_STRINGS.items():
            with self.subTest(case=label):
                self.configure(main=value)
                findings = self.branch_findings()
                self.assertEqual(len(findings), 1, findings)
                self.assertIn("branches.main", findings[0])
                self.assertIn("quote", findings[0].lower())
        self.configure(main="42", integration="1.10")
        findings = " ".join(self.branch_findings())
        self.assertIn("branches.main", findings)
        self.assertIn("branches.integration", findings)

    def test_check_reports_nothing_for_strings_and_blank_values(self) -> None:
        cases = {**{k: v for k, (_, v) in STRINGS.items()}, **BLANK}
        for label, value in cases.items():
            with self.subTest(case=label):
                self.configure(main=value)
                self.assertEqual(self.branch_findings(), [])


if __name__ == "__main__":
    unittest.main()
