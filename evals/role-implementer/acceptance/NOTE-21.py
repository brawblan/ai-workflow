"""Hidden acceptance test of NOTE-21. grade.py copies it into a copy of the workspace."""
import unittest

from src.notes import Notes


class DeleteTest(unittest.TestCase):
    def notes(self) -> Notes:
        notes = Notes()
        for text in ("a", "b", "c"):
            notes.add(text)
        return notes

    def test_delete_removes_the_note_with_that_number(self) -> None:
        notes = self.notes()
        notes.delete(1)
        self.assertEqual(notes.list(), ["1. b", "2. c"])
        notes.delete(2)
        self.assertEqual(notes.list(), ["1. b"])

    def test_a_number_with_no_note_raises(self) -> None:
        for number in (0, -1, 4):
            with self.subTest(number=number), self.assertRaises(IndexError):
                self.notes().delete(number)
