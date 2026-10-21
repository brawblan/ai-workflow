"""Tests for K18, the personas file check. Each test builds a small repo in a temp folder."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from stone import cli, personas_check

PERSONAS = "constitution/personas.md"
PLANS = "docs/plans"
FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"

JOB1 = "shopper.J1: When I find an item, I want to put it in my cart, so that I buy all items at once."
JOB2 = "shopper.J2: When I am not sure, I want to keep it out of my order, so that I decide later."
JOB3 = "shopper.J3: When I check out, I want to see the total, so that I know what I pay."
JOB4 = "shopper.J4: When I get my order, I want to get a receipt, so that I can check each item."
JOB5 = "shopper.J5: When I pay, I want to see a receipt, so that I keep a record."
JOB6 = "shopper.J6: When I leave, I want to save my cart, so that I come back later."


def persona(pid: str = "shopper", jobs: tuple[str, ...] = (JOB1, JOB2, JOB3, JOB4),
            who: str = "A person who buys pens on the shop site.") -> str:
    job_lines = "".join(f"  - {job}\n" for job in jobs)
    return (f"## {pid.title()}\n\n- id: {pid}\n- who: {who}\n- jobs:\n{job_lines}"
            "- limits:\n  - device: phone or laptop\n  - skill: no technical knowledge\n"
            "  - access: own account only\n- evidence: assumed\n")


class PersonasCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self) -> None:
        self.folder.cleanup()

    # Helpers

    def write(self, path: str, text: str) -> Path:
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")
        return full

    def personas(self, *sections: str) -> None:
        self.write(PERSONAS, "# Personas\n\n" + "\n".join(sections))

    def plan(self, name: str, text: str, folder: str = PLANS) -> None:
        self.write(f"{folder}/{name}.md", text)

    def k18(self) -> list:
        return personas_check.run(self.root)

    def run_stone_check(self) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["check", "--root", str(self.root), "--framework", str(FRAMEWORK)])
        return code, out.getvalue()

    def assert_one_error(self, findings: list, fragment: str) -> None:
        self.assertEqual(len(findings), 1, findings)
        finding = findings[0]
        self.assertEqual(finding.check, "K18")
        self.assertEqual(finding.severity, "error")
        self.assertIn(fragment, finding.message)

    # A valid file

    def test_k18_valid_personas_file_gives_no_finding(self) -> None:
        self.personas(persona())
        self.assertEqual(self.k18(), [])

    def test_k18_valid_file_with_two_personas_gives_no_finding(self) -> None:
        admin_jobs = tuple(f"admin.J{n}: When I act {n}, I want to do it, so that it is done."
                           for n in (1, 2, 3))
        self.personas(persona(), persona("admin", admin_jobs))
        self.assertEqual(self.k18(), [])

    def test_k18_valid_file_with_three_or_five_job_stories_gives_no_finding(self) -> None:
        for jobs in ((JOB1, JOB2, JOB3), (JOB1, JOB2, JOB3, JOB4, JOB5)):
            with self.subTest(count=len(jobs)):
                self.personas(persona(jobs=jobs))
                self.assertEqual(self.k18(), [])

    def test_k18_no_personas_file_and_no_plan_gives_no_finding(self) -> None:
        self.assertEqual(self.k18(), [])

    # Job story rules

    def test_k18_bad_job_story_form_is_an_error(self) -> None:
        bad = "shopper.J2: I want to keep it out of my order."
        self.personas(persona(jobs=(JOB1, bad, JOB3, JOB4)))
        findings = self.k18()
        self.assert_one_error(findings, "does not have the form")
        self.assertEqual(findings[0].path, PERSONAS)
        self.assertGreater(findings[0].line, 1)

    def test_k18_job_story_with_no_id_is_an_error(self) -> None:
        bad = "When I pay, I want to see a receipt, so that I keep a record."
        self.personas(persona(jobs=(JOB1, JOB2, JOB3, bad)))
        self.assert_one_error(self.k18(), "does not have the form")

    def test_k18_wrong_job_story_id_prefix_is_an_error(self) -> None:
        wrong = JOB2.replace("shopper.J2", "buyer.J2")
        self.personas(persona(jobs=(JOB1, wrong, JOB3, JOB4)))
        self.assert_one_error(self.k18(), "buyer.J2")

    def test_k18_job_story_id_without_a_number_is_an_error(self) -> None:
        wrong = JOB2.replace("shopper.J2", "shopper.Jx")
        self.personas(persona(jobs=(JOB1, wrong, JOB3, JOB4)))
        self.assert_one_error(self.k18(), "shopper.Jx")

    def test_k18_duplicate_job_story_id_is_an_error(self) -> None:
        duplicate = JOB2.replace("shopper.J2", "shopper.J1")
        self.personas(persona(jobs=(JOB1, duplicate, JOB3, JOB4)))
        self.assert_one_error(self.k18(), "used two times")

    def test_k18_job_story_ids_are_not_reused_in_a_second_persona(self) -> None:
        # A second persona with the same id gives a duplicate persona id error.
        self.personas(persona(), persona())
        findings = self.k18()
        self.assertTrue(findings)
        for finding in findings:
            self.assertEqual(finding.check, "K18")
            self.assertEqual(finding.severity, "error")
        self.assertTrue(any("used two times" in f.message for f in findings), findings)

    def test_k18_persona_with_too_few_job_stories_is_an_error(self) -> None:
        self.personas(persona(jobs=(JOB1, JOB2)))
        self.assert_one_error(self.k18(), "has 2 job stories")

    def test_k18_persona_with_no_job_story_is_an_error(self) -> None:
        self.personas(persona(jobs=()))
        self.assert_one_error(self.k18(), "has 0 job stories")

    def test_k18_persona_with_too_many_job_stories_is_an_error(self) -> None:
        self.personas(persona(jobs=(JOB1, JOB2, JOB3, JOB4, JOB5, JOB6)))
        self.assert_one_error(self.k18(), "has 6 job stories")

    # Other persona rules

    def test_k18_missing_field_is_an_error(self) -> None:
        text = persona().replace("- evidence: assumed\n", "")
        self.personas(text)
        self.assert_one_error(self.k18(), "no evidence")

    def test_k18_file_with_no_persona_is_an_error(self) -> None:
        self.write(PERSONAS, "# Personas\n")
        self.assert_one_error(self.k18(), "no persona")

    # Plans

    def test_k18_plan_with_a_known_persona_and_job_story_gives_no_finding(self) -> None:
        self.personas(persona())
        self.plan("SHOP-3", "Personas: shopper\n\n"
                            "Job story: shopper.J1\n")
        self.assertEqual(self.k18(), [])

    def test_k18_plan_with_an_unknown_persona_id_is_an_error(self) -> None:
        self.personas(persona())
        self.plan("SHOP-3", "Personas: ghost\n")
        findings = self.k18()
        self.assert_one_error(findings, "ghost")
        self.assertEqual(findings[0].path, f"{PLANS}/SHOP-3.md")
        self.assertEqual(findings[0].line, 1)

    def test_k18_plan_with_one_unknown_persona_in_a_list_is_an_error(self) -> None:
        self.personas(persona())
        self.plan("SHOP-3", "Personas: shopper, ghost\n")
        self.assert_one_error(self.k18(), "ghost")

    def test_k18_plan_with_an_unknown_job_story_id_is_an_error(self) -> None:
        self.personas(persona())
        self.plan("SHOP-3", "Personas: shopper\n\nThis serves shopper.J9.\n")
        findings = self.k18()
        self.assert_one_error(findings, "shopper.J9")
        self.assertEqual(findings[0].line, 3)

    def test_k18_plan_with_a_job_story_of_an_unknown_persona_is_an_error(self) -> None:
        self.personas(persona())
        self.plan("SHOP-3", "Personas: shopper\n\nThis serves ghost.J1.\n")
        self.assert_one_error(self.k18(), "ghost.J1")

    def test_k18_plan_reference_in_a_code_block_is_not_tested(self) -> None:
        self.personas(persona())
        self.plan("SHOP-3", "Personas: shopper\n\n```\nPersonas: ghost\nghost.J1\n```\n")
        self.assertEqual(self.k18(), [])

    def test_k18_plan_names_a_persona_but_the_personas_file_is_missing(self) -> None:
        self.plan("SHOP-3", "Personas: shopper\n")
        self.assert_one_error(self.k18(), "does not exist")

    def test_k18_plans_folder_comes_from_config_paths_plans(self) -> None:
        self.write(".cornerstone/config.yaml", "paths:\n  plans: work/plans/\n")
        self.personas(persona())
        self.plan("T-1", "Personas: ghost\n", folder="work/plans")
        self.plan("T-2", "Personas: ghost\n", folder=PLANS)
        findings = self.k18()
        self.assert_one_error(findings, "ghost")
        self.assertEqual(findings[0].path, "work/plans/T-1.md")

    # stone check

    def test_k18_stone_check_returns_1_and_prints_an_error_for_a_bad_job_story(self) -> None:
        self.personas(persona())
        clean_code, clean_output = self.run_stone_check()
        self.assertNotIn("K18", clean_output)
        self.assertEqual(clean_code, 0, clean_output)
        self.personas(persona(jobs=(JOB1, JOB2)))
        code, output = self.run_stone_check()
        self.assertEqual(code, 1, output)
        self.assertIn(f"{PERSONAS}:", output)
        self.assertIn("error: K18:", output)
        self.assertNotIn("warning: K18:", output)

    def test_k18_stone_check_returns_1_for_an_unknown_persona_in_a_plan(self) -> None:
        self.personas(persona())
        self.plan("SHOP-3", "Personas: ghost\n")
        code, output = self.run_stone_check()
        self.assertEqual(code, 1, output)
        self.assertIn(f"{PLANS}/SHOP-3.md:1: error: K18:", output)


if __name__ == "__main__":
    unittest.main()
