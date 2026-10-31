"""Issue #227: stone render lists only the ignore lines that git does not already ignore."""

import contextlib
import datetime as dt
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stone import render
from test_render import CONFIG, FRAMEWORK

HEADER = "Add these lines to .git/info/exclude:"
NOTE = "note: git cannot check the ignore rules here, so all the lines show."


class IsolatedGitTest(unittest.TestCase):
    """Base class: a temp folder, and a git setup that the developer's own config cannot change."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / "repo"
        self.root.mkdir()
        empty = Path(self.folder.name) / "empty-gitconfig"
        empty.write_text("", encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_NOSYSTEM": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def init_repo(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True, capture_output=True)

    def exclude(self, *lines: str) -> None:
        path = self.root / ".git" / "info" / "exclude"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")

    def not_ignored(self, patterns: list[str]) -> tuple[list[str], str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            found = render.not_ignored(self.root, patterns)
        return found, err.getvalue()


class NotIgnoredTest(IsolatedGitTest):
    def setUp(self) -> None:
        super().setUp()
        self.init_repo()

    def test_anchored_entry_removes_the_path(self) -> None:
        self.exclude("/.cornerstone/", "/AGENTS.md")
        found, err = self.not_ignored([".claude/", ".cornerstone/", "AGENTS.md"])
        self.assertEqual(found, [".claude/"])
        self.assertEqual(err, "")

    def test_parent_folder_entry_removes_the_child_path(self) -> None:
        self.exclude("/docs/", "/.cornerstone/")
        found, _ = self.not_ignored(["docs/plans/", ".cornerstone/manifest.yaml", "AGENTS.md"])
        self.assertEqual(found, ["AGENTS.md"])

    def test_gitignore_entry_without_slash_removes_the_path(self) -> None:
        (self.root / ".gitignore").write_text(".claude\n", encoding="utf-8")
        found, _ = self.not_ignored([".claude/", "AGENTS.md"])
        self.assertEqual(found, ["AGENTS.md"])

    def test_wildcard_entry_removes_the_path(self) -> None:
        self.exclude("*.md")
        found, _ = self.not_ignored(["AGENTS.md", ".claude/"])
        self.assertEqual(found, [".claude/"])

    def test_path_that_git_does_not_ignore_stays_in_input_order(self) -> None:
        self.exclude("/.cornerstone/")
        patterns = [".claude/", ".cornerstone/", "docs/plans/", "docs/reports/", "AGENTS.md"]
        found, err = self.not_ignored(patterns)
        self.assertEqual(found, [".claude/", "docs/plans/", "docs/reports/", "AGENTS.md"])
        self.assertEqual(err, "")

    def test_nothing_ignored_returns_all_the_patterns(self) -> None:
        patterns = [".claude/", "AGENTS.md"]
        found, err = self.not_ignored(patterns)
        self.assertEqual(found, patterns)
        self.assertEqual(err, "")

    def test_everything_ignored_returns_an_empty_list(self) -> None:
        self.exclude("/.claude/", "/AGENTS.md")
        found, _ = self.not_ignored([".claude/", "AGENTS.md"])
        self.assertEqual(found, [])

    def test_global_excludes_file_is_honoured(self) -> None:
        global_ignore = Path(self.folder.name) / "global-ignore"
        global_ignore.write_text("AGENTS.md\n", encoding="utf-8")
        config = Path(self.folder.name) / "gitconfig-with-excludes"
        config.write_text(f"[core]\n\texcludesFile = {global_ignore}\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config)}):
            found, _ = self.not_ignored(["AGENTS.md", ".claude/"])
        self.assertEqual(found, [".claude/"])


class GitUnavailableTest(IsolatedGitTest):
    def test_not_a_git_repo_returns_all_patterns_and_prints_the_note(self) -> None:
        patterns = [".claude/", "AGENTS.md"]
        found, err = self.not_ignored(patterns)
        self.assertEqual(found, patterns)
        self.assertIn(NOTE, err)

    def test_git_not_installed_returns_all_patterns_and_prints_the_note(self) -> None:
        self.init_repo()
        self.exclude("/AGENTS.md")
        patterns = [".claude/", "AGENTS.md"]
        with mock.patch("stone.render.subprocess.run", side_effect=OSError("no git")):
            found, err = self.not_ignored(patterns)
        self.assertEqual(found, patterns)
        self.assertIn(NOTE, err)


class RenderExcludeTest(IsolatedGitTest):
    def setUp(self) -> None:
        super().setUp()
        (self.root / ".cornerstone").mkdir()
        (self.root / ".cornerstone" / "config.yaml").write_text(
            CONFIG + "delivery: local\n", encoding="utf-8")

    def render(self) -> str:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            render.render(self.root, FRAMEWORK, today=dt.date(2026, 10, 17))
        return err.getvalue()

    def test_header_is_hidden_when_git_ignores_every_pattern(self) -> None:
        self.init_repo()
        self.exclude(".claude/", ".cornerstone/", "docs/plans/", "docs/reports/", "docs/specs/",
                     "constitution/", "AGENTS.md")
        err = self.render()
        self.assertIn("G3 runs on this machine only", err)
        self.assertNotIn(HEADER, err)
        self.assertNotIn("  AGENTS.md\n", err)
        self.assertNotIn(NOTE, err)

    def test_only_the_missing_patterns_print(self) -> None:
        self.init_repo()
        self.exclude("/.cornerstone/", "/AGENTS.md", "/docs/")
        err = self.render()
        self.assertIn(HEADER, err)
        self.assertIn("  .claude/\n", err)
        for pattern in (".cornerstone/", "AGENTS.md", "docs/plans/", "docs/reports/"):
            self.assertNotIn(f"  {pattern}\n", err)
        self.assertNotIn(NOTE, err)

    def test_no_ignore_rules_prints_the_old_format(self) -> None:
        self.init_repo()
        err = self.render()
        self.assertIn(HEADER, err)
        for pattern in (".claude/", ".cornerstone/", "docs/plans/", "docs/reports/", "AGENTS.md"):
            self.assertIn(f"  {pattern}\n", err)

    def test_not_a_git_repo_prints_the_note_and_all_the_lines(self) -> None:
        err = self.render()
        self.assertIn(NOTE, err)
        self.assertIn(HEADER, err)
        self.assertIn("  AGENTS.md\n", err)


if __name__ == "__main__":
    unittest.main()
