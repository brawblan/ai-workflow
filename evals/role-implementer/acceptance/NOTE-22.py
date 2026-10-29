"""Hidden acceptance test of NOTE-22. grade.py copies it into a copy of the workspace."""
import unittest

from src.notes import Notes


class LastTest(unittest.TestCase):
    def test_last_is_none_with_no_notes(self) -> None:
        self.assertIsNone(Notes().last())

    def test_last_returns_the_newest_text(self) -> None:
        notes = Notes()
        notes.add("a")
        notes.add("b")
        self.assertEqual(notes.last(), "b")
