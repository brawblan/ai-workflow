"""Tests for the link check of `stone check` (issue #124)."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from stone import cli, framework_check
from test_framework_check import CHECKS, GATES, PROFILE, WORKFLOW_MODEL

BROKEN = "See [x](missing.md).\n"
HARNESS = "harness: demo-harness\nprofiles: [demo]\n"


class LinkCheckBase(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name).resolve()
        framework = self.root / "framework"
        (framework / "profiles").mkdir(parents=True)
        (framework / "adapters").mkdir()
        (framework / "workflow-model.md").write_text(WORKFLOW_MODEL, encoding="utf-8")
        (framework / "checks.md").write_text(CHECKS, encoding="utf-8")
        (framework / "gates.md").write_text(GATES, encoding="utf-8")
        (framework / "profiles" / "demo.md").write_text(PROFILE, encoding="utf-8")
        (framework / "adapters" / "demo-harness.md").write_text("x", encoding="utf-8")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def config(self, extra: str = "") -> None:
        self.write(".cornerstone/config.yaml", HARNESS + extra)

    def findings(self, links: str = "default") -> list[framework_check.Finding]:
        return framework_check.run(self.root, None, links)

    def link_findings(self, links: str = "default") -> list[tuple[str, str]]:
        """Return (file, message) for each link finding."""
        return [(f.path, f.message) for f in self.findings(links) if "points to no file" in f.message]

    def link_files(self, links: str = "default") -> set[str]:
        return {Path(file).as_posix() for file, _ in self.link_findings(links)}

    def messages(self, links: str = "default") -> list[str]:
        return [f.message for f in self.findings(links)]


class LinkParsingTest(LinkCheckBase):
    """Link forms. Each link is in AGENTS.md, which is in the default scope."""

    def setUp(self) -> None:
        super().setUp()
        self.write("docs/Static Types.md", "# Static types\n")

    def test_percent_encoded_link_to_existing_file_has_no_finding(self) -> None:
        self.write("AGENTS.md", "See [types](docs/Static%20Types.md).\n")
        self.assertEqual(self.link_findings(), [])

    def test_percent_encoded_link_to_missing_file_shows_link_as_written(self) -> None:
        self.write("AGENTS.md", "See [types](docs/Missing%20File.md).\n")
        messages = [m for _, m in self.link_findings()]
        self.assertEqual(len(messages), 1)
        self.assertIn("'docs/Missing%20File.md'", messages[0])

    def test_root_relative_link_resolves_from_repo_root(self) -> None:
        self.write("apps/ga/config.xml", "<config/>\n")
        self.write("constitution/rules.md", "See [config](/apps/ga/config.xml).\n")
        self.assertEqual(self.link_findings(), [])

    def test_root_relative_link_to_missing_file_has_finding(self) -> None:
        self.write("constitution/rules.md", "See [gone](/gone.md).\n")
        messages = [m for _, m in self.link_findings()]
        self.assertEqual(len(messages), 1)
        self.assertIn("'/gone.md'", messages[0])

    def test_protocol_relative_link_is_skipped(self) -> None:
        self.write("AGENTS.md", "See [host](//example.com/x).\n")
        self.assertEqual(self.link_findings(), [])

    def test_fragment_only_link_is_skipped(self) -> None:
        self.write("AGENTS.md", "See [below](#not-a-heading).\n")
        self.assertEqual(self.link_findings(), [])

    def test_file_and_fragment_link_tests_the_file(self) -> None:
        self.write("AGENTS.md", "See [a](docs/Static%20Types.md#intro) and [b](missing.md#intro).\n")
        messages = [m for _, m in self.link_findings()]
        self.assertEqual(len(messages), 1)
        self.assertIn("'missing.md#intro'", messages[0])

    def test_angle_bracket_link_to_existing_file_has_no_finding(self) -> None:
        self.write("AGENTS.md", "See [types](<docs/Static Types.md>).\n")
        self.assertEqual(self.link_findings(), [])

    def test_angle_bracket_link_to_missing_file_has_finding(self) -> None:
        self.write("AGENTS.md", "See [missing](<docs/Missing File.md>).\n")
        messages = [m for _, m in self.link_findings()]
        self.assertEqual(len(messages), 1)
        self.assertIn("docs/Missing File.md", messages[0])


class DefaultScopeTest(LinkCheckBase):
    def test_file_outside_scope_is_not_reported(self) -> None:
        self.write("docs/old.md", BROKEN)
        self.write("README.md", BROKEN)
        self.assertEqual(self.link_findings(), [])

    def test_each_cornerstone_file_is_reported(self) -> None:
        owned = ["AGENTS.md", "CLAUDE.md", "constitution/x.md", ".cornerstone/x.md",
                 "docs/plans/x.md", "docs/specs/x.md", "framework/x.md"]
        for name in owned:
            self.write(name, BROKEN)
        self.write("docs/old.md", BROKEN)
        self.assertEqual(self.link_files(), set(owned))

    def test_custom_plans_and_specs_folders_are_reported(self) -> None:
        self.config("paths:\n  plans: work/plans/\n  specs: work/specs/\n")
        self.write("work/plans/x.md", BROKEN)
        self.write("work/specs/x.md", BROKEN)
        self.write("docs/old.md", BROKEN)
        self.assertEqual(self.link_files(), {"work/plans/x.md", "work/specs/x.md"})

    def test_templates_exclusion_still_applies(self) -> None:
        self.write("framework/templates/t.md", BROKEN)
        self.write("framework/x.md", BROKEN)
        self.assertEqual(self.link_files(), {"framework/x.md"})

    def test_templates_exclusion_applies_in_all_mode(self) -> None:
        self.write("templates/t.md", BROKEN)
        self.assertEqual(self.link_files("all"), set())


class AllScopeTest(LinkCheckBase):
    def test_links_all_reports_file_outside_default_scope(self) -> None:
        self.write("docs/old.md", BROKEN)
        self.write("AGENTS.md", BROKEN)
        self.assertEqual(self.link_files("all"), {"docs/old.md", "AGENTS.md"})


class ConfigPathsTest(LinkCheckBase):
    def test_config_paths_adds_folder_and_keeps_defaults(self) -> None:
        self.config("checks:\n  links:\n    paths: [docs/]\n")
        self.write("docs/old.md", BROKEN)
        self.write("AGENTS.md", BROKEN)
        self.write("other/x.md", BROKEN)
        self.assertEqual(self.link_files(), {"docs/old.md", "AGENTS.md"})

    def test_config_paths_adds_single_file(self) -> None:
        self.config("checks:\n  links:\n    paths: [README.md]\n")
        self.write("README.md", BROKEN)
        self.assertEqual(self.link_files(), {"README.md"})

    def test_non_list_value_gives_config_finding(self) -> None:
        self.config("checks:\n  links:\n    paths: docs/\n")
        self.write("docs/old.md", BROKEN)
        self.write("AGENTS.md", BROKEN)
        self.assertTrue(any("'checks.links.paths' must be a list" in m for m in self.messages()))
        self.assertEqual(self.link_files(), {"AGENTS.md"})

    def test_path_outside_repo_gives_config_finding(self) -> None:
        self.config("checks:\n  links:\n    paths: ['../x']\n")
        self.write("AGENTS.md", BROKEN)
        findings = self.findings()
        config_findings = [f for f in findings if "outside the repo" in f.message]
        self.assertEqual(len(config_findings), 1)
        self.assertIn("../x", config_findings[0].message)
        self.assertEqual(Path(config_findings[0].path).as_posix(), ".cornerstone/config.yaml")
        self.assertEqual(self.link_files(), {"AGENTS.md"})

    def test_check_config_reports_problem_directly(self) -> None:
        self.config("checks:\n  links:\n    paths: 3\n")
        messages = [f.message for f in
                    framework_check.check_config(self.root, self.root / "framework")]
        self.assertTrue(any("'checks.links.paths' must be a list" in m for m in messages))


class CliLinksTest(LinkCheckBase):
    def run_cli(self, *extra: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["check", "--root", str(self.root), *extra])
        return code, out.getvalue()

    def test_default_links_mode_skips_file_outside_scope(self) -> None:
        self.write("docs/old.md", BROKEN)
        code, output = self.run_cli()
        self.assertEqual(code, 0)
        self.assertNotIn("missing.md", output)

    def test_default_links_mode_is_default(self) -> None:
        args = cli._parser().parse_args(["check"])
        self.assertEqual(args.links, "default")

    def test_links_all_reports_file_outside_scope(self) -> None:
        self.write("docs/old.md", BROKEN)
        code, output = self.run_cli("--links", "all")
        self.assertEqual(code, 1)
        self.assertIn("missing.md", output)
        self.assertIn("old.md", output)

    def test_invalid_links_value_exits_with_code_2(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.run_cli("--links", "everything")
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
