"""Issue #122: adoption: opt-in, the marker step of the G3 workflow, and the K6 human rule."""

import contextlib
import datetime as dt
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import render
from test_render import CONFIG, FRAMEWORK

K6 = ".cornerstone/checks/protected_paths.py"
WORKFLOW = ".github/workflows/cornerstone-checks.yml"
IF = "steps.marker.outputs.cornerstone == 'true'"


class AdoptionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def render(self, extra: str = "") -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG + extra, encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK, today=dt.date(2026, 10, 17))

    def workflow(self) -> dict:
        return yaml.safe_load((self.root / WORKFLOW).read_text(encoding="utf-8"))

    def steps(self) -> list[dict]:
        return self.workflow()["jobs"]["checks"]["steps"]

    def test_all_is_the_default_and_has_no_marker(self) -> None:
        self.render()
        text = (self.root / WORKFLOW).read_text(encoding="utf-8")
        self.assertNotIn("marker", text)
        self.assertNotIn("types:", text)
        self.assertIn('ADOPTION = "all"', (self.root / K6).read_text(encoding="utf-8"))

    def test_opt_in_gates_each_cornerstone_step_on_the_marker(self) -> None:
        self.render("adoption: opt-in\n")
        steps = self.steps()
        self.assertEqual(steps[1]["id"], "marker")
        names = {step["name"] for step in steps if step.get("if") == IF}
        for name in ("K6 protected paths", "K7 change size", "Install stone", "K14 PR evidence",
                     "Install", "All checks"):
            self.assertIn(name, names)
        self.assertFalse([s["name"] for s in steps[2:] if s.get("if") != IF], "a step has no if")
        self.assertNotIn("if", steps[0])  # the checkout runs for each PR

    def test_opt_in_gates_the_profile_steps_too(self) -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(
            CONFIG.replace("[single-ticket]", "[app-slice]").replace(
                "  all_checks:", "  test_acceptance: make acceptance\n  test_integration: make it\n"
                "  architecture: make arch\n  all_checks:") + "adoption: opt-in\n",
            encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK, today=dt.date(2026, 10, 17))
        steps = self.steps()
        self.assertGreater(len(steps), 8)
        self.assertFalse([s["name"] for s in steps[2:] if s.get("if") != IF])

    def test_opt_in_runs_again_when_the_marker_changes(self) -> None:
        self.render("adoption: opt-in\n")
        types = self.workflow()[True]["pull_request"]["types"]  # YAML reads "on" as True
        self.assertEqual(set(types),
                         {"opened", "synchronize", "reopened", "edited", "labeled", "unlabeled"})

    def marker(self, body: str, labels: str) -> str:
        step = next(s for s in self.steps() if s.get("id") == "marker")
        output = self.root / "out.txt"
        output.unlink(missing_ok=True)
        env = {**os.environ, "PR_BODY": body, "PR_LABELS": labels, "GITHUB_OUTPUT": str(output)}
        subprocess.run(["bash", "-c", step["run"]], env=env, check=True, capture_output=True)
        return output.read_text(encoding="utf-8").strip()

    def test_marker_rule(self) -> None:
        self.render("adoption: opt-in\n")
        self.assertEqual(self.marker("Profile: single-ticket\n\nText", "[]"), "cornerstone=true")
        self.assertEqual(self.marker("Text\r\nProfile: single-ticket\r\n", "[]"), "cornerstone=true")
        self.assertEqual(self.marker("", '["bug","cornerstone"]'), "cornerstone=true")
        self.assertEqual(self.marker("The Profile: line is not here", '["bug"]'),
                         "cornerstone=false")
        self.assertEqual(self.marker("", '["cornerstone-x"]'), "cornerstone=false")

    def test_the_marker_must_name_a_profile_of_the_config(self) -> None:
        self.render("adoption: opt-in\n")
        self.assertEqual(self.marker("Profile: other\n", "[]"), "cornerstone=false")
        self.assertEqual(self.marker("Profile: <id>\n", "[]"), "cornerstone=false")
        self.assertEqual(self.marker("Profile: single-ticket-x\n", "[]"), "cornerstone=false")
        self.assertEqual(self.marker("Profile: single-ticket  \n", "[]"), "cornerstone=true")

    def test_role_files_get_the_marker_rule_only_in_opt_in(self) -> None:
        self.render()
        self.assertNotIn("cornerstone`", (self.root / ".claude/agents/tester.md").read_text())
        self.render("adoption: opt-in\n")
        for role in ("implementer", "tester"):
            text = (self.root / f".claude/agents/{role}.md").read_text(encoding="utf-8")
            self.assertIn("add the line `Profile: <id>` to the PR body, or the label "
                          "`cornerstone`", text)

    def test_invalid_adoption_fails(self) -> None:
        with self.assertRaisesRegex(render.RenderError, "adoption 'some' is not valid"):
            self.render("adoption: some\n")

    def test_k6_text_in_role_files_follows_trailers(self) -> None:
        self.render()
        self.assertIn("Check K6 fails the commit in CI:",
                      (self.root / ".claude/agents/implementer.md").read_text())
        self.render("commits: {trailers: none}\n")
        implementer = (self.root / ".claude/agents/implementer.md").read_text()
        self.assertNotIn("K6", implementer)
        self.assertIn("on these paths. The paths are:", implementer)
        self.assertNotIn("K6", (self.root / ".claude/agents/investigator.md").read_text()
                         if (self.root / ".claude/agents/investigator.md").exists() else "")


class K6HumanTest(unittest.TestCase):
    """K6 in opt-in mode: Actor: human with no Role is a human commit."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def k6_after(self, adoption: str, message: str) -> int:
        (self.root / ".cornerstone" / "config.yaml").write_text(
            CONFIG + f"adoption: {adoption}\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK)
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "a@example.com"),
                     ("config", "user.name", "a"), ("add", "-A"), ("commit", "-q", "-m", "base")):
            self.git(*args)
        self.git("update-ref", "refs/remotes/origin/dev", "HEAD")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "t.py").write_text("x = 1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "a test", *message.split("|"))
        return subprocess.run(["python3", K6, "origin/dev"], cwd=self.root,
                              capture_output=True, text=True).returncode

    def test_opt_in_human_commit_passes(self) -> None:
        self.assertEqual(self.k6_after("opt-in", "--trailer|Actor: human"), 0)

    def test_all_mode_still_counts_it_as_implementer(self) -> None:
        self.assertEqual(self.k6_after("all", "--trailer|Actor: human"), 1)

    def test_opt_in_commit_with_no_trailer_is_still_implementer(self) -> None:
        self.assertEqual(self.k6_after("opt-in", "--allow-empty-message"), 1)

    def test_opt_in_agent_implementer_still_fails(self) -> None:
        self.assertEqual(
            self.k6_after("opt-in", "--trailer|Role: implementer|--trailer|Actor: agent"), 1)


if __name__ == "__main__":
    unittest.main()
