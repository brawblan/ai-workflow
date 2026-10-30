"""Tests for K23, the new dependency check (D90), and the `stone check-dependencies` command."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from stone import dependency_check
from stone.cli import main

GIT = ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


def pkg(**fields: dict[str, str]) -> str:
    return json.dumps(fields)


def body(section: str = "") -> str:
    return f"## Summary\n\nA change.\n\n{section}\n## Risks\n\nNone.\n"


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> None:
        subprocess.run([*GIT, "-C", str(self.root), *args], check=True, capture_output=True)

    def write(self, files: dict[str, str]) -> None:
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def make(self, base: dict[str, str], head: dict[str, str]) -> None:
        """Commit `base` on main, then commit `head` on a feature branch."""
        self.write({"README.md": "x\n", **base})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.write(head)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "head")

    def new(self, base: dict[str, str], head: dict[str, str]) -> dict[str, set[str]]:
        self.make(base, head)
        return dependency_check.new_packages(self.root, "main")

    def findings(self, base: dict[str, str], head: dict[str, str], text: str):
        self.make(base, head)
        return dependency_check.check(self.root, "main", text)


class PackageJsonTest(RepoCase):
    def test_r1_new_key_in_each_dependency_map_is_found(self) -> None:
        for field in ("dependencies", "devDependencies", "optionalDependencies",
                      "peerDependencies"):
            with self.subTest(field=field):
                self.setUp()
                found = self.new({"package.json": pkg(**{field: {"a": "1"}})},
                                 {"package.json": pkg(**{field: {"a": "1", "b": "2"}})})
                self.assertEqual(found, {"package.json": {"b"}})

    def test_r1_version_change_is_not_new(self) -> None:
        found = self.new({"package.json": pkg(dependencies={"a": "1"})},
                         {"package.json": pkg(dependencies={"a": "2"})})
        self.assertEqual(found, {})

    def test_r1_removed_package_is_not_new(self) -> None:
        found = self.new({"package.json": pkg(dependencies={"a": "1", "b": "1"})},
                         {"package.json": pkg(dependencies={"a": "1"})})
        self.assertEqual(found, {})

    def test_r1_scoped_name_is_found(self) -> None:
        found = self.new({"package.json": pkg(dependencies={})},
                         {"package.json": pkg(dependencies={"@evil/x": "1"})})
        self.assertEqual(found, {"package.json": {"@evil/x"}})

    def test_r1_other_fields_are_not_packages(self) -> None:
        found = self.new({"package.json": pkg(dependencies={})},
                         {"package.json": pkg(dependencies={}, scripts={"x": "y"})})
        self.assertEqual(found, {})


class PyprojectTest(RepoCase):
    BASE = '[project]\nname = "p"\nversion = "1"\n'

    def test_r2_project_dependencies(self) -> None:
        head = self.BASE + 'dependencies = ["requests>=2", "rich"]\n'
        self.assertEqual(self.new({"pyproject.toml": self.BASE}, {"pyproject.toml": head}),
                         {"pyproject.toml": {"requests", "rich"}})

    def test_r2_optional_dependencies(self) -> None:
        head = self.BASE + '[project.optional-dependencies]\ndev = ["pytest"]\n'
        self.assertEqual(self.new({"pyproject.toml": self.BASE}, {"pyproject.toml": head}),
                         {"pyproject.toml": {"pytest"}})

    def test_r2_dependency_groups_skip_include_group(self) -> None:
        head = self.BASE + ('[dependency-groups]\ntest = ["pytest"]\n'
                            'all = [{include-group = "test"}, "coverage"]\n')
        self.assertEqual(self.new({"pyproject.toml": self.BASE}, {"pyproject.toml": head}),
                         {"pyproject.toml": {"pytest", "coverage"}})

    def test_r2_poetry_dependencies_ignore_python(self) -> None:
        head = self.BASE + '[tool.poetry.dependencies]\npython = "^3.11"\nflask = "^3"\n'
        self.assertEqual(self.new({"pyproject.toml": self.BASE}, {"pyproject.toml": head}),
                         {"pyproject.toml": {"flask"}})

    def test_r2_specifiers_and_extras_are_stripped(self) -> None:
        head = self.BASE + ('dependencies = ["requests[socks]>=2", "Foo_Bar ~=1.0", '
                            '"baz; python_version<\'3.12\'"]\n')
        self.assertEqual(self.new({"pyproject.toml": self.BASE}, {"pyproject.toml": head}),
                         {"pyproject.toml": {"requests", "foo-bar", "baz"}})

    def test_r2_existing_package_with_new_specifier_is_not_new(self) -> None:
        found = self.new({"pyproject.toml": self.BASE + 'dependencies = ["requests>=1"]\n'},
                         {"pyproject.toml": self.BASE + 'dependencies = ["requests[socks]>=2"]\n'})
        self.assertEqual(found, {})


class RequirementsTest(RepoCase):
    def test_r3_new_names_in_a_subfolder(self) -> None:
        found = self.new(
            {"svc/requirements.txt": "a==1\n", "svc/requirements-dev.txt": "b\n"},
            {"svc/requirements.txt": "a==1\nc>=2\n", "svc/requirements-dev.txt": "b\nd\n"})
        self.assertEqual(found, {"svc/requirements.txt": {"c"},
                                 "svc/requirements-dev.txt": {"d"}})

    def test_r3_comments_and_option_lines_are_ignored(self) -> None:
        found = self.new({"requirements.txt": "a\n"},
                         {"requirements.txt": "a\n# evil\n-r other.txt\n  # more\n--index-url x\n"})
        self.assertEqual(found, {})

    def test_r3_names_are_normalized(self) -> None:
        found = self.new({"requirements.txt": "py-yaml\n"}, {"requirements.txt": "Py_Yaml\n"})
        self.assertEqual(found, {})
        self.assertEqual(dependency_check.package_names("requirements.txt", "Py_Yaml==1\n"),
                         {"py-yaml"})

    def test_r3_name_with_dots_and_underscores_is_the_same(self) -> None:
        found = self.new({"requirements.txt": "zope.interface\n"},
                         {"requirements.txt": "zope_interface\n"})
        self.assertEqual(found, {})


class EdgeTest(RepoCase):
    def test_r4_new_manifest_counts_all_packages(self) -> None:
        found = self.new({}, {"web/package.json": pkg(dependencies={"a": "1", "b": "1"})})
        self.assertEqual(found, {"web/package.json": {"a", "b"}})

    def test_r4_manifest_that_does_not_parse_gives_no_finding(self) -> None:
        for name, text in (("package.json", "{not json"), ("pyproject.toml", "[[[ bad")):
            with self.subTest(name=name):
                self.setUp()
                self.assertEqual(self.new({}, {name: text}), {})

    def test_r4_manifest_with_wrong_shape_does_not_crash(self) -> None:
        self.assertEqual(self.new({}, {"package.json": "[1, 2]"}), {})

    def test_r4_unchanged_manifest_is_not_read(self) -> None:
        found = self.new({"package.json": pkg(dependencies={"a": "1"})},
                         {"other.txt": "x"})
        self.assertEqual(found, {})

    def test_r4_other_files_are_not_manifests(self) -> None:
        self.assertEqual(self.new({}, {"notes.txt": "evil\n", "deps.json": pkg(dependencies={"a": "1"})}), {})


class BodyTest(RepoCase):
    BASE = {"package.json": pkg(dependencies={})}
    HEAD = {"package.json": pkg(dependencies={"left-pad": "1", "@evil/x": "1"})}

    def test_r5_section_that_names_each_package_passes(self) -> None:
        text = body("## Dependencies\n\n- left-pad: pads strings, from npm.\n"
                    "- @evil/x: a scoped test helper, from npm.\n")
        self.assertEqual(self.findings(self.BASE, self.HEAD, text), [])

    def test_r5_mention_outside_the_section_does_not_count(self) -> None:
        text = body("## Dependencies\n\n- left-pad: pads strings.\n").replace(
            "A change.", "I add @evil/x too.")
        found = self.findings(self.BASE, self.HEAD, text)
        self.assertEqual(len(found), 1)
        self.assertIn("@evil/x", found[0].message)

    def test_r5_trailing_period_and_backticks_count(self) -> None:
        text = body("## Dependencies\n\nWe add `left-pad`. We add `@evil/x`.\n")
        self.assertEqual(self.findings(self.BASE, self.HEAD, text), [])

    def test_r5_name_in_a_sentence_with_a_period_counts(self) -> None:
        text = body("## Dependencies\n\nThe new package is left-pad.\nAnd @evil/x.\n")
        self.assertEqual(self.findings(self.BASE, self.HEAD, text), [])

    def test_r5_missing_section_gives_one_finding_for_each_package(self) -> None:
        found = self.findings(self.BASE, self.HEAD, body())
        self.assertEqual(len(found), 2)
        for finding in found:
            self.assertEqual(finding.check, "K23")
            self.assertEqual(finding.path, "package.json")
        messages = " ".join(f.message for f in found)
        self.assertIn("left-pad", messages)
        self.assertIn("@evil/x", messages)

    def test_r5_a_longer_name_does_not_cover_a_shorter_one(self) -> None:
        text = body("## Dependencies\n\n- left-pad-extra: no.\n")
        found = self.findings({"package.json": pkg(dependencies={})},
                              {"package.json": pkg(dependencies={"left-pad": "1"})}, text)
        self.assertEqual(len(found), 1)

    def test_r5_python_name_is_matched_after_normalizing(self) -> None:
        text = body("## Dependencies\n\n- py-yaml: config, from PyPI.\n")
        self.assertEqual(self.findings({}, {"requirements.txt": "Py_Yaml>=6\n"}, text), [])

    def test_r5_no_new_package_gives_no_finding_with_no_section(self) -> None:
        self.assertEqual(self.findings(self.BASE, self.BASE | {"x.md": "y"}, body()), [])


class CliTest(RepoCase):
    def run_cli(self, argv: list[str], stdin: str) -> tuple[int, str]:
        out = io.StringIO()
        old = os.getcwd()
        os.chdir(self.root)
        try:
            with redirect_stdout(out), mock.patch("sys.stdin", io.StringIO(stdin)):
                code = main(argv)
        finally:
            os.chdir(old)
        return code, out.getvalue()

    def setUp(self) -> None:
        super().setUp()
        self.make({"requirements.txt": "a\n"}, {"requirements.txt": "a\nevil\n"})

    def test_r6_warn_mode_exits_0_and_prints_findings(self) -> None:
        code, out = self.run_cli(["check-dependencies", "-", "--base", "main"], body())
        self.assertEqual(code, 0)
        self.assertIn("evil", out)
        self.assertIn("K23", out)
        self.assertIn("mode warn", out)

    def test_r6_block_mode_exits_1(self) -> None:
        code, out = self.run_cli(
            ["check-dependencies", "-", "--base", "main", "--mode", "block"], body())
        self.assertEqual(code, 1)
        self.assertIn("mode block", out)

    def test_r6_block_mode_exits_0_when_the_body_names_the_package(self) -> None:
        code, out = self.run_cli(
            ["check-dependencies", "-", "--base", "main", "--mode", "block"],
            body("## Dependencies\n\n- evil: reason, from PyPI.\n"))
        self.assertEqual(code, 0)
        self.assertIn("0 finding", out)

    def test_r6_github_format_prints_a_warning_in_warn_mode(self) -> None:
        code, out = self.run_cli(
            ["check-dependencies", "-", "--base", "main", "--format", "github"], body())
        self.assertEqual(code, 0)
        self.assertIn("::warning", out)

    def test_r6_github_format_prints_an_error_in_block_mode(self) -> None:
        code, out = self.run_cli(["check-dependencies", "-", "--base", "main",
                                  "--format", "github", "--mode", "block"], body())
        self.assertEqual(code, 1)
        self.assertIn("::error", out)

    def test_r6_body_file_is_read(self) -> None:
        (self.root / "body.md").write_text(body("## Dependencies\n\n- evil: x.\n"),
                                           encoding="utf-8")
        code, out = self.run_cli(["check-dependencies", "body.md", "--base", "main"], "")
        self.assertEqual(code, 0)
        self.assertIn("0 finding", out)

    def test_r6_bad_base_ref_exits_2(self) -> None:
        code, out = self.run_cli(["check-dependencies", "-", "--base", "no-such-ref"], body())
        self.assertEqual(code, 2)
        self.assertIn("check-dependencies", out)

    def test_r6_missing_body_file_exits_2(self) -> None:
        code, _ = self.run_cli(["check-dependencies", "nope.md", "--base", "main"], "")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
