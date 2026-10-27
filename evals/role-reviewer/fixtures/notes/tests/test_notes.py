import unittest

from src.notes import Notes


class NotesTest(unittest.TestCase):
    def test_add_returns_the_number(self) -> None:
        notes = Notes()
        self.assertEqual(notes.add("a"), 1)
        self.assertEqual(notes.add("b"), 2)

    def test_list_numbers_each_note(self) -> None:
        notes = Notes()
        notes.add("a")
        notes.add("b")
        self.assertEqual(notes.list(), ["1. a", "2. b"])
