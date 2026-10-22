"""Issue #139 (D66): check K20, `stone check-specialists`, and its render and gate steps."""

import contextlib
import datetime as dt
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from stone import cli, gate, render, specialists
from test_render import CONFIG, FRAMEWORK

SPECS = """specialists:
  - id: security
    run: /security-review
    when:
      paths: ["src/**"]
    blocks: true
  - id: docs
    run: /docs-review
    when:
      labels: [docs]
    blocks: false
"""
STEP = "K20 specialist findings"
WAIVER_TEXT = "## Waiver (K20)\nThe owner accepts this at G4.\n"


class K20Base(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()
        self.write_config(CONFIG + SPECS)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "a@example.com")
        self.git("config", "user.name", "a")
        (self.root / "a.txt").write_text("a\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("update-ref", "refs/remotes/origin/dev", "HEAD")
        target = self.root / "src" / "x.py"
        target.parent.mkdir()
        target.write_text("x = 1\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def write_config(self, text: str) -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")

    @property
    def config(self) -> dict:
        return yaml.safe_load((self.root / ".cornerstone" / "config.yaml").read_text())

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def report(self, name: str, text: str, ticket: str = "139") -> Path:
        path = self.root / "docs" / "reports" / f"{ticket}.{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def check(self, body: str, labels: list[str] | None = None) -> list:
        return specialists.check(self.root, self.config, "origin/dev", body, labels or [])


class BodyFieldsTest(unittest.TestCase):
    def test_ticket_forms(self) -> None:
        self.assertEqual(specialists.body_fields("Ticket: 139\n")[0], "139")
        self.assertEqual(specialists.body_fields("Ticket: #139\n")[0], "139")
        self.assertEqual(specialists.body_fields("nothing here\n")[0], "")

    def test_ticket_with_slash_is_not_accepted(self) -> None:
        self.assertEqual(specialists.body_fields("Ticket: ../etc/passwd\n")[0], "")
        self.assertEqual(specialists.body_fields("Ticket: a/b\n")[0], "")

    def test_personas(self) -> None:
        self.assertEqual(specialists.body_fields("Personas: a, b\n")[1], ["a", "b"])
        self.assertEqual(specialists.body_fields("Personas: none\n")[1], [])
        self.assertEqual(specialists.body_fields("Ticket: 1\n")[1], [])


class CheckTest(K20Base):
    def test_no_match_gives_no_finding_even_without_ticket(self) -> None:
        self.git("reset", "-q", "--hard", "origin/dev")
        self.assertEqual(self.check("no ticket line\n"), [])

    def test_match_without_ticket_is_one_error(self) -> None:
        found = self.check("No ticket\n")
        self.assertEqual([f.severity for f in found], ["error"])
        self.assertIn("security", found[0].message)
        self.assertIn("Ticket: <id>", found[0].message)

    def test_missing_report_of_blocking_specialist_is_error(self) -> None:
        found = self.check("Ticket: 139\n")
        self.assertEqual([f.severity for f in found], ["error"])
        self.assertIn("security", found[0].message)

    def test_missing_report_of_non_blocking_specialist_is_warning(self) -> None:
        self.report("security", "Severity: low\n")
        found = self.check("Ticket: 139\n", ["docs"])
        self.assertEqual([f.severity for f in found], ["warning"])
        self.assertIn("docs", found[0].message)

    def test_high_finding_of_blocking_specialist(self) -> None:
        self.report("security", "# Review\n\nok\nSeverity: high\nmore\n")
        found = self.check("Ticket: 139\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, "error")
        self.assertEqual(found[0].path, "docs/reports/139.security.md")
        self.assertEqual(found[0].line, 4)

    def test_high_finding_of_non_blocking_specialist_is_no_error(self) -> None:
        self.report("security", "Severity: low\n")
        self.report("docs", "Severity: high\n")
        found = self.check("Ticket: 139\n", ["docs"])
        self.assertFalse([f for f in found if f.severity == "error"])

    def test_low_severity_gives_no_finding(self) -> None:
        self.report("security", "Severity: low\n")
        self.assertEqual(self.check("Ticket: 139\n"), [])

    def test_waiver_turns_error_into_warning(self) -> None:
        found = self.check("Ticket: 139\n\n" + WAIVER_TEXT)
        self.assertEqual([f.severity for f in found], ["warning"])
        self.assertTrue(found[0].message.startswith("Waived (K20):"), found[0].message)

    def test_waiver_waives_a_missing_ticket_error(self) -> None:
        found = self.check(WAIVER_TEXT)
        self.assertEqual([f.severity for f in found], ["warning"])
        self.assertTrue(found[0].message.startswith("Waived (K20):"))

    def test_waiver_keeps_an_existing_warning_text(self) -> None:
        self.report("security", "Severity: low\n")
        plain = self.check("Ticket: 139\n", ["docs"])
        waived = self.check("Ticket: 139\n\n" + WAIVER_TEXT, ["docs"])
        self.assertEqual([f.message for f in waived], [f.message for f in plain])
        self.assertEqual([f.severity for f in waived], ["warning"])

    def test_waiver_with_warning_and_error_changes_only_the_error(self) -> None:
        found = self.check("Ticket: 139\n\n" + WAIVER_TEXT, ["docs"])
        self.assertEqual([f.severity for f in found], ["warning", "warning"])
        self.assertEqual(sum(f.message.startswith("Waived (K20):") for f in found), 1)

    def test_empty_waivers_do_not_waive(self) -> None:
        for tail in ("## Waiver (K20)\nNone\n", "## Waiver (K20)\n", "## Waiver (K20)\n\n## Next\ntext\n",
                     "- Waiver (K20): ok\n"):
            with self.subTest(tail=tail):
                found = self.check("Ticket: 139\n\n" + tail)
                self.assertEqual([f.severity for f in found], ["error"])

    def test_waiver_heading_level_and_case(self) -> None:
        for heading in ("# Waiver (K20)", "### waiver (k20) for security", "#### WAIVER (K20)"):
            with self.subTest(heading=heading):
                found = self.check(f"Ticket: 139\n\n{heading}\nAccepted by the owner.\n")
                self.assertEqual([f.severity for f in found], ["warning"])

    def test_crlf_body(self) -> None:
        self.report("security", "Severity: low\n")
        self.assertEqual(self.check("Ticket: 139\r\nPersonas: none\r\n"), [])
        (self.root / "docs" / "reports" / "139.security.md").unlink()
        found = self.check("Ticket: 139\r\n\r\n## Waiver (K20)\r\nAccepted.\r\n")
        self.assertEqual([f.severity for f in found], ["warning"])

    def test_unknown_persona_is_one_error_and_does_not_raise(self) -> None:
        found = self.check("Ticket: 139\nPersonas: ghost\n")
        self.assertEqual([f.severity for f in found], ["error"])


class CliTest(K20Base):
    def run_cli(self, body: str, *args: str, stdin: bool = False) -> tuple[int, str]:
        out = io.StringIO()
        argv = ["check-specialists", "-" if stdin else str(self.root / "body.md"),
                "--root", str(self.root), "--base", "origin/dev", *args]
        if not stdin:
            (self.root / "body.md").write_text(body, encoding="utf-8")
        with contextlib.redirect_stdout(out), mock.patch.object(sys, "stdin", io.StringIO(body)):
            code = cli.main(argv)
        return code, out.getvalue()

    def test_warn_mode_exits_0_with_an_error(self) -> None:
        code, out = self.run_cli("Ticket: 139\n", "--mode", "warn")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "K20: 1 finding(s), mode warn.")

    def test_default_mode_is_warn(self) -> None:
        code, _ = self.run_cli("Ticket: 139\n")
        self.assertEqual(code, 0)

    def test_block_mode_exits_1_with_an_error(self) -> None:
        code, out = self.run_cli("Ticket: 139\n", "--mode", "block")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[-1], "K20: 1 finding(s), mode block.")

    def test_block_mode_exits_0_with_only_warnings(self) -> None:
        self.report("security", "Severity: low\n")
        code, out = self.run_cli("Ticket: 139\n", "--mode", "block", "--labels", "docs")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "K20: 1 finding(s), mode block.")

    def test_block_mode_with_a_waiver_exits_0(self) -> None:
        code, _ = self.run_cli("Ticket: 139\n\n" + WAIVER_TEXT, "--mode", "block")
        self.assertEqual(code, 0)

    def test_missing_config_exits_2(self) -> None:
        (self.root / ".cornerstone" / "config.yaml").unlink()
        code, _ = self.run_cli("Ticket: 139\n", "--mode", "block")
        self.assertEqual(code, 2)

    def test_reads_stdin(self) -> None:
        self.report("security", "Severity: low\n")
        code, out = self.run_cli("Ticket: 139\n", "--mode", "block", stdin=True)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "K20: 0 finding(s), mode block.")
        code, out = self.run_cli("no ticket\n", "--mode", "block", stdin=True)
        self.assertEqual(code, 1)

    def test_github_format(self) -> None:
        _, out = self.run_cli("Ticket: 139\n", "--format", "github", "--mode", "block")
        lines = [line for line in out.splitlines() if line.startswith("::")]
        self.assertTrue(lines, out)
        self.assertTrue(lines[0].startswith("::error"), lines[0])
        self.assertIn("title=K20::", lines[0])
        self.assertEqual(out.splitlines()[-1], "K20: 1 finding(s), mode block.")

    def test_old_specialists_command_still_exits_1_for_a_missing_non_blocking_report(self) -> None:
        self.report("security", "Severity: low\n", ticket="T1")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["specialists", "--root", str(self.root), "--base", "origin/dev",
                             "--ticket", "T1", "--labels", "docs"])
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("missing", out.getvalue().lower())


class RenderK20Test(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def render(self, extra: str) -> render.Result:
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG + extra, encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            return render.render(self.root, FRAMEWORK, today=dt.date(2026, 10, 17))

    def steps(self) -> list[dict]:
        text = (self.root / ".github/workflows/cornerstone-checks.yml").read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        return [step for job in data["jobs"].values() for step in job.get("steps", [])
                if step.get("name") == STEP]

    def test_step_is_rendered_with_specialists(self) -> None:
        self.render(SPECS)
        found = self.steps()
        self.assertEqual(len(found), 1)
        step = found[0]
        self.assertIn("check-specialists - ", step["run"])
        self.assertIn("--mode warn", step["run"])
        self.assertIn("PR_BODY", step["env"])
        self.assertIn("PR_LABELS", step["env"])

    def test_no_step_without_specialists(self) -> None:
        self.render("")
        self.assertEqual(self.steps(), [])

    def test_opt_in_step_has_the_marker_condition(self) -> None:
        self.render(SPECS + "adoption: opt-in\n")
        text = (self.root / ".github/workflows/cornerstone-checks.yml").read_text(encoding="utf-8")
        self.assertIn("if: steps.marker.outputs.cornerstone == 'true'", text)
        self.assertEqual(self.steps()[0].get("if"), "steps.marker.outputs.cornerstone == 'true'")

    def test_local_delivery_writes_no_workflow(self) -> None:
        result = self.render(SPECS + "delivery: local\n")
        self.assertFalse([p for p in result.wrote if p.startswith(".github/workflows/")])
        self.assertFalse((self.root / ".github").exists())


class GateK20Test(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def plan(self, extra: str, body: Path | None = None, labels: list[str] | None = None) -> list:
        text = CONFIG.replace("make check", "exit 0") + "delivery: local\n" + extra
        (self.root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK)
        config = gate.load_config(self.root)
        return gate.plan(self.root, config, "origin/dev", body, labels)

    def test_step_before_all_checks(self) -> None:
        names = [s.name for s in self.plan(SPECS)]
        self.assertIn(STEP, names)
        self.assertEqual(names.index(STEP) + 1, names.index("All checks"))

    def test_skipped_without_body(self) -> None:
        step = next(s for s in self.plan(SPECS) if s.name == STEP)
        self.assertEqual(step.skipped, "no --body")

    def test_command_with_body(self) -> None:
        body = self.root / "body.md"
        body.write_text("Ticket: 139\n", encoding="utf-8")
        step = next(s for s in self.plan(SPECS, body, ["docs", "a11y"]) if s.name == STEP)
        self.assertFalse(step.skipped)
        self.assertIn("check-specialists", step.command)
        self.assertIn(str(body.resolve()), step.command)
        self.assertEqual(step.command[step.command.index("--labels") + 1], "docs,a11y")
        self.assertEqual(step.command[step.command.index("--mode") + 1], "warn")

    def test_no_step_without_specialists(self) -> None:
        self.assertNotIn(STEP, [s.name for s in self.plan("")])


if __name__ == "__main__":
    unittest.main()
