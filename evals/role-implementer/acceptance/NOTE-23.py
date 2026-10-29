"""Hidden acceptance test of NOTE-23. grade.py copies it into a copy of the workspace."""
import unittest

from src.notes import Notes


class StripTest(unittest.TestCase):
    def test_add_removes_the_spaces_at_the_start_and_end(self) -> None:
        notes = Notes()
        notes.add("  a b  ")
        self.assertEqual(notes.list(), ["1. a b"])
