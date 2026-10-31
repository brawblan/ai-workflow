"""Issue #224: the text form of the generated files (form.py) and the drift check."""

import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import form, render
from test_render import CONFIG, FRAMEWORK, TODAY

CHANGED_FORM = """a:
- 'x'
-   y
b: ''
"""


class DumpYamlTest(unittest.TestCase):
    def test_list_is_indented_under_its_key(self) -> None:
        self.assertEqual(form.dump_yaml({"key": ["one", "two"]}), "key:\n  - one\n  - two\n")

    def test_nested_list_is_indented(self) -> None:
        text = form.dump_yaml({"a": [{"b": [1, 2]}]})
        self.assertEqual(text, "a:\n  - b:\n      - 1\n      - 2\n")

    def test_empty_string_uses_double_quotes(self) -> None:
        self.assertEqual(form.dump_yaml({"a": ""}), 'a: ""\n')

    def test_date_string_uses_double_quotes(self) -> None:
        self.assertEqual(form.dump_yaml({"d": "2026-10-30"}), 'd: "2026-10-30"\n')

    def test_no_single_quotes_are_written(self) -> None:
        text = form.dump_yaml({"a": "yes", "b": "1.10", "c": "x: y", "d": "- z"})
        self.assertNotIn("'", text)

    def test_long_value_stays_on_one_line(self) -> None:
        value = " ".join(["word"] * 60)
        text = form.dump_yaml({"k": value})
        self.assertEqual(len(text.splitlines()), 1)
        self.assertGreater(len(text), 80)

    def test_round_trip_equals_the_input(self) -> None:
        data = {"v": "1.4.0", "d": "2026-10-30", "e": "", "n": None, "t": True, "i": 3,
                "l": ["a", "yes", "1", "x: y", "", "it's", 'say "hi"'], "m": {"k": ["z"], "u": "é"},
                "long": "x " * 100}
        self.assertEqual(yaml.safe_load(form.dump_yaml(data)), data)


class TableTest(unittest.TestCase):
    def test_columns_are_aligned(self) -> None:
        self.assertEqual(form.table([["A", "Bee"], ["longer", "x"]]),
                         ["| A      | Bee |", "| ------ | --- |", "| longer | x   |"])

    def test_minimum_width_is_three(self) -> None:
        lines = form.table([["a"], ["b"]])
        self.assertEqual(lines, ["| a   |", "| --- |", "| b   |"])

    def test_wide_characters_count_as_two(self) -> None:
        lines = form.table([["h"], ["日本"]])
        self.assertEqual(lines, ["| h    |", "| ---- |", "| 日本 |"])

    def test_header_only(self) -> None:
        self.assertEqual(form.table([["Name", "Id"]]), ["| Name | Id  |", "| ---- | --- |"])


class SameFormTest(unittest.TestCase):
    def test_equal_text(self) -> None:
        self.assertTrue(form.same_form("a.txt", "x\n", "x\n"))

    def test_other_extension_differs(self) -> None:
        self.assertFalse(form.same_form("a.txt", "x\n", "x \n"))
        self.assertFalse(form.same_form("a.py", "x=1", "x = 1"))

    def test_yaml_quote_style_and_indent_do_not_matter(self) -> None:
        for name in ("a.yaml", "a.yml"):
            self.assertTrue(form.same_form(name, "k:\n- 'a'\n- b\n", 'k:\n  - "a"\n  - b\n'))

    def test_yaml_value_change_matters(self) -> None:
        self.assertFalse(form.same_form("a.yaml", "k: a\n", "k: b\n"))
        self.assertFalse(form.same_form("a.yaml", "k: [a]\n", "k: [a, b]\n"))

    def test_invalid_yaml_is_false(self) -> None:
        self.assertFalse(form.same_form("a.yaml", "k: [a\n", "k: a\n"))
        self.assertFalse(form.same_form("a.yaml", "k: a\n", "k: [a\n"))

    def test_json_whitespace_does_not_matter(self) -> None:
        data = {"a": [1, 2], "b": {"c": "d"}}
        self.assertTrue(form.same_form("a.json", json.dumps(data), json.dumps(data, indent="\t")))

    def test_json_value_change_matters(self) -> None:
        self.assertFalse(form.same_form("a.json", '{"a": 1}', '{"a": 2}'))

    def test_invalid_json_is_false(self) -> None:
        self.assertFalse(form.same_form("a.json", "{", '{"a": 1}'))

    def test_markdown_whitespace_and_blank_lines_do_not_matter(self) -> None:
        self.assertTrue(form.same_form("a.md", "# T\nsome   words\n", "# T\n\n\nsome words  \n"))

    def test_markdown_table_width_does_not_matter(self) -> None:
        narrow = "| A | B |\n| --- | --- |\n| x | y |\n"
        wide = "| A     | B   |\n| ----- | --- |\n| x     | y   |\n"
        self.assertTrue(form.same_form("a.md", narrow, wide))

    def test_markdown_word_change_matters(self) -> None:
        self.assertFalse(form.same_form("a.md", "some words\n", "some other words\n"))
        self.assertFalse(form.same_form("a.md", "| A |\n| --- |\n| x |\n", "| A |\n| --- |\n| z |\n"))


class RenderFormTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG, encoding="utf-8")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def render(self) -> render.Result:
        with contextlib.redirect_stderr(io.StringIO()):
            return render.render(self.root, FRAMEWORK, today=TODAY)

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def test_manifest_uses_the_new_form(self) -> None:
        self.render()
        text = self.read(".cornerstone/manifest.yaml")
        self.assertNotIn("'", text)
        self.assertIn("components:\n  - ", text)

    def test_unchanged_file_gets_the_new_form(self) -> None:
        """A file with the manifest hash is written, even if only its form differs."""
        self.render()
        tester = ".claude/agents/tester.md"
        new = self.read(tester)
        old = new.replace("\n", "\n\n", 3)
        (self.root / tester).write_text(old, encoding="utf-8")
        manifest = yaml.safe_load(self.read(".cornerstone/manifest.yaml"))
        entry = next(c for c in manifest["components"] if c["id"] == "role.tester")
        entry["hash"] = render.content_hash({tester: old})
        (self.root / ".cornerstone/manifest.yaml").write_text(yaml.safe_dump(manifest),
                                                              encoding="utf-8")
        result = self.render()
        self.assertEqual(result.drift, [])
        self.assertIn(tester, result.wrote)
        self.assertEqual(self.read(tester), new)

    def test_reformatted_file_is_skipped_not_drift(self) -> None:
        self.render()
        tester = self.root / ".claude/agents/tester.md"
        person = tester.read_text(encoding="utf-8").replace("\n", "\n\n").rstrip("\n") + "\n\n\n"
        tester.write_text(person, encoding="utf-8")
        result = self.render()
        self.assertEqual(result.drift, [])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(".claude/agents/tester.md", result.skipped)
        self.assertEqual(tester.read_text(encoding="utf-8"), person)

    def test_content_change_is_still_drift(self) -> None:
        self.render()
        tester = self.root / ".claude/agents/tester.md"
        tester.write_text(tester.read_text(encoding="utf-8") + "\nA new rule.\n", encoding="utf-8")
        result = self.render()
        self.assertEqual(result.drift, [".claude/agents/tester.md"])
        self.assertEqual(result.exit_code, 2)

    def test_reformatted_manifest_is_not_rewritten(self) -> None:
        self.render()
        path = self.root / ".cornerstone/manifest.yaml"
        path.write_text(yaml.safe_dump(yaml.safe_load(path.read_text()), sort_keys=False),
                        encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        result = self.render()
        self.assertNotIn(".cornerstone/manifest.yaml", result.wrote)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_changed_manifest_value_is_rewritten(self) -> None:
        self.render()
        path = self.root / ".cornerstone/manifest.yaml"
        path.write_text(path.read_text().replace("0.1.0", "0.0.9", 1), encoding="utf-8")
        result = self.render()
        self.assertIn(".cornerstone/manifest.yaml", result.wrote)
        self.assertEqual(yaml.safe_load(path.read_text())["framework_version"], "0.1.0")


if __name__ == "__main__":
    unittest.main()
