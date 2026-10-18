"""Tests for K17 (stone check-writing)."""

from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from stone import cli
from stone.writing_check import (DEFAULT_EXCLUDE, Rules, changed_lines, check_text, load_rules,
                                 run)

RULES_MD = """# Rules

5. Do not use vague words: simply, just, robust, etc.

## Dictionary

### Project dictionary

| Term | Meaning | Do not use |
| --- | --- | --- |
| tenant | Example only. | org |

### Removal (all projects)

| Term | Meaning | Do not use |
| --- | --- | --- |
| remove | Take out an item. | delete (for these items) |
| delete | Destroy stored data. | remove, erase |
"""


def rules() -> Rules:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "ste.md"
        path.write_text(RULES_MD, encoding="utf-8")
        return load_rules(path, None)


def found(text: str) -> list[str]:
    return sorted(f"{f.message.split(':')[0]}|{f.severity}" for f in check_text("x.md", text, rules()))


class LoadRulesTest(unittest.TestCase):
    def test_reads_vague_words(self) -> None:
        self.assertEqual(rules().vague_words, {"simply", "just", "robust"})

    def test_bans_only_terms_without_context(self) -> None:
        # "remove" is an approved term, and "delete (for these items)" has a qualifier.
        self.assertEqual(rules().banned_terms, {"erase": "delete"})

    def test_skips_the_example_project_dictionary(self) -> None:
        self.assertNotIn("org", rules().banned_terms)


class CheckTextTest(unittest.TestCase):
    def test_long_description_fails(self) -> None:
        text = " ".join(["word"] * 26) + "."
        self.assertEqual(found(text), ["Rule 8|error"])

    def test_procedure_limit_is_20(self) -> None:
        self.assertEqual(found("1. " + " ".join(["run"] * 21) + "."), ["Rule 8|error"])
        self.assertEqual(found("1. " + " ".join(["run"] * 20) + "."), [])

    def test_wrapped_list_item_is_one_sentence(self) -> None:
        text = "1. " + " ".join(["run"] * 12) + "\n   " + " ".join(["run"] * 12) + "."
        self.assertEqual(found(text), ["Rule 8|error"])

    def test_vague_word_and_banned_term(self) -> None:
        self.assertEqual(found("Just erase the cache."), ["Rule 1|error", "Rule 5|error"])

    def test_progressive_and_passive_are_warnings(self) -> None:
        self.assertEqual(found("The job is running."), ["Rule 2|warning"])
        self.assertEqual(found("1. The file is copied."), ["Rule 11|warning"])

    def test_long_paragraph_fails(self) -> None:
        self.assertEqual(found("Run it. " * 7), ["Rule 13|error"])

    def test_out_of_scope_text_is_skipped(self) -> None:
        text = (
            "---\ntitle: robust\n---\n"
            "# A robust heading\n\n"
            "```\njust code\n```\n\n"
            'Use `simply` and "just this" and [the docs](https://example.com/just).\n\n'
            "This line is simply ignored. <!-- ste-ignore -->\n"
        )
        self.assertEqual(found(text), [])

    def test_table_cells_are_checked(self) -> None:
        self.assertEqual(found("| a | Just do it. |\n| --- | --- |"), ["Rule 5|error"])

    def test_line_number_points_to_the_sentence(self) -> None:
        text = "Intro.\n\nFirst line. Second\nline is just here."
        lines = [f.line for f in check_text("x.md", text, rules())]
        self.assertEqual(lines, [3])


class ChangedLinesTest(unittest.TestCase):
    """`--diff BASE` tests the lines that changed since the merge base, in the working tree."""

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.root = Path(self._folder.name)
        self.git("init", "-q", "-b", "main")
        self.write("doc.md", "# Doc\n\nOne.\nTwo.\nThree.\n")
        self.write(".gitignore", "ignored.md\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "feature")

    def tearDown(self) -> None:
        self._folder.cleanup()

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "-c", "commit.gpgsign=false", *args],
                       cwd=self.root, check=True, capture_output=True)

    def write(self, name: str, text: str) -> None:
        (self.root / name).write_text(text, encoding="utf-8")

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def test_committed_change_counts(self) -> None:
        self.write("doc.md", "# Doc\n\nOne.\nTwo changed.\nThree.\n")
        self.commit("change")
        self.assertEqual(changed_lines("main", self.root), {"doc.md": {4}})

    def test_unstaged_change_counts(self) -> None:
        self.write("doc.md", "# Doc\n\nOne.\nTwo changed.\nThree.\n")
        self.assertEqual(changed_lines("main", self.root), {"doc.md": {4}})

    def test_staged_change_counts(self) -> None:
        self.write("doc.md", "# Doc\n\nOne.\nTwo.\nThree changed.\n")
        self.git("add", "doc.md")
        self.assertEqual(changed_lines("main", self.root), {"doc.md": {5}})

    def test_untracked_file_counts_in_full(self) -> None:
        self.write("new.md", "# New\n\nText.\n")
        self.assertEqual(changed_lines("main", self.root), {"new.md": {1, 2, 3}})

    def test_ignored_and_non_markdown_files_do_not_count(self) -> None:
        self.write("ignored.md", "Just this.\n")
        self.write("notes.txt", "Just this.\n")
        self.assertEqual(changed_lines("main", self.root), {})

    def test_clean_tree_with_no_change_is_empty(self) -> None:
        self.assertEqual(changed_lines("main", self.root), {})

    def test_new_commits_on_the_base_do_not_count(self) -> None:
        self.git("checkout", "-q", "main")
        self.write("doc.md", "# Doc\n\nOne on main.\nTwo.\nThree.\n")
        self.commit("main moves")
        self.git("checkout", "-q", "feature")
        self.write("doc.md", "# Doc\n\nOne.\nTwo.\nThree on feature.\n")
        self.assertEqual(changed_lines("main", self.root), {"doc.md": {5}})

    def test_run_reports_errors_before_a_commit(self) -> None:
        self.write("doc.md", "# Doc\n\nOne.\nJust two.\nThree.\n")
        self.write("new.md", "# New\n\nErase the cache.\n")
        findings = run(self.root, [], "main", rules(), [])
        self.assertEqual(sorted((f.path, f.line) for f in findings),
                         [("doc.md", 4), ("new.md", 3)])


class ClaudeFolderTest(unittest.TestCase):
    """AC12: K17 skips Markdown under a `.claude/` folder at any depth. Agent text is out of scope.

    D28: K17 also skips every file under a `golden/` folder.
    """

    BAD = "# Doc\n\nJust erase the cache.\n"
    SKIPPED = [".claude/agents/a.md",
               "plugins/x/.claude/a.md",
               "stone/tests/golden/x/expected/.claude/agents/a.md"]
    GOLDEN = ["stone/tests/golden/x/expected/docs/c.md"]
    TESTED = ["docs/b.md",
              "plugins/x/docs/c.md",
              "docs/claude/d.md",
              "docs/.claude-notes/e.md"]

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.root = Path(self._folder.name) / "repo"
        self.root.mkdir()
        # The rule file is outside the repo, so --diff does not test it.
        self.rules_path = Path(self._folder.name) / "ste.md"
        self.rules_path.write_text(RULES_MD, encoding="utf-8")
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "-c", "commit.gpgsign=false", "init", "-q", "-b", "main"],
                       cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty",
                        "-m", "base"], cwd=self.root, check=True, capture_output=True)
        for name in self.SKIPPED + self.GOLDEN + self.TESTED:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.BAD, encoding="utf-8")

    def tearDown(self) -> None:
        self._folder.cleanup()

    def paths(self, findings: list) -> set[str]:
        return {Path(f.path).as_posix() for f in findings}

    def test_ac12_diff_skips_claude_folders_at_any_depth(self) -> None:
        found_paths = self.paths(run(self.root, [], "main", rules(), DEFAULT_EXCLUDE))
        for name in self.SKIPPED:
            with self.subTest(path=name):
                self.assertNotIn(name, found_paths)

    def test_ac12_diff_skips_golden_folders(self) -> None:
        found_paths = self.paths(run(self.root, [], "main", rules(), DEFAULT_EXCLUDE))
        for name in self.GOLDEN:
            with self.subTest(path=name):
                self.assertNotIn(name, found_paths)

    def test_ac12_diff_still_tests_other_files(self) -> None:
        found_paths = self.paths(run(self.root, [], "main", rules(), DEFAULT_EXCLUDE))
        self.assertEqual(found_paths, set(self.TESTED))

    def test_ac12_folder_path_skips_nested_claude_folder(self) -> None:
        findings = run(self.root, ["plugins/x"], None, rules(), DEFAULT_EXCLUDE)
        self.assertEqual(self.paths(findings), {"plugins/x/docs/c.md"})

    def test_ac12_folder_path_skips_golden_folder(self) -> None:
        findings = run(self.root, ["stone/tests/golden"], None, rules(), DEFAULT_EXCLUDE)
        self.assertEqual(self.paths(findings), set())

    def cli_block(self) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["check-writing", "--root", str(self.root), "--rules",
                             str(self.rules_path), "--diff", "main", "--mode", "block"])
        return code, out.getvalue()

    def test_ac12_cli_block_mode_passes_with_only_claude_files(self) -> None:
        for name in self.TESTED:
            (self.root / name).unlink()
        code, out = self.cli_block()
        self.assertEqual(code, 0, out)
        self.assertIn("K17: 0 error(s)", out)

    def test_ac12_cli_block_mode_still_fails_on_other_files(self) -> None:
        code, out = self.cli_block()
        self.assertEqual(code, 1, out)
        self.assertIn("docs/b.md", out)
        self.assertNotIn(".claude/", out)


if __name__ == "__main__":
    unittest.main()
