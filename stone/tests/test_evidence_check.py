"""Tests for K14 (stone check-evidence). Each class tests one acceptance criterion (AC1 to AC8)."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from stone.cli import main
from stone.evidence_check import DEFAULT_SECTIONS, check_text

FULL_BODY = """## Summary

Adds K14.

## Evidence

Unit tests pass: 40 of 40.

## Decision log

D20: K14 is a stone command.

## Review findings

No blocking findings.

## Confidence

High. The tests cover each criterion.
"""


def body_with(**replace: str) -> str:
    """Return FULL_BODY with the content of the named sections replaced.

    Keys: evidence, decision, review, confidence.
    """
    parts = {
        "evidence": "Unit tests pass: 40 of 40.",
        "decision": "D20: K14 is a stone command.",
        "review": "No blocking findings.",
        "confidence": "High. The tests cover each criterion.",
    }
    parts.update(replace)
    return (
        "## Summary\n\nAdds K14.\n\n"
        f"## Evidence\n\n{parts['evidence']}\n\n"
        f"## Decision log\n\n{parts['decision']}\n\n"
        f"## Review findings\n\n{parts['review']}\n\n"
        f"## Confidence\n\n{parts['confidence']}\n"
    )


def lines_of(text: str, sections: list[str] | None = None) -> list[int]:
    return sorted(f.line for f in check_text(text, "pr.md", sections))


def section_names(text: str, sections: list[str] | None = None) -> list[str]:
    """Return the section name quoted in each finding message."""
    return sorted(f.message.split("'")[1] for f in check_text(text, "pr.md", sections))


class CliRun:
    """Run `stone check-evidence` through stone.cli.main and capture stdout."""

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

    def write(self, text: str, name: str = "body.md") -> str:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def run_cli(self, *args: str, stdin: str | None = None) -> CliRun:
        return CliRun(["check-evidence", *args], stdin)


class AC1InputTest(FileTestCase):
    """AC1: read the body from a file or from stdin ('-'); an unreadable file gives exit code 2."""

    def test_ac1_reads_body_from_a_file(self) -> None:
        path = self.write(body_with(evidence="TODO"))
        result = self.run_cli(path)
        self.assertEqual(result.code, 0)
        self.assertEqual(len([l for l in result.lines if l.startswith(f"{path}:")]), 1)

    def test_ac1_full_body_from_a_file_has_no_findings(self) -> None:
        result = self.run_cli(self.write(FULL_BODY), "--mode", "block")
        self.assertEqual(result.code, 0)
        self.assertEqual(result.lines, ["K14: 0 finding(s), mode block."])

    def test_ac1_dash_reads_standard_input(self) -> None:
        result = self.run_cli("-", "--mode", "block", stdin=FULL_BODY)
        self.assertEqual(result.code, 0)
        result = self.run_cli("-", "--mode", "block", stdin=body_with(confidence=""))
        self.assertEqual(result.code, 1)

    def test_ac1_stdin_findings_use_path_stdin(self) -> None:
        result = self.run_cli("-", stdin="No sections here.\n")
        findings = result.lines[:-1]
        self.assertEqual(len(findings), 4)
        for line in findings:
            self.assertTrue(line.startswith("<stdin>:1:"), line)

    def test_ac1_missing_file_gives_exit_code_2(self) -> None:
        result = self.run_cli(str(self.root / "no-such-file.md"))
        self.assertEqual(result.code, 2)

    def test_ac1_missing_file_gives_exit_code_2_in_block_mode(self) -> None:
        result = self.run_cli(str(self.root / "no-such-file.md"), "--mode", "block")
        self.assertEqual(result.code, 2)

    def test_ac1_directory_gives_exit_code_2(self) -> None:
        result = self.run_cli(str(self.root))
        self.assertEqual(result.code, 2)

    def test_ac1_file_that_is_not_utf8_gives_exit_code_2(self) -> None:
        # Edge case: a file with bytes that are not UTF-8 cannot be read as a PR body.
        path = self.root / "binary.md"
        path.write_bytes(b"## Evidence\n\xff\xfe\xfa\n")
        result = self.run_cli(str(path))
        self.assertEqual(result.code, 2)


class AC2SectionsTest(FileTestCase):
    """AC2: the default sections, and --section (repeatable) replaces the default list."""

    def test_ac2_default_sections_are_the_four_names(self) -> None:
        self.assertEqual(DEFAULT_SECTIONS, ["Evidence", "Decision log", "Review findings", "Confidence"])

    def test_ac2_body_with_no_sections_has_one_finding_per_default_section(self) -> None:
        self.assertEqual(section_names("Text only.\n"),
                         sorted(["Evidence", "Decision log", "Review findings", "Confidence"]))

    def test_ac2_each_default_section_is_required(self) -> None:
        for key, name in [("evidence", "Evidence"), ("decision", "Decision log"),
                          ("review", "Review findings"), ("confidence", "Confidence")]:
            with self.subTest(section=name):
                self.assertEqual(section_names(body_with(**{key: ""})), [name])

    def test_ac2_section_option_replaces_the_default_list(self) -> None:
        path = self.write("## Testing\n\nRan the suite.\n")
        result = self.run_cli(path, "--section", "Testing", "--mode", "block")
        self.assertEqual(result.code, 0)
        self.assertEqual(result.lines, ["K14: 0 finding(s), mode block."])

    def test_ac2_section_option_is_repeatable(self) -> None:
        path = self.write("## Testing\n\nRan the suite.\n")
        result = self.run_cli(path, "--section", "Testing", "--section", "Rollback plan",
                              "--mode", "block")
        self.assertEqual(result.code, 1)
        self.assertEqual(result.lines[-1], "K14: 1 finding(s), mode block.")
        self.assertIn("Rollback plan", result.output)
        self.assertNotIn("Evidence", result.output)

    def test_ac2_check_text_with_sections_replaces_the_default_list(self) -> None:
        self.assertEqual(section_names("## Testing\n\nRan it.\n", ["Testing"]), [])


class AC3HeadingTest(unittest.TestCase):
    """AC3: ATX headings of any level, bold-only lines, a loose name match, no headings in fences."""

    def test_ac3_atx_heading_of_each_level_is_a_heading(self) -> None:
        for level in range(1, 7):
            with self.subTest(level=level):
                text = f"{'#' * level} Evidence\n\nTests pass.\n"
                self.assertEqual(section_names(text, ["Evidence"]), [])

    def test_ac3_seven_hashes_is_not_a_heading(self) -> None:
        self.assertEqual(lines_of("####### Evidence\n\nTests pass.\n", ["Evidence"]), [1])
        self.assertIn("no 'Evidence' section",
                      check_text("####### Evidence\n\nTests pass.\n", "pr.md", ["Evidence"])[0].message)

    def test_ac3_bold_line_with_stars_is_a_heading(self) -> None:
        self.assertEqual(section_names("**Evidence**\n\nTests pass.\n", ["Evidence"]), [])

    def test_ac3_bold_line_with_underscores_is_a_heading(self) -> None:
        self.assertEqual(section_names("__Decision log__\n\nD1.\n", ["Decision log"]), [])

    def test_ac3_bold_text_in_a_sentence_is_not_a_heading(self) -> None:
        text = "**Evidence** is below.\n\nTests pass.\n"
        findings = check_text(text, "pr.md", ["Evidence"])
        self.assertEqual(len(findings), 1)
        self.assertIn("no 'Evidence' section", findings[0].message)

    def test_ac3_name_match_ignores_case(self) -> None:
        self.assertEqual(section_names("## EVIDENCE\n\nTests pass.\n", ["Evidence"]), [])
        self.assertEqual(section_names("## decision LOG\n\nD1.\n", ["Decision log"]), [])

    def test_ac3_name_match_ignores_extra_spaces(self) -> None:
        self.assertEqual(section_names("##   Decision    log   \n\nD1.\n", ["Decision log"]), [])
        self.assertEqual(section_names("**  Review   findings  **\n\nNone found.\n",
                                       ["Review findings"]), [])

    def test_ac3_name_match_ignores_a_trailing_colon(self) -> None:
        for text in ["## Evidence:\n\nTests pass.\n",
                     "**Evidence:**\n\nTests pass.\n",
                     "**Evidence**:\n\nTests pass.\n"]:
            with self.subTest(text=text):
                self.assertEqual(section_names(text, ["Evidence"]), [])

    def test_ac3_section_option_name_also_matches_loosely(self) -> None:
        self.assertEqual(section_names("## Decision log\n\nD1.\n", ["decision   LOG"]), [])

    def test_ac3_heading_in_backtick_fence_is_not_a_heading(self) -> None:
        text = "```\n## Evidence\n```\n\nTests pass.\n"
        findings = check_text(text, "pr.md", ["Evidence"])
        self.assertEqual(len(findings), 1)
        self.assertIn("no 'Evidence' section", findings[0].message)

    def test_ac3_heading_in_tilde_fence_is_not_a_heading(self) -> None:
        text = "~~~\n**Evidence**\n~~~\n\nTests pass.\n"
        findings = check_text(text, "pr.md", ["Evidence"])
        self.assertEqual(len(findings), 1)
        self.assertIn("no 'Evidence' section", findings[0].message)

    def test_ac3_heading_in_a_fence_does_not_end_a_section(self) -> None:
        text = "## Evidence\n\n```\n## Decision log\n```\n"
        self.assertEqual(section_names(text, ["Evidence", "Decision log"]), ["Decision log"])

    def test_ac3_tilde_line_in_a_backtick_fence_does_not_close_it(self) -> None:
        text = "```\n~~~\n## Evidence\n~~~\n```\n"
        findings = check_text(text, "pr.md", ["Evidence"])
        self.assertEqual(len(findings), 1)
        self.assertIn("no 'Evidence' section", findings[0].message)

    def test_ac3_heading_after_a_closed_fence_is_a_heading(self) -> None:
        text = "```\ncode\n```\n\n## Evidence\n\nTests pass.\n"
        self.assertEqual(section_names(text, ["Evidence"]), [])


class AC4FindingLocationTest(unittest.TestCase):
    """AC4: missing section on line 1, empty section on its heading line, duplicates."""

    def test_ac4_missing_section_gives_one_finding_on_line_1(self) -> None:
        text = "## Summary\n\nText.\n\n## Evidence\n\nTests pass.\n"
        findings = check_text(text, "pr.md", ["Evidence", "Confidence"])
        self.assertEqual([(f.path, f.line) for f in findings], [("pr.md", 1)])
        self.assertIn("'Confidence'", findings[0].message)

    def test_ac4_empty_section_gives_one_finding_on_its_heading_line(self) -> None:
        text = body_with(review="")
        heading_line = text.splitlines().index("## Review findings") + 1
        findings = check_text(text, "pr.md")
        self.assertEqual([f.line for f in findings], [heading_line])
        self.assertIn("'Review findings'", findings[0].message)

    def test_ac4_empty_bold_section_finding_is_on_the_bold_line(self) -> None:
        text = "Intro.\n\n**Evidence**\n\n**Confidence**\n\nHigh.\n"
        self.assertEqual(lines_of(text, ["Evidence", "Confidence"]), [3])

    def test_ac4_duplicate_heading_passes_if_one_copy_has_content(self) -> None:
        text = "## Evidence\n\nTODO\n\n## Notes\n\nx\n\n## Evidence\n\nTests pass.\n"
        self.assertEqual(check_text(text, "pr.md", ["Evidence"]), [])

    def test_ac4_duplicate_heading_passes_if_the_first_copy_has_content(self) -> None:
        text = "## Evidence\n\nTests pass.\n\n## Notes\n\nx\n\n## Evidence\n\n"
        self.assertEqual(check_text(text, "pr.md", ["Evidence"]), [])

    def test_ac4_duplicate_headings_all_empty_give_one_finding(self) -> None:
        text = "## Evidence\n\n## Notes\n\nx\n\n## Evidence\n\nTBD\n"
        findings = check_text(text, "pr.md", ["Evidence"])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line, 1)

    def test_ac4_cli_text_output_has_path_line_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pr.md"
            path.write_text(body_with(evidence=""), encoding="utf-8")
            result = CliRun(["check-evidence", str(path)])
        self.assertEqual(len(result.lines), 2)
        self.assertRegex(result.lines[0], rf"^{path}:5: \w+: K14: ")


class AC5SectionEndTest(unittest.TestCase):
    """AC5: where a section ends, and when a sub-heading is content."""

    def test_ac5_next_heading_of_same_level_ends_the_section(self) -> None:
        text = "## Evidence\n\n## Notes\n\nTests pass.\n"
        self.assertEqual(lines_of(text, ["Evidence"]), [1])

    def test_ac5_next_heading_of_higher_level_ends_the_section(self) -> None:
        text = "### Evidence\n\n## Notes\n\nTests pass.\n"
        self.assertEqual(lines_of(text, ["Evidence"]), [1])
        text = "## Evidence\n\n# Notes\n\nTests pass.\n"
        self.assertEqual(lines_of(text, ["Evidence"]), [1])

    def test_ac5_lower_level_sub_heading_with_text_is_content(self) -> None:
        text = "## Evidence\n\n### Unit tests\n\n40 of 40 pass.\n"
        self.assertEqual(check_text(text, "pr.md", ["Evidence"]), [])

    def test_ac5_lower_level_sub_heading_alone_is_content(self) -> None:
        text = "## Evidence\n\n### Unit tests\n\n## Notes\n\nx\n"
        self.assertEqual(check_text(text, "pr.md", ["Evidence"]), [])

    def test_ac5_required_sub_heading_of_lower_level_ends_the_section(self) -> None:
        text = "## Evidence\n\n### Decision log\n\nD1.\n"
        self.assertEqual(section_names(text, ["Evidence", "Decision log"]), ["Evidence"])

    def test_ac5_required_bold_heading_ends_an_atx_section(self) -> None:
        text = "## Evidence\n\n**Confidence**\n\nHigh.\n"
        self.assertEqual(section_names(text, ["Evidence", "Confidence"]), ["Evidence"])

    def test_ac5_required_atx_heading_ends_a_bold_section(self) -> None:
        text = "**Evidence**\n\n#### Confidence\n\nHigh.\n"
        self.assertEqual(section_names(text, ["Evidence", "Confidence"]), ["Evidence"])

    def test_ac5_sub_heading_that_is_not_required_with_custom_sections_is_content(self) -> None:
        # "Decision log" is a default section, but --section replaces the list.
        text = "## Evidence\n\n### Decision log\n"
        self.assertEqual(check_text(text, "pr.md", ["Evidence"]), [])

    def test_ac5_content_after_the_section_end_does_not_count(self) -> None:
        text = "## Evidence\n\n## Summary\n\nLots of text.\n"
        self.assertEqual(lines_of(text, ["Evidence"]), [1])

    def test_ac5_last_section_runs_to_the_end_of_the_body(self) -> None:
        text = "## Summary\n\nx\n\n## Evidence\n\n\n\nTests pass.\n"
        self.assertEqual(check_text(text, "pr.md", ["Evidence"]), [])


class AC6EmptySectionTest(unittest.TestCase):
    """AC6: what counts as empty, and the placeholders."""

    def assertEmpty(self, content: str) -> None:
        self.assertEqual(section_names(body_with(evidence=content)), ["Evidence"],
                         f"expected empty: {content!r}")

    def assertContent(self, content: str) -> None:
        self.assertEqual(section_names(body_with(evidence=content)), [],
                         f"expected content: {content!r}")

    def test_ac6_no_text_is_empty(self) -> None:
        self.assertEmpty("")
        self.assertEmpty("\n\n   \n\t\n")

    def test_ac6_html_comment_only_is_empty(self) -> None:
        self.assertEmpty("<!-- Paste the test output here. -->")

    def test_ac6_multiline_html_comment_is_empty(self) -> None:
        self.assertEmpty("<!--\nPaste the test output here.\nAdd the command.\n-->")

    def test_ac6_text_next_to_a_comment_is_content(self) -> None:
        self.assertContent("<!-- output --> Tests pass.")

    def test_ac6_table_header_and_separator_only_is_empty(self) -> None:
        self.assertEmpty("| Check | Result |\n| --- | --- |")

    def test_ac6_table_with_aligned_separator_only_is_empty(self) -> None:
        self.assertEmpty("| Check | Result |\n|:---|---:|")

    def test_ac6_table_header_without_outer_pipes_is_empty(self) -> None:
        # Edge case: a GFM table header row can omit the outer pipes.
        self.assertEmpty("Check | Result\n--- | ---")

    def test_ac6_table_with_a_data_row_is_content(self) -> None:
        self.assertContent("| Check | Result |\n| --- | --- |\n| unit tests | pass |")

    def test_ac6_table_row_without_a_separator_is_content(self) -> None:
        self.assertContent("| unit tests | pass |")

    def test_ac6_list_markers_only_are_empty(self) -> None:
        for content in ["- ", "* ", "+ ", "1. ", "1) ", "- \n- ", "- \n* \n+ \n1. "]:
            with self.subTest(content=content):
                self.assertEmpty(content)

    def test_ac6_list_item_with_text_is_content(self) -> None:
        self.assertContent("- Unit tests pass.")
        self.assertContent("1. Unit tests pass.")

    def test_ac6_placeholders_are_empty(self) -> None:
        for placeholder in ["TODO", "TBD", "None", "N/A", "-", "..."]:
            with self.subTest(placeholder=placeholder):
                self.assertEmpty(placeholder)

    def test_ac6_placeholders_ignore_case(self) -> None:
        for placeholder in ["todo", "Tbd", "NONE", "n/a", "none"]:
            with self.subTest(placeholder=placeholder):
                self.assertEmpty(placeholder)

    def test_ac6_placeholders_ignore_surrounding_emphasis(self) -> None:
        for placeholder in ["**TODO**", "_TBD_", "*None*", "__N/A__", "***None***"]:
            with self.subTest(placeholder=placeholder):
                self.assertEmpty(placeholder)

    def test_ac6_placeholders_ignore_a_trailing_period_or_colon(self) -> None:
        for placeholder in ["None.", "TODO:", "TBD.", "N/A:", "**None.**", "_None_."]:
            with self.subTest(placeholder=placeholder):
                self.assertEmpty(placeholder)

    def test_ac6_placeholder_as_a_list_item_is_empty(self) -> None:
        self.assertEmpty("- TODO")
        self.assertEmpty("1. None")

    def test_ac6_placeholder_after_a_comment_is_empty(self) -> None:
        self.assertEmpty("<!-- Fill this in. -->\nTBD")

    def test_ac6_none_with_a_reason_is_content(self) -> None:
        for content in ["None. The change has no design decision.",
                        "None: the change does not affect users.",
                        "None, because this is a docs-only change.",
                        "- None. No reviewer found a problem."]:
            with self.subTest(content=content):
                self.assertContent(content)

    def test_ac6_word_that_starts_with_a_placeholder_is_content(self) -> None:
        self.assertContent("Nonetheless, tests pass.")
        self.assertContent("TODO list is done.")

    def test_ac6_placeholder_rule_applies_to_each_default_section(self) -> None:
        for key, name in [("evidence", "Evidence"), ("decision", "Decision log"),
                          ("review", "Review findings"), ("confidence", "Confidence")]:
            with self.subTest(section=name):
                self.assertEqual(section_names(body_with(**{key: "N/A"})), [name])


class AC7ModeAndFormatTest(FileTestCase):
    """AC7: --mode warn exits 0, --mode block exits 1 on a finding, --format github levels."""

    def test_ac7_warn_is_the_default_and_exits_0_with_findings(self) -> None:
        result = self.run_cli(self.write("No sections.\n"))
        self.assertEqual(result.code, 0)
        self.assertEqual(len(result.lines), 5)  # 4 findings and the summary

    def test_ac7_warn_mode_prints_the_findings(self) -> None:
        result = self.run_cli(self.write(body_with(decision="TBD")), "--mode", "warn")
        self.assertEqual(result.code, 0)
        self.assertIn("K14", result.lines[0])
        self.assertIn("Decision log", result.lines[0])

    def test_ac7_block_mode_exits_1_with_a_finding(self) -> None:
        result = self.run_cli(self.write(body_with(decision="TBD")), "--mode", "block")
        self.assertEqual(result.code, 1)

    def test_ac7_block_mode_exits_0_without_a_finding(self) -> None:
        result = self.run_cli(self.write(FULL_BODY), "--mode", "block")
        self.assertEqual(result.code, 0)

    def test_ac7_github_format_in_warn_mode_prints_warning_annotations(self) -> None:
        path = self.write(body_with(evidence=""))
        result = self.run_cli(path, "--format", "github")
        self.assertEqual(result.code, 0)
        annotations = [l for l in result.lines if l.startswith("::")]
        self.assertEqual(len(annotations), 1)
        self.assertTrue(annotations[0].startswith(f"::warning file={path},line=5"), annotations[0])
        self.assertNotIn("::error", result.output)

    def test_ac7_github_format_in_block_mode_prints_error_annotations(self) -> None:
        path = self.write(body_with(evidence=""))
        result = self.run_cli(path, "--format", "github", "--mode", "block")
        self.assertEqual(result.code, 1)
        annotations = [l for l in result.lines if l.startswith("::")]
        self.assertEqual(len(annotations), 1)
        self.assertTrue(annotations[0].startswith(f"::error file={path},line=5"), annotations[0])
        self.assertNotIn("::warning", result.output)

    def test_ac7_github_format_with_stdin_uses_path_stdin(self) -> None:
        result = self.run_cli("-", "--format", "github", stdin="Nothing.\n")
        for line in result.lines[:-1]:
            self.assertTrue(line.startswith("::warning file=<stdin>,line=1"), line)

    def test_ac7_unknown_mode_is_a_usage_error(self) -> None:
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(["check-evidence", self.write(FULL_BODY), "--mode", "fail"])
        self.assertEqual(raised.exception.code, 2)


class AC8SummaryLineTest(FileTestCase):
    """AC8: the last line of output is `K14: <n> finding(s), mode <mode>.`"""

    def test_ac8_summary_with_zero_findings(self) -> None:
        result = self.run_cli(self.write(FULL_BODY))
        self.assertEqual(result.lines[-1], "K14: 0 finding(s), mode warn.")

    def test_ac8_summary_counts_the_findings_in_warn_mode(self) -> None:
        result = self.run_cli(self.write(body_with(evidence="", confidence="TODO")))
        self.assertEqual(result.lines[-1], "K14: 2 finding(s), mode warn.")

    def test_ac8_summary_counts_the_findings_in_block_mode(self) -> None:
        result = self.run_cli(self.write("Nothing.\n"), "--mode", "block")
        self.assertEqual(result.lines[-1], "K14: 4 finding(s), mode block.")

    def test_ac8_summary_is_last_with_github_format(self) -> None:
        result = self.run_cli(self.write("Nothing.\n"), "--format", "github", "--mode", "block")
        self.assertEqual(result.lines[-1], "K14: 4 finding(s), mode block.")
        self.assertTrue(all(l.startswith("::error") for l in result.lines[:-1]))

    def test_ac8_summary_with_stdin(self) -> None:
        result = self.run_cli("-", stdin=FULL_BODY)
        self.assertEqual(result.lines[-1], "K14: 0 finding(s), mode warn.")


if __name__ == "__main__":
    unittest.main()
