"""Tests for stone.repo_rules (R1 pins, R2 version bump) and `stone check-rules` (D78)."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from stone import cli, repo_rules

SHA = "a" * 40
DIGEST = "b" * 64
SKILL = "plugins/cornerstone/skills/a/SKILL.md"
PLUGIN = "plugins/cornerstone/.claude-plugin/plugin.json"


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _workflow(root: Path, *uses_lines: str, name: str = "ci.yml") -> None:
    body = "jobs:\n  j:\n    steps:\n" + "".join(f"      {line}\n" for line in uses_lines)
    _write(root, f".github/workflows/{name}", body)


class PinTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def pins(self, *lines: str) -> list:
        _workflow(self.root, *lines)
        return repo_rules.check_pins(self.root)

    def test_r1_passing_forms(self) -> None:
        for line in [
            "- uses: ./local-action",
            "- uses: ./.github/actions/x",
            f"- uses: docker://img@sha256:{DIGEST}",
            f"- uses: owner/repo@{SHA} # v1",
            f"- uses: owner/repo@{SHA}",
            f"  uses: owner/repo@{SHA}",
            f"- uses: 'owner/repo@{SHA}'",
            f'- uses: "owner/repo@{SHA}" # v4.1.0',
            f"- uses: owner/repo/sub/dir@{SHA}",
            f"- uses: owner/repo/.github/workflows/x.yml@{SHA}",
        ]:
            with self.subTest(line=line):
                self.assertEqual(self.pins(line), [])

    def test_r1_failing_forms(self) -> None:
        for line in [
            "- uses: actions/checkout@v4",
            "- uses: actions/checkout@main",
            "- uses: actions/checkout@abc1234",
            f"- uses: actions/checkout@{'a' * 39}",
            f"- uses: actions/checkout@{'a' * 41}",
            f"- uses: actions/checkout@{'A' * 40}",
            "- uses: actions/checkout",
            "- uses: docker://img:tag",
            "- uses: docker://img",
            "- uses: 'actions/checkout@v4'",
            "- uses: owner/repo/.github/workflows/x.yml@v1",
        ]:
            with self.subTest(line=line):
                found = self.pins(line)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0].check, "R1")

    def test_r1_finding_path_and_line(self) -> None:
        _workflow(self.root, f"- uses: ok/ok@{SHA}", "- uses: bad/bad@v1", name="b.yaml")
        found = repo_rules.check_pins(self.root)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].path, ".github/workflows/b.yaml")
        self.assertEqual(found[0].line, 5)  # 3 header lines + 2nd step
        self.assertEqual(found[0].check, "R1")

    def test_r1_both_extensions_and_multiple_findings(self) -> None:
        _workflow(self.root, "- uses: a/b@v1", name="one.yml")
        _workflow(self.root, "- uses: c/d@v1", name="two.yaml")
        paths = sorted(f.path for f in repo_rules.check_pins(self.root))
        self.assertEqual(paths, [".github/workflows/one.yml", ".github/workflows/two.yaml"])

    def test_r1_no_workflow_folder(self) -> None:
        self.assertEqual(repo_rules.check_pins(self.root), [])

    def test_r1_commented_out_uses_is_ignored(self) -> None:
        self.assertEqual(self.pins("# uses: x/y@v1", f"- uses: x/y@{SHA}"), [])

    def test_r1_non_workflow_files_ignored(self) -> None:
        _write(self.root, ".github/workflows/notes.txt", "uses: x/y@v1\n")
        self.assertEqual(repo_rules.check_pins(self.root), [])


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout


class GitRepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q", "-b", "main")
        _git(self.root, "config", "user.name", "T")
        _git(self.root, "config", "user.email", "t@example.com")
        _git(self.root, "config", "commit.gpgsign", "false")
        _write(self.root, SKILL, "one\n")
        self.set_version("1.0.0")
        self.commit("base")
        _git(self.root, "checkout", "-q", "-b", "feature")

    def set_version(self, version: str) -> None:
        _write(self.root, PLUGIN, json.dumps({"version": version}))

    def commit(self, message: str) -> None:
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", message)

    def r2(self, **kwargs) -> list:
        return repo_rules.check_version_bump(self.root, "main", **kwargs)


class VersionBumpTests(GitRepoCase):
    def test_r2_skill_changed_version_same(self) -> None:
        _write(self.root, SKILL, "two\n")
        self.commit("skill")
        found = self.r2()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].check, "R2")

    def test_r2_skill_and_version_changed(self) -> None:
        _write(self.root, SKILL, "two\n")
        self.set_version("1.0.1")
        self.commit("skill")
        self.assertEqual(self.r2(), [])

    def test_r2_skill_added_counts(self) -> None:
        _write(self.root, "plugins/cornerstone/skills/b/SKILL.md", "new\n")
        self.commit("add")
        self.assertEqual(len(self.r2()), 1)

    def test_r2_skill_deleted_counts(self) -> None:
        (self.root / SKILL).unlink()
        self.commit("del")
        self.assertEqual(len(self.r2()), 1)

    def test_r2_no_skill_change(self) -> None:
        _write(self.root, "README.md", "x\n")
        self.commit("other")
        self.assertEqual(self.r2(), [])

    def test_r2_version_only_change(self) -> None:
        self.set_version("2.0.0")
        self.commit("ver")
        self.assertEqual(self.r2(), [])

    def test_r2_plugin_file_removed_at_head(self) -> None:
        _write(self.root, SKILL, "two\n")
        (self.root / PLUGIN).unlink()
        self.commit("rename")
        self.assertEqual(self.r2(), [])

    def test_r2_plugin_file_missing_at_base_and_head(self) -> None:
        _git(self.root, "checkout", "-q", "main")
        _git(self.root, "rm", "-q", PLUGIN)
        _git(self.root, "commit", "-q", "-m", "no plugin")
        _git(self.root, "checkout", "-q", "-B", "feature")
        _write(self.root, SKILL, "two\n")
        self.commit("skill")
        found = self.r2()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].check, "R2")

    def test_r2_no_version_at_head(self) -> None:
        _write(self.root, SKILL, "two\n")
        _write(self.root, PLUGIN, json.dumps({"name": "x"}))
        self.commit("skill")
        self.assertEqual(len(self.r2()), 1)

    def test_r2_invalid_json_at_head(self) -> None:
        _write(self.root, SKILL, "two\n")
        _write(self.root, PLUGIN, "{not json")
        self.commit("skill")
        self.assertEqual(len(self.r2()), 1)

    def test_r2_non_string_version_at_head(self) -> None:
        _write(self.root, SKILL, "two\n")
        _write(self.root, PLUGIN, json.dumps({"version": 2}))
        self.commit("skill")
        self.assertEqual(len(self.r2()), 1)

    def add_other_on_main(self) -> None:
        _git(self.root, "checkout", "-q", "main")
        _write(self.root, "other/skills/s.md", "a\n")
        _write(self.root, "other/plugin.json", json.dumps({"version": "1"}))
        self.commit("other")
        _git(self.root, "checkout", "-q", "feature")
        _git(self.root, "rebase", "-q", "main")

    def test_r2_custom_skills_and_plugin_file(self) -> None:
        self.add_other_on_main()
        kwargs = {"skills": "other/skills/", "plugin_file": "other/plugin.json"}
        _write(self.root, "other/skills/s.md", "b\n")
        self.commit("change")
        found = self.r2(**kwargs)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].path, "other/plugin.json")
        _write(self.root, "other/plugin.json", json.dumps({"version": "2"}))
        self.commit("bump")
        self.assertEqual(self.r2(**kwargs), [])
        # The default skills folder is untouched, so the default args give no finding.
        self.assertEqual(self.r2(), [])

    def test_r2_uses_merge_base(self) -> None:
        # Feature bumps nothing and changes no skill. Main moves on and changes a skill.
        _write(self.root, "README.md", "x\n")
        self.commit("feature work")
        _git(self.root, "checkout", "-q", "main")
        _write(self.root, SKILL, "main change\n")
        self.set_version("1.1.0")
        self.commit("main moves")
        _git(self.root, "checkout", "-q", "feature")
        self.assertEqual(self.r2(), [])

    def test_r2_merge_base_no_false_finding_when_only_base_changed_skill(self) -> None:
        _git(self.root, "checkout", "-q", "main")
        _write(self.root, SKILL, "main change\n")
        self.commit("main skill, same version")
        _git(self.root, "checkout", "-q", "feature")
        _write(self.root, "README.md", "x\n")
        self.commit("feature")
        self.assertEqual(self.r2(), [])


class CliTests(GitRepoCase):
    def run_cli(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["check-rules", "--root", str(self.root), *args])
        return code, out.getvalue()

    def test_clean_returns_0(self) -> None:
        _workflow(self.root, f"- uses: a/b@{SHA}")
        self.assertEqual(self.run_cli()[0], 0)

    def test_r1_error_returns_1(self) -> None:
        _workflow(self.root, "- uses: a/b@v1")
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("R1", out)

    def test_github_format_prints_error_annotation(self) -> None:
        _workflow(self.root, "- uses: a/b@v1")
        code, out = self.run_cli("--format", "github")
        self.assertEqual(code, 1)
        self.assertIn("::error", out)

    def test_base_adds_r2(self) -> None:
        _write(self.root, SKILL, "two\n")
        self.commit("skill")
        code, out = self.run_cli("--base", "main")
        self.assertEqual(code, 1)
        self.assertIn("R2", out)

    def test_base_clean_returns_0(self) -> None:
        _write(self.root, SKILL, "two\n")
        self.set_version("1.0.1")
        self.commit("skill")
        self.assertEqual(self.run_cli("--base", "main")[0], 0)

    def test_without_base_r2_does_not_run(self) -> None:
        _write(self.root, SKILL, "two\n")
        self.commit("skill")
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertNotIn("R2", out.replace("R1, R2:", ""))

    def test_bad_base_returns_2(self) -> None:
        self.assertEqual(self.run_cli("--base", "no-such-branch")[0], 2)

    def test_custom_args_pass_through(self) -> None:
        _git(self.root, "checkout", "-q", "main")
        _write(self.root, "other/skills/s.md", "a\n")
        _write(self.root, "other/plugin.json", json.dumps({"version": "1"}))
        self.commit("other")
        _git(self.root, "checkout", "-q", "feature")
        _git(self.root, "rebase", "-q", "main")
        _write(self.root, "other/skills/s.md", "b\n")
        self.commit("change")
        code, _ = self.run_cli("--base", "main", "--skills", "other/skills/",
                               "--plugin-file", "other/plugin.json")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
