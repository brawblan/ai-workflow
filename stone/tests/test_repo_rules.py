"""Tests for stone.repo_rules (R1 pins, R2 version bump, R4 commit format) and `stone check-rules` (D78, D97)."""

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


GOOD = "feat(stone): add a thing"


class SubjectProblemTests(unittest.TestCase):
    def test_r4_each_allowed_type_passes(self) -> None:
        for kind in ["build", "chore", "ci", "docs", "feat", "fix", "perf", "refactor", "revert",
                     "style", "test"]:
            with self.subTest(kind=kind):
                self.assertIsNone(repo_rules.subject_problem(f"{kind}(stone): summary"))
                self.assertIsNone(repo_rules.subject_problem(f"{kind}: summary"))

    def test_r4_scope_is_optional(self) -> None:
        self.assertIsNone(repo_rules.subject_problem("fix: summary"))
        self.assertIsNone(repo_rules.subject_problem("fix(a-b_c/d): summary"))

    def test_r4_breaking_marker_passes(self) -> None:
        self.assertIsNone(repo_rules.subject_problem("feat!: summary"))
        self.assertIsNone(repo_rules.subject_problem("feat(stone)!: summary"))

    def test_r4_git_revert_subject_passes(self) -> None:
        self.assertIsNone(repo_rules.subject_problem('Revert "feat(stone): add a thing"'))

    def test_r4_failing_subjects(self) -> None:
        for subject in [
            "feat:summary",
            "feat(stone):summary",
            "Feat: summary",
            "FIX(stone): summary",
            "fixup! feat(stone): summary",
            "squash! feat(stone): summary",
            "WIP",
            "wip: summary",
            "feat(my scope): summary",
            "feat(): summary",
            "",
            "feat:",
            "feat: ",
            "feat(stone):",
            "just a summary",
            "Revert without quotes",
        ]:
            with self.subTest(subject=subject):
                self.assertIsNotNone(repo_rules.subject_problem(subject))

    def test_r4_unknown_type_is_named(self) -> None:
        problem = repo_rules.subject_problem("feature(stone): summary")
        self.assertIsNotNone(problem)
        self.assertIn("feature", problem)


class CommitFormatTests(GitRepoCase):
    def r4(self) -> list:
        return repo_rules.check_commit_format(self.root, "main")

    def head_sha(self, rev: str = "HEAD") -> str:
        return _git(self.root, "rev-parse", rev).strip()

    def change(self, name: str, subject: str) -> None:
        _write(self.root, name, "x\n")
        self.commit(subject)

    def test_r4_good_commits_pass(self) -> None:
        self.change("a.txt", GOOD)
        self.change("b.txt", "fix: another")
        self.assertEqual(self.r4(), [])

    def test_r4_no_commits_on_branch(self) -> None:
        self.assertEqual(self.r4(), [])

    def test_r4_bad_commit_fails_with_sha_path_and_line(self) -> None:
        self.change("a.txt", "added a thing")
        found = self.r4()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].check, "R4")
        self.assertEqual(found[0].path, f"commit {self.head_sha()[:12]}")
        self.assertEqual(len(found[0].path), len("commit ") + 12)
        self.assertEqual(found[0].line, 1)
        self.assertIn("added a thing", found[0].message)

    def test_r4_two_bad_commits_give_two_findings(self) -> None:
        self.change("a.txt", "bad one")
        first = self.head_sha()
        self.change("b.txt", GOOD)
        self.change("c.txt", "Bad two")
        second = self.head_sha()
        paths = sorted(f.path for f in self.r4())
        self.assertEqual(paths, sorted([f"commit {first[:12]}", f"commit {second[:12]}"]))

    def test_r4_only_the_bad_commit_is_named(self) -> None:
        self.change("a.txt", GOOD)
        self.change("b.txt", "oops")
        bad = self.head_sha()
        self.change("c.txt", GOOD)
        found = self.r4()
        self.assertEqual([f.path for f in found], [f"commit {bad[:12]}"])

    def test_r4_merge_commit_with_git_subject_is_not_tested(self) -> None:
        self.change("a.txt", GOOD)
        _git(self.root, "checkout", "-q", "main")
        self.change("m.txt", "chore: main moves")
        _git(self.root, "checkout", "-q", "feature")
        _git(self.root, "merge", "-q", "--no-ff", "-m", "Merge branch 'main' into feature", "main")
        self.assertEqual(_git(self.root, "log", "-1", "--format=%P").count(" "), 1)
        self.assertEqual(self.r4(), [])

    def test_r4_bad_commit_on_branch_still_found_after_merge(self) -> None:
        self.change("a.txt", "bad")
        bad = self.head_sha()
        _git(self.root, "checkout", "-q", "main")
        self.change("m.txt", "chore: main moves")
        _git(self.root, "checkout", "-q", "feature")
        _git(self.root, "merge", "-q", "--no-ff", "-m", "Merge branch 'main' into feature", "main")
        self.assertEqual([f.path for f in self.r4()], [f"commit {bad[:12]}"])

    def test_r4_bad_commit_on_base_after_merge_base_is_not_tested(self) -> None:
        self.change("a.txt", GOOD)
        _git(self.root, "checkout", "-q", "main")
        self.change("m.txt", "bad base commit")
        _git(self.root, "checkout", "-q", "feature")
        self.assertEqual(self.r4(), [])

    def test_r4_bad_commit_on_base_after_merge_is_not_tested(self) -> None:
        self.change("a.txt", GOOD)
        _git(self.root, "checkout", "-q", "main")
        self.change("m.txt", "bad base commit")
        _git(self.root, "checkout", "-q", "feature")
        _git(self.root, "merge", "-q", "--no-ff", "-m", "Merge branch 'main' into feature", "main")
        self.assertEqual(self.r4(), [])

    def test_r4_bad_commit_before_merge_base_is_not_tested(self) -> None:
        # The "base" commit in setUp has a bad subject and is before the merge base.
        _git(self.root, "checkout", "-q", "main")
        _git(self.root, "commit", "-q", "--amend", "-m", "bad old commit")
        _git(self.root, "checkout", "-q", "-B", "feature")
        self.change("a.txt", GOOD)
        self.assertEqual(self.r4(), [])

    def test_r4_git_revert_commit_passes(self) -> None:
        self.change("a.txt", GOOD)
        _git(self.root, "revert", "--no-edit", "HEAD")
        self.assertTrue(_git(self.root, "log", "-1", "--format=%s").startswith('Revert "'))
        self.assertEqual(self.r4(), [])

    def test_r4_run_needs_base(self) -> None:
        self.change("a.txt", "bad")
        self.assertEqual([f.check for f in repo_rules.run(self.root, None)], [])
        self.assertEqual([f.check for f in repo_rules.run(self.root, "main")], ["R4"])


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
        self.commit("feat(skill): change")
        code, out = self.run_cli("--base", "main")
        self.assertEqual(code, 1)
        self.assertIn("R2", out)

    def test_base_clean_returns_0(self) -> None:
        _write(self.root, SKILL, "two\n")
        self.set_version("1.0.1")
        self.commit("feat(skill): change")
        self.assertEqual(self.run_cli("--base", "main")[0], 0)

    def test_without_base_r2_does_not_run(self) -> None:
        _write(self.root, SKILL, "two\n")
        self.commit("skill")
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertNotIn("R2", out)
        self.assertEqual(out.strip(), "check-rules: 0 error(s).")

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
        self.commit("fix(other): change")
        code, _ = self.run_cli("--base", "main", "--skills", "other/skills/",
                               "--plugin-file", "other/plugin.json")
        self.assertEqual(code, 1)

    def test_r4_without_base_bad_commit_does_not_fail(self) -> None:
        _write(self.root, "a.txt", "x\n")
        self.commit("bad subject")
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertNotIn("R4", out)

    def test_r4_with_base_bad_commit_returns_1(self) -> None:
        _write(self.root, "a.txt", "x\n")
        self.commit("bad subject")
        code, out = self.run_cli("--base", "main")
        self.assertEqual(code, 1)
        self.assertIn("R4", out)
        self.assertIn("check-rules: 1 error(s).", out)

    def test_r4_with_base_good_commit_returns_0(self) -> None:
        _write(self.root, "a.txt", "x\n")
        self.commit(GOOD)
        code, out = self.run_cli("--base", "main")
        self.assertEqual(code, 0)
        self.assertIn("check-rules: 0 error(s).", out)

    def test_summary_line_counts_errors(self) -> None:
        _workflow(self.root, "- uses: a/b@v1")
        _write(self.root, "a.txt", "x\n")
        self.commit("bad subject")
        code, out = self.run_cli("--base", "main")
        self.assertEqual(code, 1)
        self.assertIn("check-rules: 2 error(s).", out)
        self.assertNotIn("R1, R2:", out)


if __name__ == "__main__":
    unittest.main()
