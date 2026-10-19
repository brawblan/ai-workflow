import unittest

from src.stats import median

EXPECTED = 2


class MedianTest(unittest.TestCase):
    def test_odd(self):
        self.assertEqual(median([3, 1, 2]), EXPECTED)
