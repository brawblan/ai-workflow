"""Tests of `golden_helpers.py`: the shared fixture rule of the golden tests (D64, issue #148)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import golden_helpers as helpers
from golden_helpers import (SHARED, UPDATE_ENV, golden_differences, golden_renders, shared_files,
                            shared_folder, tree_files, update_golden, updating, write_tree)

SHARED_PATHS = {".cornerstone/lib/path_match.py", ".claude/settings.json",
                *(f".claude/agents/{role}.md" for role in (
                    "implementer", "investigator", "planner", "reviewer", "shaper", "tester"))}


class RuleTest(unittest.TestCase):
    """The layout is `tmp/golden/one/` (profile folder) and `tmp/golden/_shared/`."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.golden = Path(folder.name) / "golden" / "one"
        self.shared = Path(folder.name) / "golden" / "_shared"
        write_tree(self.golden, {"own.txt": b"own\n"})
        write_tree(self.shared, {"common/s.txt": b"s\n"})
        self.files = {"own.txt": b"own\n", "common/s.txt": b"s\n"}

    def test_a_file_in_either_folder_matches(self) -> None:
        self.assertEqual(golden_differences(self.golden, self.files), [])

    def test_a_file_in_neither_folder_is_extra(self) -> None:
        messages = golden_differences(self.golden, {**self.files, "new.txt": b"n\n"})
        self.assertEqual(len(messages), 1, messages)
        self.assertTrue(messages[0].startswith("extra file new.txt"), messages)

    def test_a_profile_file_that_render_did_not_write_is_missing(self) -> None:
        messages = golden_differences(self.golden, {"common/s.txt": b"s\n"})
        self.assertEqual(len(messages), 1, messages)
        self.assertTrue(messages[0].startswith("missing file own.txt"), messages)

    def test_a_shared_file_that_this_test_does_not_render_is_no_difference(self) -> None:
        self.assertEqual(golden_differences(self.golden, {"own.txt": b"own\n"}), [])

    def test_a_changed_shared_file_names_the_shared_path(self) -> None:
        messages = golden_differences(self.golden, {**self.files, "common/s.txt": b"t\n"})
        self.assertEqual(len(messages), 1, messages)
        self.assertIn("changed file common/s.txt", messages[0])
        self.assertIn(str(self.shared / "common/s.txt"), messages[0])

    def test_a_file_in_both_folders_is_a_duplicate(self) -> None:
        write_tree(self.golden, {**self.files})
        messages = golden_differences(self.golden, self.files)
        self.assertEqual(len(messages), 1, messages)
        self.assertTrue(messages[0].startswith("duplicate file common/s.txt"), messages)

    def test_each_message_tells_the_reader_to_update(self) -> None:
        write_tree(self.golden, {"own.txt": b"x\n", "old.txt": b"o\n", "common/s.txt": b"s\n"})
        messages = golden_differences(self.golden, {"own.txt": b"own\n", "new.txt": b"n\n"})
        self.assertEqual(len(messages), 4, messages)
        for message in messages:
            self.assertIn(f"{UPDATE_ENV}=1", message)

    def test_one_changed_byte_and_a_line_ending_change_fail(self) -> None:
        for content in (b"own\n ", b"own\r\n"):
            with self.subTest(content=content):
                messages = golden_differences(self.golden, {**self.files, "own.txt": content})
                self.assertEqual(len(messages), 1, messages)
                self.assertIn("changed file own.txt", messages[0])


class SharedFolderTest(unittest.TestCase):
    def test_a_folder_under_golden_uses_the_real_shared_folder(self) -> None:
        self.assertEqual(shared_folder(SHARED.parent / "spike"), SHARED)

    def test_a_temporary_folder_uses_the_neighbour_shared_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(shared_folder(Path(folder) / "one"), Path(folder) / "_shared")

    def test_shared_files_keeps_only_files_that_2_or_more_renders_write_equal(self) -> None:
        renders = [{"a": b"1", "b": b"1", "c": b"1"}, {"a": b"1", "b": b"2", "d": b"1"},
                   {"a": b"1"}]
        self.assertEqual(shared_files(renders), {"a": b"1"})
        self.assertEqual(shared_files([{"a": b"1"}]), {})


class WriteTreeTest(unittest.TestCase):
    def test_write_tree_deletes_stale_files_and_empty_folders(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tree = Path(folder) / "t"
            write_tree(tree, {"a.txt": b"a", "x/y/b.txt": b"b"})
            write_tree(tree, {"a.txt": b"a"})
            self.assertEqual(tree_files(tree), {"a.txt": b"a"})
            self.assertFalse((tree / "x").exists())

    def test_write_tree_does_not_write_an_equal_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tree = Path(folder) / "t"
            write_tree(tree, {"a.txt": b"a"})
            with mock.patch.object(Path, "write_bytes") as write:
                write_tree(tree, {"a.txt": b"a"})
            write.assert_not_called()


class UpdateTest(unittest.TestCase):
    def test_update_splits_the_files_and_a_second_compare_passes(self) -> None:
        one = {"same": b"1", "differs": b"1", "only-one": b"1"}
        two = {"same": b"1", "differs": b"2"}
        with tempfile.TemporaryDirectory() as folder:
            golden = Path(folder) / "golden" / "one"
            renders = {golden: one, Path(folder) / "golden" / "two": two}
            write_tree(golden, {"old.txt": b"stale"})
            with mock.patch.object(helpers, "golden_renders", return_value=renders):
                update_golden(golden, one)
            self.assertEqual(tree_files(golden.parent / "_shared"), {"same": b"1"})
            self.assertEqual(tree_files(golden), {"differs": b"1", "only-one": b"1"})
            self.assertEqual(golden_differences(golden, one), [])


class RealFixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        if updating():
            self.skipTest("the fixtures are being rewritten")

    def test_shared_holds_exactly_the_8_files_that_each_render_writes_equal(self) -> None:
        self.assertEqual(set(tree_files(SHARED)), SHARED_PATHS)

    def test_shared_is_the_set_of_files_that_2_or_more_golden_tests_render_equal(self) -> None:
        self.assertEqual(tree_files(SHARED), shared_files(golden_renders().values()))

    def test_each_golden_folder_matches_the_helper_render(self) -> None:
        for golden, files in golden_renders().items():
            with self.subTest(golden=golden.name):
                self.assertEqual(golden_differences(golden, files), [])
                self.assertFalse(SHARED_PATHS & set(tree_files(golden)))


if __name__ == "__main__":
    unittest.main()
