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


class DefaultExcludeTest(unittest.TestCase):
    """AC9: role files in a `.claude/` folder at any depth are out of K17 scope (writing.md)."""

    TEXT = "# Role\n\nJust erase the cache.\n"  # two K17 errors: Rule 5 and Rule 1

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.root = Path(self._folder.name)

    def write(self, name: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.TEXT, encoding="utf-8")

    def paths_with_errors(self, *names: str) -> list[str]:
        for name in names:
            self.write(name)
        findings = run(self.root, list(names), None, rules(), DEFAULT_EXCLUDE)
        return sorted({f.path for f in findings if f.severity == "error"})

    def test_ac9_nested_claude_folder_gives_no_finding(self) -> None:
        self.assertEqual(self.paths_with_errors("pkg/.claude/agents/x.md"), [])

    def test_ac9_deeply_nested_claude_folder_gives_no_finding(self) -> None:
        name = "stone/tests/golden/debugging/.claude/agents/tester.md"
        self.assertEqual(self.paths_with_errors(name), [])

    def test_ac9_root_claude_folder_still_gives_no_finding(self) -> None:
        self.assertEqual(self.paths_with_errors(".claude/agents/x.md"), [])

    def test_ac9_nested_claude_folder_given_as_a_folder_gives_no_finding(self) -> None:
        self.write("pkg/.claude/agents/x.md")
        findings = run(self.root, ["pkg"], None, rules(), DEFAULT_EXCLUDE)
        self.assertEqual(findings, [])

    def test_ac9_same_text_in_docs_gives_a_finding(self) -> None:
        self.assertEqual(self.paths_with_errors("docs/x.md"), ["docs/x.md"])

    def test_ac9_same_text_in_both_places_flags_only_docs(self) -> None:
        found = self.paths_with_errors("pkg/.claude/agents/x.md", "docs/x.md")
        self.assertEqual(found, ["docs/x.md"])

    def test_ac9_claude_notes_file_name_is_still_checked(self) -> None:
        name = "notclaude/.claude-notes.md"
        self.assertEqual(self.paths_with_errors(name), [name])

    def test_ac9_folder_name_that_only_ends_in_claude_is_still_checked(self) -> None:
        for name in ("pkg/my.claude/x.md", "pkg/.claude-old/x.md"):
            with self.subTest(name=name):
                self.assertEqual(self.paths_with_errors(name), [name])

    def test_ac9_nested_claude_folder_is_skipped_in_diff_mode(self) -> None:
        def git(*args: str) -> None:
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "-c", "commit.gpgsign=false", *args],
                           cwd=self.root, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        (self.root / "README.md").write_text("# Readme\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        self.write("pkg/.claude/agents/x.md")
        self.write("docs/x.md")
        findings = run(self.root, [], "main", rules(), DEFAULT_EXCLUDE)
        self.assertEqual(sorted({f.path for f in findings}), ["docs/x.md"])


# AC10: K17 skips Markdown under a folder named golden, and still tests other files.

LONG_SENTENCE = " ".join(["word"] * 29) + " end.\n"  # 30 words: more than the limit of 25
GOLDEN_FILE = "stone/tests/golden/spike/.claude/agents/shaper.md"
OUTSIDE_FILE = "stone/tests/notes.md"


class GoldenFolderTest(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        # The rule file is outside the repo root, so that K17 does not test it.
        self.root = Path(self._folder.name) / "repo"
        self.root.mkdir()
        self.rules_path = Path(self._folder.name) / "ste.md"
        self.rules_path.write_text(RULES_MD, encoding="utf-8")

    def tearDown(self) -> None:
        self._folder.cleanup()

    def write(self, name: str, text: str = LONG_SENTENCE) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "-c", "commit.gpgsign=false", *args],
                       cwd=self.root, check=True, capture_output=True)

    def paths_found(self, paths: list[str], base: str | None = None) -> list[str]:
        findings = run(self.root, paths, base, rules(), DEFAULT_EXCLUDE)
        return sorted({f.path for f in findings})

    def cli(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["check-writing", "--root", str(self.root),
                             "--rules", str(self.rules_path), "--mode", "block", *args])
        return code, out.getvalue()

    def test_ac10_fixture_sentence_fails_outside_a_golden_folder(self) -> None:
        # Guard the test data: the same text has a finding when K17 tests it.
        self.assertEqual(found(LONG_SENTENCE), ["Rule 8|error"])

    def test_ac10_golden_file_given_by_path_is_skipped(self) -> None:
        self.write(GOLDEN_FILE)
        self.assertEqual(self.paths_found([GOLDEN_FILE]), [])

    def test_ac10_golden_file_in_a_folder_scan_is_skipped_and_others_are_tested(self) -> None:
        self.write(GOLDEN_FILE)
        self.write(OUTSIDE_FILE)
        self.assertEqual(self.paths_found(["stone"]), [OUTSIDE_FILE])

    def test_ac10_golden_file_without_claude_folder_is_skipped(self) -> None:
        name = "stone/tests/golden/spike/docs/report.md"
        self.write(name)
        self.write(OUTSIDE_FILE)
        self.assertEqual(self.paths_found(["stone"]), [OUTSIDE_FILE])

    def test_ac10_golden_file_in_a_diff_is_skipped_and_others_are_tested(self) -> None:
        self.git("init", "-q", "-b", "main")
        self.write("README.md", "# Readme\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.write(GOLDEN_FILE)
        self.write(OUTSIDE_FILE)
        self.assertEqual(self.paths_found([], base="main"), [OUTSIDE_FILE])

    def test_ac10_golden_folder_at_the_repo_root_is_skipped(self) -> None:
        self.write("golden/spike/.claude/agents/shaper.md")
        self.write(OUTSIDE_FILE)
        self.assertEqual(self.paths_found(["."]), [OUTSIDE_FILE])

    def test_ac10_near_names_are_still_tested(self) -> None:
        names = ["stone/tests/goldens/a.md", "stone/tests/not-golden/b.md",
                 "stone/tests/golden-files/c.md", "stone/tests/golden.md",
                 "docs/golden_notes.md"]
        for name in names:
            self.write(name)
        self.assertEqual(self.paths_found(["."]), sorted(names))

    def test_ac10_cli_passes_with_only_a_golden_file(self) -> None:
        self.write(GOLDEN_FILE)
        code, out = self.cli("stone")
        self.assertEqual(code, 0, out)
        self.assertIn("K17: 0 error(s)", out)
        self.assertNotIn("shaper.md", out)

    def test_ac10_cli_still_fails_on_a_file_outside_golden(self) -> None:
        self.write(GOLDEN_FILE)
        self.write(OUTSIDE_FILE)
        code, out = self.cli("stone")
        self.assertEqual(code, 1, out)
        self.assertIn("notes.md", out)
        self.assertNotIn("shaper.md", out)
        self.assertIn("K17: 1 error(s)", out)


if __name__ == "__main__":
    unittest.main()
