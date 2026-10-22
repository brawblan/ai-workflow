"""Issue #121: the `commits` section of the repo config."""

import contextlib
import datetime as dt
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from stone import framework_check, gate, render
from test_render import CONFIG, FRAMEWORK

K6 = ".cornerstone/checks/protected_paths.py"
WORKFLOW = ".github/workflows/cornerstone-checks.yml"


class CommitConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def render(self, extra: str = "") -> tuple[render.Result, str]:
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG + extra, encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = render.render(self.root, FRAMEWORK, today=dt.date(2026, 10, 17))
        return result, err.getvalue()

    def text(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def test_default_commits_with_trailers(self) -> None:
        self.render()
        self.assertIn("5. Commit with the trailers `Role: implementer` and `Actor: agent`.",
                      self.text(".claude/agents/implementer.md"))
        self.assertIn("4. Commit with the trailers `Role: tester` and `Actor: agent`.",
                      self.text(".claude/agents/tester.md"))
        self.assertIn("Commit the\nfailing test.", self.text(".claude/agents/tester.md"))

    def test_human_commit_gets_a_proposed_message(self) -> None:
        self.render("commits: {by: human}\n")
        implementer = self.text(".claude/agents/implementer.md")
        self.assertIn("Do not commit. End with a proposed commit message that has the trailers "
                      "`Role: implementer` and `Actor: human`.", implementer)
        self.assertIn("Keep the failing test.", self.text(".claude/agents/tester.md"))

    def test_message_format_is_in_the_role_file(self) -> None:
        (self.root / "docs").mkdir()
        (self.root / "docs" / "commit-format.md").write_text("[scope] area: text\n")
        self.render("commits: {message_format: docs/commit-format.md}\n")
        self.assertIn("Follow the commit message format in `docs/commit-format.md`.",
                      self.text(".claude/agents/tester.md"))

    def test_notes_write_the_role_to_a_note(self) -> None:
        self.render("commits: {trailers: notes}\n")
        tester = self.text(".claude/agents/tester.md")
        self.assertIn('git notes --ref=cornerstone add -m "Role: tester" -m "Actor: agent" HEAD',
                      tester)
        self.assertIn("Commit with no trailers.", tester)
        self.assertIn('TRAILERS = "notes"', self.text(K6))

    def test_none_does_not_render_k6_and_warns(self) -> None:
        result, err = self.render("commits: {trailers: none}\n")
        self.assertNotIn(K6, result.wrote)
        self.assertFalse((self.root / K6).exists())
        self.assertNotIn("K6 protected paths", self.text(WORKFLOW))
        self.assertIn("K7 change size", self.text(WORKFLOW))
        self.assertIn("K6 cannot run", err)
        self.assertIn("Commit with no trailers and no git notes.",
                      self.text(".claude/agents/implementer.md"))

    def test_default_keeps_k6_in_the_workflow(self) -> None:
        self.render()
        self.assertIn("K6 protected paths", self.text(WORKFLOW))
        self.assertTrue((self.root / K6).exists())

    def test_check_rejects_bad_values(self) -> None:
        for extra, message in (("commits: {by: robot}\n", "'commits.by' is 'robot'"),
                               ("commits: {trailers: x}\n", "'commits.trailers' is 'x'"),
                               ("commits: {size: 1}\n", "'commits.size' is not a key"),
                               ("commits: {message_format: missing.md}\n", "not a file in the repo"),
                               ("commits: agent\n", "'commits' must be a map")):
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(render.RenderError, message):
                    self.render(extra)

    def test_check_accepts_a_url_and_stone_check_reports(self) -> None:
        self.render("commits: {message_format: 'https://example.com/format'}\n")
        self.assertEqual(framework_check.check_config(self.root, FRAMEWORK), [])


class NotesTest(unittest.TestCase):
    """K6 reads the role from a git note."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()
        (self.root / ".cornerstone" / "config.yaml").write_text(
            CONFIG + "commits: {trailers: notes}\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK)
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "a@example.com"),
                     ("config", "user.name", "a"), ("add", "-A"), ("commit", "-q", "-m", "base")):
            self.git(*args)
        self.git("update-ref", "refs/remotes/origin/dev", "HEAD")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "t.py").write_text("x = 1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "add a test")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def k6(self) -> int:
        return subprocess.run(["python3", K6, "origin/dev"], cwd=self.root,
                              capture_output=True, text=True).returncode

    def test_a_commit_with_no_note_is_an_implementer_commit(self) -> None:
        self.assertEqual(self.k6(), 1)

    def test_a_tester_note_passes(self) -> None:
        self.git("notes", "--ref=cornerstone", "add", "-m", "Role: tester", "-m",
                 "Actor: agent", "HEAD")
        self.assertEqual(self.k6(), 0)

    def test_an_implementer_note_fails(self) -> None:
        self.git("notes", "--ref=cornerstone", "add", "-m", "Role: implementer", "HEAD")
        self.assertEqual(self.k6(), 1)


class GateWithNoTrailersTest(unittest.TestCase):
    def test_gate_skips_k6(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".cornerstone").mkdir()
            (root / ".cornerstone" / "config.yaml").write_text(
                CONFIG.replace("make check", "exit 0") + "commits: {trailers: none}\n",
                encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                render.render(root, FRAMEWORK)
            for args in (("init", "-q", "-b", "main"), ("config", "user.email", "a@example.com"),
                         ("config", "user.name", "a"), ("add", "-A"), ("commit", "-q", "-m", "x")):
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "update-ref", "refs/remotes/origin/dev", "HEAD"], cwd=root,
                           check=True)
            steps, text = gate.run(root)
            self.assertIn("| K6 protected paths | skipped (commits.trailers: none) |", text)
            self.assertTrue(all(step.passed or step.skipped for step in steps), text)


if __name__ == "__main__":
    unittest.main()
