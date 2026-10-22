"""Golden test for job stories in K17 and K18 (#125).

K18 requires the form "<id>.J<n>: When I ..., I want to ..., so that ...". K17 must not count the
job story ID as words. Thus a valid job story of 25 words after the ID passes both checks. The test
writes a personas file in the form of constitution/personas.md into a temporary repo. It uses the
real writing rules from the ste-writing skill.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stone import personas_check
from stone.writing_check import check_text, load_rules

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / "plugins" / "workflow" / "skills" / "ste-writing" / "references" / "ste.md"
PERSONAS = "constitution/personas.md"

# 25 words after the ID. The test counts them with str.split(), not with the code under test.
STORY_25 = ("When I read a long page with my screen reader, I want to skip to the next heading, "
            "so that I find my part fast.")
# 26 words after the ID: the same story with one more word.
STORY_26 = ("When I read a long page with my screen reader, I want to skip to the next heading, "
            "so that I find my own part fast.")
JOB2 = "When I start a test, I want to hear the time limit, so that I plan my work."
JOB3 = "When I send a form, I want to hear the result, so that I know it arrived."


def personas_file(pid: str, first_job: str, first_number: int = 1) -> str:
    """Return a personas file in the form of the constitution/personas.md template."""
    jobs = [(first_number, first_job), (first_number + 1, JOB2), (first_number + 2, JOB3)]
    job_lines = "".join(f"  - {pid}.J{number}: {job}\n" for number, job in jobs)
    return ("# Personas\n\n"
            f"## {pid.replace('-', ' ').title()}\n\n"
            f"- id: {pid}\n"
            "- who: A student who uses a screen reader for each class.\n"
            f"- jobs:\n{job_lines}"
            "- limits:\n"
            "  - device: laptop with a screen reader\n"
            "  - skill: no technical knowledge\n"
            "  - access: own account only\n"
            "- evidence: assumed\n")


class GoldenJobStoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.rules = load_rules(RULES, None)

    def tearDown(self) -> None:
        self.folder.cleanup()

    # Helpers

    def write_personas(self, text: str) -> Path:
        path = self.root / PERSONAS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def k17(self, text: str) -> list[str]:
        return [f"{f.line}|{f.message}" for f in check_text(PERSONAS, text, self.rules)]

    def k17_rule8(self, text: str) -> list[str]:
        return [item for item in self.k17(text) if "Rule 8:" in item]

    def k18(self, path: Path) -> list[str]:
        findings, _, _ = personas_check.check_file(path, PERSONAS)
        return [f"{f.line}|{f.message}" for f in findings]

    # Fixture guards: the word counts do not depend on the code under test.

    def test_fixture_story_25_has_25_words(self) -> None:
        self.assertEqual(len(STORY_25.split()), 25)

    def test_fixture_story_26_has_26_words(self) -> None:
        self.assertEqual(len(STORY_26.split()), 26)

    # Golden: a valid 25-word job story passes K17 and K18.

    def test_golden_25_word_story_passes_k17_with_no_findings(self) -> None:
        path = self.write_personas(personas_file("reader", STORY_25))
        self.assertEqual(self.k17(path.read_text(encoding="utf-8")), [])

    def test_golden_25_word_story_passes_k18_with_no_findings(self) -> None:
        path = self.write_personas(personas_file("reader", STORY_25))
        self.assertEqual(self.k18(path), [])

    # The description limit still applies to the words after the ID.

    def test_26_word_story_fails_rule_8(self) -> None:
        path = self.write_personas(personas_file("reader", STORY_26))
        findings = self.k17_rule8(path.read_text(encoding="utf-8"))
        self.assertEqual(len(findings), 1, findings)
        self.assertTrue(findings[0].startswith("8|"), findings)  # the line of reader.J1

    def test_26_word_story_still_passes_k18(self) -> None:
        # K18 tests the form, not the length. Only K17 reports the long sentence.
        path = self.write_personas(personas_file("reader", STORY_26))
        self.assertEqual(self.k18(path), [])

    # The ID can have hyphens and a number of more than one digit.

    def test_id_with_two_hyphen_parts_is_not_counted(self) -> None:
        path = self.write_personas(personas_file("assistive-student", STORY_25))
        self.assertEqual(self.k17(path.read_text(encoding="utf-8")), [])
        self.assertEqual(self.k18(path), [])

    def test_id_with_two_hyphen_parts_and_26_words_fails_rule_8(self) -> None:
        path = self.write_personas(personas_file("assistive-student", STORY_26))
        self.assertEqual(len(self.k17_rule8(path.read_text(encoding="utf-8"))), 1)

    def test_id_with_a_two_digit_job_number_is_not_counted(self) -> None:
        path = self.write_personas(personas_file("reader", STORY_25, first_number=10))
        self.assertEqual(self.k17(path.read_text(encoding="utf-8")), [])
        self.assertEqual(self.k18(path), [])

    # Only an ID at the start of the sentence is a name. In other positions, it is counted.

    def test_id_not_at_sentence_start_is_counted(self) -> None:
        # 25 words without the ID. The ID in the middle makes the sentence too long.
        sentence = ("When I read a long page with my screen reader, as in reader.J1: I want to skip "
                    "to the next heading, so that I find it.")
        self.assertEqual(len(sentence.replace("reader.J1:", "").split()), 25)
        self.assertEqual(len(self.k17_rule8(f"{sentence}\n")), 1)

    def test_id_not_at_sentence_start_in_a_list_item_is_counted(self) -> None:
        text = f"- See reader.J1: {STORY_25}\n"
        self.assertEqual(len(self.k17_rule8(text)), 1)


if __name__ == "__main__":
    unittest.main()
