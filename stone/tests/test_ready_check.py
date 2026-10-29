"""Tests for K21 (stone check-ready, D82)."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from stone.cli import main
from stone.ready_check import PROFILE_FIELDS, check_text, find_profile

FIELD_VALUES = {
    "Problem": "Users cannot log in.",
    "Acceptance criteria": "Login works.",
    "Non-goals": "No SSO.",
    "Test oracle": "Unit test passes.",
    "Reproduction": "Open the page and click login.",
    "Time box": "2 hours",
    "Personas": "Maintainer",
}

EXPECTED = {
    "single-ticket": ["Problem", "Acceptance criteria", "Non-goals", "Test oracle", "Personas"],
    "app-slice": ["Problem", "Acceptance criteria", "Non-goals", "Test oracle", "Personas"],
    "debugging": ["Problem", "Reproduction", "Personas"],
    "spike": ["Problem", "Acceptance criteria", "Non-goals", "Test oracle", "Time box"],
    "code-audit": ["Problem", "Time box"],
    "bug-triage": ["Problem", "Reproduction"],
    "full-project": ["Problem"],
}


def ticket(profile: str, **override: str | None) -> str:
    """Return a complete ticket for the profile. A None value drops the field."""
    names = [f.name for f in PROFILE_FIELDS[profile]]
    lines = ["## Definition of Ready", ""]
    for name in names:
        value = override.get(name.replace(" ", "_").replace("-", "_"), FIELD_VALUES[name])
        if value is not None:
            lines.append(f"{name}: {value}")
    return "\n".join(lines) + "\n"


def messages(text: str, profile: str = "single-ticket") -> list[str]:
    return [f.message for f in check_text(text, "t.md", profile)]


class CliRun:
    def __init__(self, argv: list[str], stdin: str | None = None) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            if stdin is None:
                self.code = main(argv)
            else:
                with mock.patch("sys.stdin", io.StringIO(stdin)):
                    self.code = main(argv)
        self.output = out.getvalue()
        self.lines = self.output.splitlines()


class FileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.root = Path(self._folder.name)

    def tearDown(self) -> None:
        self._folder.cleanup()

    def write(self, text: str, name: str = "ticket.md") -> str:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def run_cli(self, *args: str, stdin: str | None = None) -> CliRun:
        return CliRun(["check-ready", *args], stdin)


class ProfileFieldsTest(unittest.TestCase):
    def test_d82_profile_table_lists_exactly_the_expected_fields(self) -> None:
        for profile, names in EXPECTED.items():
            with self.subTest(profile=profile):
                self.assertEqual([f.name for f in PROFILE_FIELDS[profile]], names)

    def test_d82_complete_ticket_passes_for_each_profile(self) -> None:
        for profile in PROFILE_FIELDS:
            with self.subTest(profile=profile):
                self.assertEqual(check_text(ticket(profile), "t.md", profile), [])

    def test_d82_each_missing_field_gives_a_finding_at_line_1(self) -> None:
        for profile in EXPECTED:
            for field in PROFILE_FIELDS[profile]:
                with self.subTest(profile=profile, field=field.name):
                    key = field.name.replace(" ", "_").replace("-", "_")
                    found = check_text(ticket(profile, **{key: None}), "t.md", profile)
                    self.assertEqual(len(found), 1)
                    self.assertEqual(found[0].line, 1)
                    self.assertEqual(found[0].check, "K21")
                    self.assertIn(f"no '{field.name}' field", found[0].message)

    def test_d82_debugging_does_not_need_acceptance_criteria(self) -> None:
        self.assertEqual(check_text(ticket("debugging"), "t.md", "debugging"), [])
        self.assertNotIn("Acceptance criteria", " ".join(messages(ticket("debugging"), "debugging")))

    def test_d82_extra_fields_for_other_profiles_are_not_required(self) -> None:
        self.assertEqual(check_text("Problem: x\n", "t.md", "full-project"), [])

    def test_d82_empty_text_reports_every_field(self) -> None:
        self.assertEqual(len(check_text("", "t.md", "single-ticket")), 5)


class EmptyValueTest(unittest.TestCase):
    def test_d82_empty_or_vague_values_give_a_finding_at_the_field_line(self) -> None:
        for value in ["", "TBD", "TODO", "N/A", "?", "<describe the problem>", "none", "...",
                      "<!-- fill in -->"]:
            with self.subTest(value=value):
                text = ticket("single-ticket", Problem=value)
                found = check_text(text, "t.md", "single-ticket")
                self.assertEqual(len(found), 1)
                self.assertIn("empty or vague", found[0].message)
                self.assertIn("'Problem'", found[0].message)
                self.assertEqual(found[0].line, 3)

    def test_d82_none_is_vague_for_non_personas_fields(self) -> None:
        text = ticket("single-ticket", Non_goals="none")
        self.assertEqual(len(check_text(text, "t.md", "single-ticket")), 1)

    def test_d82_text_that_starts_with_a_placeholder_word_is_content(self) -> None:
        text = ticket("single-ticket", Problem="None of the users can log in.")
        self.assertEqual(check_text(text, "t.md", "single-ticket"), [])

    def test_d82_personas_none_passes_for_single_ticket_and_debugging(self) -> None:
        for profile in ["single-ticket", "debugging"]:
            with self.subTest(profile=profile):
                self.assertEqual(
                    check_text(ticket(profile, Personas="none"), "t.md", profile), [])

    def test_d82_personas_none_fails_for_app_slice(self) -> None:
        found = check_text(ticket("app-slice", Personas="none"), "t.md", "app-slice")
        self.assertEqual(len(found), 1)
        self.assertIn("'Personas' field is empty or vague", found[0].message)

    def test_d82_personas_placeholder_fails_even_where_none_passes(self) -> None:
        found = check_text(ticket("single-ticket", Personas="TBD"), "t.md", "single-ticket")
        self.assertEqual(len(found), 1)


class FormTest(unittest.TestCase):
    def test_d82_multi_line_value_counts_as_filled(self) -> None:
        text = ("## Definition of Ready\n"
                "Problem: Users cannot log in.\n"
                "Acceptance criteria:\n- item one\n- item two\n"
                "Non-goals: No SSO.\nTest oracle: Unit test.\nPersonas: none\n")
        self.assertEqual(check_text(text, "t.md", "single-ticket"), [])

    def test_d82_label_with_only_a_blank_line_after_it_is_empty(self) -> None:
        text = ticket("full-project", Problem="") + "\n"
        self.assertEqual(len(check_text(text, "t.md", "full-project")), 1)

    def test_d82_bullet_and_bold_labels_count(self) -> None:
        text = "## Definition of Ready\n- **Problem**: Users cannot log in.\n"
        self.assertEqual(check_text(text, "t.md", "full-project"), [])
        text = "## Definition of Ready\n**Problem:** Users cannot log in.\n"
        self.assertEqual(check_text(text, "t.md", "full-project"), [])

    def test_d82_label_ignores_case(self) -> None:
        text = "## Definition of Ready\nPROBLEM: Users cannot log in.\n"
        self.assertEqual(check_text(text, "t.md", "full-project"), [])

    def test_d82_heading_form_counts(self) -> None:
        text = "## Acceptance criteria\n\n- It works.\n"
        found = check_text(text, "t.md", "single-ticket")
        self.assertNotIn("Acceptance criteria", " ".join(f.message for f in found))

    def test_d82_heading_form_passes_a_full_ticket(self) -> None:
        text = ("## Problem\nUsers cannot log in.\n\n## Acceptance criteria\nIt works.\n\n"
                "## Non-goals\nNo SSO.\n\n## Test oracle\nUnit test.\n\n## Personas\nnone\n")
        self.assertEqual(check_text(text, "t.md", "single-ticket"), [])

    def test_d82_why_this_change_heading_counts_as_problem(self) -> None:
        text = "## Why this change\n\nUsers cannot log in.\n"
        self.assertEqual(check_text(text, "t.md", "full-project"), [])

    def test_d82_empty_heading_section_is_empty(self) -> None:
        text = "## Why this change\n\n## Acceptance criteria\nIt works.\n"
        found = check_text(text, "t.md", "full-project")
        self.assertEqual(len(found), 1)
        self.assertIn("empty or vague", found[0].message)
        self.assertEqual(found[0].line, 1)

    def test_d82_empty_heading_section_with_placeholder_is_empty(self) -> None:
        text = "## Problem\n\nTBD\n"
        found = check_text(text, "t.md", "full-project")
        self.assertIn("empty or vague", found[0].message)

    def test_d82_goal_heading_counts_as_problem(self) -> None:
        self.assertEqual(check_text("## Goal\nShip it.\n", "t.md", "full-project"), [])

    def test_d82_field_lines_in_a_fenced_block_do_not_count(self) -> None:
        text = "## Definition of Ready\n\n```\nProblem: Users cannot log in.\n```\n"
        found = check_text(text, "t.md", "full-project")
        self.assertEqual(len(found), 1)
        self.assertIn("no 'Problem' field", found[0].message)

    def test_d82_field_lines_in_a_fenced_block_without_a_section_do_not_count(self) -> None:
        text = "Intro\n\n~~~\nProblem: Users cannot log in.\n~~~\n"
        found = check_text(text, "t.md", "full-project")
        self.assertIn("no 'Problem' field", found[0].message)

    def test_d82_field_after_a_closed_fence_counts(self) -> None:
        text = "## Definition of Ready\n```\nx\n```\nProblem: Real problem.\n"
        self.assertEqual(check_text(text, "t.md", "full-project"), [])


class SectionScopeTest(unittest.TestCase):
    def test_d82_field_line_outside_the_section_does_not_count(self) -> None:
        text = "Problem: Users cannot log in.\n\n## Definition of Ready\n\nAcceptance criteria: x\n"
        found = check_text(text, "t.md", "full-project")
        self.assertEqual(len(found), 1)
        self.assertIn("no 'Problem' field", found[0].message)

    def test_d82_field_line_after_the_section_does_not_count(self) -> None:
        text = "## Definition of Ready\n\nNon-goals: x\n\n## Notes\n\nProblem: Users.\n"
        found = check_text(text, "t.md", "full-project")
        self.assertIn("no 'Problem' field", found[0].message)

    def test_d82_heading_outside_the_section_still_supplies_a_field(self) -> None:
        text = ("## Why this change\nUsers cannot log in.\n\n"
                "## Definition of Ready\n\nNon-goals: x\n")
        self.assertEqual(check_text(text, "t.md", "full-project"), [])

    def test_d82_without_a_section_field_lines_anywhere_count(self) -> None:
        self.assertEqual(check_text("Hello\n\nProblem: Users.\n", "t.md", "full-project"), [])

    def test_d82_finding_line_is_the_line_in_the_whole_file(self) -> None:
        text = "Title\n\nMore\n\n## Definition of Ready\n\nProblem: TBD\n"
        found = check_text(text, "t.md", "full-project")
        self.assertEqual(found[0].line, 7)

    def test_d82_section_heading_name_ignores_case(self) -> None:
        text = "Problem: outside\n\n## definition of ready\n\nNon-goals: x\n"
        found = check_text(text, "t.md", "full-project")
        self.assertIn("no 'Problem' field", found[0].message)


class FindProfileTest(unittest.TestCase):
    def test_d82_find_profile_reads_the_profile_line(self) -> None:
        self.assertEqual(find_profile("Title\nProfile: Spike\n"), "spike")

    def test_d82_find_profile_returns_none_without_a_line(self) -> None:
        self.assertIsNone(find_profile("Nothing here\n"))

    def test_d82_find_profile_uses_the_first_line(self) -> None:
        self.assertEqual(find_profile("Profile: spike\nProfile: debugging\n"), "spike")


class CliTest(FileTestCase):
    def test_d82_profile_flag_wins_over_the_profile_line(self) -> None:
        text = "Profile: single-ticket\n" + ticket("full-project")
        result = self.run_cli(self.write(text), "--profile", "full-project")
        self.assertEqual(result.lines[-1], "K21: 0 finding(s), profile full-project, mode warn.")

    def test_d82_profile_line_is_used_without_a_flag(self) -> None:
        text = "Profile: full-project\n" + ticket("full-project")
        result = self.run_cli(self.write(text))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.lines[-1], "K21: 0 finding(s), profile full-project, mode warn.")

    def test_d82_no_profile_exits_2_with_a_message(self) -> None:
        result = self.run_cli(self.write(ticket("full-project")))
        self.assertEqual(result.code, 2)
        self.assertIn("no known profile", result.output)
        self.assertIn("--profile", result.output)

    def test_d82_unknown_profile_line_exits_2(self) -> None:
        result = self.run_cli(self.write("Profile: nonsense\nProblem: x\n"))
        self.assertEqual(result.code, 2)
        self.assertIn("nonsense", result.output)

    def test_d82_unknown_profile_flag_is_a_usage_error(self) -> None:
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(["check-ready", self.write("x"), "--profile", "nonsense"])
        self.assertEqual(raised.exception.code, 2)

    def test_d82_unreadable_file_exits_2(self) -> None:
        result = self.run_cli(str(self.root / "missing.md"), "--profile", "full-project")
        self.assertEqual(result.code, 2)
        self.assertIn("cannot read", result.output)

    def test_d82_stdin_dash_works(self) -> None:
        result = self.run_cli("-", "--profile", "full-project", stdin=ticket("full-project"))
        self.assertEqual(result.code, 0)
        self.assertEqual(result.lines, ["K21: 0 finding(s), profile full-project, mode warn."])

    def test_d82_stdin_reads_the_profile_line(self) -> None:
        result = self.run_cli("-", stdin="Profile: full-project\nProblem: x\n")
        self.assertEqual(result.code, 0)

    def test_d82_stdin_findings_use_path_stdin(self) -> None:
        result = self.run_cli("-", "--profile", "full-project", stdin="Nothing.\n")
        self.assertTrue(result.lines[0].startswith("<stdin>:1"), result.lines[0])
        self.assertIn("K21", result.lines[0])

    def test_d82_file_findings_use_the_file_path(self) -> None:
        path = self.write("Nothing.\n")
        result = self.run_cli(path, "--profile", "full-project")
        self.assertTrue(result.lines[0].startswith(f"{path}:1"), result.lines[0])

    def test_d82_warn_is_the_default_and_exits_0_with_findings(self) -> None:
        result = self.run_cli(self.write("Nothing.\n"), "--profile", "single-ticket")
        self.assertEqual(result.code, 0)
        self.assertEqual(len(result.lines), 6)  # 5 findings and the summary
        self.assertEqual(result.lines[-1], "K21: 5 finding(s), profile single-ticket, mode warn.")

    def test_d82_block_mode_exits_1_with_findings(self) -> None:
        result = self.run_cli(self.write("Nothing.\n"), "--profile", "single-ticket",
                              "--mode", "block")
        self.assertEqual(result.code, 1)
        self.assertEqual(result.lines[-1], "K21: 5 finding(s), profile single-ticket, mode block.")

    def test_d82_block_mode_exits_0_without_findings(self) -> None:
        result = self.run_cli(self.write(ticket("single-ticket")), "--profile", "single-ticket",
                              "--mode", "block")
        self.assertEqual(result.code, 0)
        self.assertEqual(result.lines, ["K21: 0 finding(s), profile single-ticket, mode block."])

    def test_d82_github_format_in_warn_mode_prints_warning(self) -> None:
        path = self.write(ticket("full-project", Problem="TBD"))
        result = self.run_cli(path, "--profile", "full-project", "--format", "github")
        self.assertEqual(result.code, 0)
        annotations = [l for l in result.lines if l.startswith("::")]
        self.assertEqual(len(annotations), 1)
        self.assertTrue(annotations[0].startswith(f"::warning file={path},line=3"), annotations[0])
        self.assertNotIn("::error", result.output)

    def test_d82_github_format_in_block_mode_prints_error(self) -> None:
        path = self.write(ticket("full-project", Problem="TBD"))
        result = self.run_cli(path, "--profile", "full-project", "--format", "github",
                              "--mode", "block")
        self.assertEqual(result.code, 1)
        self.assertTrue(result.lines[0].startswith("::error"), result.lines[0])

    def test_d82_summary_is_the_last_line_with_github_format(self) -> None:
        result = self.run_cli(self.write("Nothing.\n"), "--profile", "code-audit",
                              "--format", "github")
        self.assertEqual(result.lines[-1], "K21: 2 finding(s), profile code-audit, mode warn.")

    def test_d82_unknown_mode_is_a_usage_error(self) -> None:
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(["check-ready", self.write("x"), "--mode", "fail"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
