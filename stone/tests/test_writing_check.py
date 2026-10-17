"""Tests for K17 (stone check-writing)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stone.writing_check import Rules, check_text, load_rules

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


if __name__ == "__main__":
    unittest.main()
