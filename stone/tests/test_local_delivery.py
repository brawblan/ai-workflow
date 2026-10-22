"""Issue #120: delivery: local, the protected-path check for plans and reports, and stone gate."""

import contextlib
import datetime as dt
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from stone import framework_check, gate, render
from test_render import CONFIG, FRAMEWORK, ROLE_FILES

WORKFLOWS = ".github/workflows/"


class LocalDeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()
        self.write_config(CONFIG + "delivery: local\n")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def write_config(self, text: str) -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")

    def render(self) -> tuple[render.Result, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = render.render(self.root, FRAMEWORK, today=dt.date(2026, 10, 17))
        return result, err.getvalue()

    def test_local_writes_no_workflow_file(self) -> None:
        result, _ = self.render()
        self.assertFalse([p for p in result.wrote if p.startswith(WORKFLOWS)])
        self.assertFalse((self.root / ".github").exists())
        self.assertTrue(set(ROLE_FILES) <= set(result.wrote))

    def test_ci_is_the_default(self) -> None:
        self.write_config(CONFIG)
        result, _ = self.render()
        self.assertIn(WORKFLOWS + "cornerstone-checks.yml", result.wrote)

    def test_local_warns_and_prints_ignore_patterns(self) -> None:
        _, err = self.render()
        self.assertIn("G3 runs on this machine only", err)
        for pattern in (".claude/", ".cornerstone/", "docs/plans/", "docs/reports/", "AGENTS.md"):
            self.assertIn(f"  {pattern}\n", err)
        self.assertNotIn(WORKFLOWS, err.split("Add these lines")[1])

    def test_delivery_must_be_ci_or_local(self) -> None:
        self.write_config(CONFIG + "delivery: remote\n")
        with self.assertRaisesRegex(render.RenderError, "delivery 'remote' is not valid"):
            self.render()


class ProtectedPathTest(unittest.TestCase):
    def problems(self, **paths: object) -> list[str]:
        return framework_check.protected_path_problems({"paths": paths})

    def test_defaults_are_valid(self) -> None:
        self.assertEqual(self.problems(tests=["tests/"], checks=[".cornerstone/checks/"]), [])

    def test_plans_under_cornerstone_fails(self) -> None:
        found = self.problems(plans=".cornerstone/plans/", reports=".cornerstone/reports/")
        self.assertEqual(len(found), 2)  # plans and reports, each under .cornerstone/
        self.assertIn("'paths.plans' (.cornerstone/plans/) overlaps", found[0])

    def test_reports_under_tests_or_checks_fails(self) -> None:
        self.assertTrue(self.problems(tests=["tests/"], reports="tests/reports/"))
        self.assertTrue(self.problems(checks=["ci/"], plans="ci/plans"))

    def test_the_overlap_works_in_both_directions(self) -> None:
        self.assertTrue(self.problems(tests=["docs/plans/x/"], plans="docs/plans/"))

    def test_a_sibling_folder_is_not_an_overlap(self) -> None:
        self.assertEqual(self.problems(tests=["docs/plans-old/"], plans="docs/plans/"), [])

    def test_a_glob_counts_up_to_its_folder(self) -> None:
        self.assertTrue(self.problems(tests=["docs/plans/*.py"], plans="docs/plans/"))
        self.assertEqual(self.problems(tests=["**/*_test.py"], plans="docs/plans/"), [])

    def test_render_and_check_fail(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".cornerstone").mkdir()
            (root / ".cornerstone" / "config.yaml").write_text(
                CONFIG.replace("docs/plans/", ".claude/plans/"), encoding="utf-8")
            with self.assertRaisesRegex(render.RenderError, "overlaps the protected path"):
                with contextlib.redirect_stderr(io.StringIO()):
                    render.render(root, FRAMEWORK)
            self.assertTrue(any("overlaps" in f.message
                                for f in framework_check.check_config(root, FRAMEWORK)))


class GateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()
        (self.root / ".cornerstone" / "config.yaml").write_text(
            CONFIG.replace("make check", "exit 0") + "delivery: local\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "a@example.com")
        self.git("config", "user.name", "a")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base", "--trailer", "Role: generator")
        self.git("update-ref", "refs/remotes/origin/dev", "HEAD")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def test_passes_on_a_clean_branch_and_writes_evidence(self) -> None:
        (self.root / "src.py").write_text("x = 1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")
        steps, text = gate.run(self.root)
        self.assertTrue(all(step.passed for step in steps), text)
        self.assertIn("| K6 protected paths | pass |", text)
        self.assertIn("Base `origin/dev`", text)

    def test_k6_fails_on_a_protected_path(self) -> None:
        (self.root / "tests").mkdir()
        (self.root / "tests" / "t.py").write_text("x = 1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change a test")
        steps, text = gate.run(self.root)
        self.assertFalse(steps[0].passed)
        self.assertIn("| K6 protected paths | FAIL |", text)

    def test_all_checks_failure_is_reported(self) -> None:
        config = self.root / ".cornerstone" / "config.yaml"
        config.write_text(config.read_text().replace("all_checks: exit 0", "all_checks: exit 1"))
        steps, _ = gate.run(self.root)
        self.assertEqual([step.passed for step in steps], [True, True, False])

    def test_missing_check_script_is_an_error(self) -> None:
        (self.root / ".cornerstone" / "checks" / "change_size.py").unlink()
        with self.assertRaisesRegex(gate.GateError, "change_size.py: no file"):
            gate.run(self.root)


if __name__ == "__main__":
    unittest.main()
