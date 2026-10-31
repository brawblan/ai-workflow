"""Tests for stone.repo_rules (R1 pins, R2 version bump, R3 event text) and `stone check-rules` (D78)."""

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


EVENT = "${{ github.event.pull_request.title }}"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_workflow(root: Path, run_text: str, rel: str = ".github/workflows/ci.yml") -> None:
    _write(root, rel, "jobs:\n  j:\n    steps:\n" + run_text)


class RunLinesTests(unittest.TestCase):
    def test_inline_value(self) -> None:
        self.assertEqual(repo_rules.run_lines("steps:\n  - run: echo hi\n"), [(2, "echo hi")])

    def test_inline_value_without_dash(self) -> None:
        self.assertEqual(repo_rules.run_lines("  run: echo hi\n"), [(1, "echo hi")])

    def test_literal_block(self) -> None:
        text = "- run: |\n    a\n    b\n- name: x\n"
        self.assertEqual(repo_rules.run_lines(text), [(2, "    a"), (3, "    b")])

    def test_folded_block_with_strip(self) -> None:
        text = "      - run: >-\n          a\n          b\n      - name: x\n"
        self.assertEqual(repo_rules.run_lines(text), [(2, "          a"), (3, "          b")])

    def test_blank_lines_inside_block(self) -> None:
        text = "- run: |\n    a\n\n    b\nnext: 1\n"
        self.assertEqual(repo_rules.run_lines(text), [(2, "    a"), (3, ""), (4, "    b")])

    def test_block_ends_at_indent_equal_to_key(self) -> None:
        text = "  run: |\n    a\n  other: ${{ github.event.x }}\n"
        self.assertEqual(repo_rules.run_lines(text), [(2, "    a")])

    def test_block_ends_at_indent_below_key(self) -> None:
        text = "    run: |\n      a\n  other: 1\n"
        self.assertEqual(repo_rules.run_lines(text), [(2, "      a")])

    def test_list_form_block_ends_at_next_dash(self) -> None:
        text = "- run: |\n    a\n- run: echo b\n"
        self.assertEqual(repo_rules.run_lines(text), [(2, "    a"), (3, "echo b")])

    def test_run_without_value_gives_no_lines(self) -> None:
        text = "jobs:\n  run:\n    runs-on: x\n    steps:\n      - uses: a/b@v1\n"
        self.assertEqual(repo_rules.run_lines(text), [])

    def test_block_indicator_with_trailing_comment(self) -> None:
        text = "- run: | # note\n    a\n"
        self.assertEqual(repo_rules.run_lines(text), [(2, "    a")])

    def test_no_run(self) -> None:
        self.assertEqual(repo_rules.run_lines("name: x\nenv:\n  A: b\n"), [])


class EventTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_r3_inline_fails(self) -> None:
        _run_workflow(self.root, f"      - run: echo {EVENT}\n")
        found = repo_rules.check_event_text(self.root)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].check, "R3")
        self.assertEqual(found[0].path, ".github/workflows/ci.yml")
        self.assertEqual(found[0].line, 4)
        self.assertIn("github.event.pull_request.title", found[0].message)

    def test_r3_block_fails_with_line_number(self) -> None:
        _run_workflow(self.root, f"      - run: |\n          echo ok\n\n          echo {EVENT}\n")
        found = repo_rules.check_event_text(self.root)
        self.assertEqual([(f.check, f.line) for f in found], [("R3", 7)])

    def test_r3_folded_block_fails(self) -> None:
        _run_workflow(self.root, f"      - run: >-\n          echo {EVENT}\n")
        self.assertEqual(len(repo_rules.check_event_text(self.root)), 1)

    def test_r3_head_ref_fails(self) -> None:
        _run_workflow(self.root, "      - run: git checkout ${{ github.head_ref }}\n")
        found = repo_rules.check_event_text(self.root)
        self.assertEqual(len(found), 1)
        self.assertIn("github.head_ref", found[0].message)

    def test_r3_event_body_fails_in_block_with_spaces_in_braces(self) -> None:
        _run_workflow(self.root, "      - run: |\n          x=${{github.event.comment.body}}\n")
        self.assertEqual(len(repo_rules.check_event_text(self.root)), 1)

    def test_r3_env_passes(self) -> None:
        _run_workflow(self.root, f"      - env:\n          TITLE: {EVENT}\n"
                                 "        run: echo \"$TITLE\"\n")
        self.assertEqual(repo_rules.check_event_text(self.root), [])

    # DEFECT in run_lines: for "- run: |", key_indent is the column of the dash, not of "run".
    # A sibling key ("env:") at the column of "run" is then read as block text. D96 says the block
    # is each line indented more than the "run:" key. Remove expectedFailure when this is fixed.
    @unittest.expectedFailure
    def test_r3_env_after_run_block_passes(self) -> None:
        _run_workflow(self.root, "      - run: |\n          echo \"$TITLE\"\n"
                                 f"        env:\n          TITLE: {EVENT}\n")
        self.assertEqual(repo_rules.check_event_text(self.root), [])

    def test_r3_if_passes(self) -> None:
        _run_workflow(self.root, f"      - if: {EVENT} == 'x'\n        run: echo hi\n")
        self.assertEqual(repo_rules.check_event_text(self.root), [])

    def test_r3_safe_contexts_pass(self) -> None:
        for expr in ["${{ github.event_name }}", "${{ github.base_ref }}"]:
            with self.subTest(expr=expr):
                _run_workflow(self.root, f"      - run: echo {expr}\n")
                self.assertEqual(repo_rules.check_event_text(self.root), [])

    def test_r3_two_findings_on_one_line(self) -> None:
        _run_workflow(self.root, f"      - run: echo {EVENT} ${{{{ github.head_ref }}}}\n")
        self.assertEqual(len(repo_rules.check_event_text(self.root)), 2)

    def test_r3_both_extensions(self) -> None:
        _run_workflow(self.root, f"      - run: echo {EVENT}\n", ".github/workflows/a.yml")
        _run_workflow(self.root, f"      - run: echo {EVENT}\n", ".github/workflows/b.yaml")
        paths = sorted(f.path for f in repo_rules.check_event_text(self.root))
        self.assertEqual(paths, [".github/workflows/a.yml", ".github/workflows/b.yaml"])

    def test_r3_templates_are_read(self) -> None:
        base = "framework/adapters/x/templates/workflows"
        line = "      - run: echo $${{ github.event.pull_request.body }}\n"
        _run_workflow(self.root, line, f"{base}/ci.yml")
        _run_workflow(self.root, line, f"{base}/steps/inner.yaml")
        paths = sorted(f.path for f in repo_rules.check_event_text(self.root))
        self.assertEqual(paths, [f"{base}/ci.yml", f"{base}/steps/inner.yaml"])

    def test_r3_files_outside_folders_ignored(self) -> None:
        line = f"      - run: echo {EVENT}\n"
        _run_workflow(self.root, line, "docs/ci.yml")
        _run_workflow(self.root, line, "framework/adapters/x/templates/other/ci.yml")
        _run_workflow(self.root, line, "framework/adapters/x/workflows/ci.yml")
        _run_workflow(self.root, line, ".github/other/ci.yml")
        self.assertEqual(repo_rules.check_event_text(self.root), [])

    def test_r3_non_yaml_files_ignored(self) -> None:
        _run_workflow(self.root, f"      - run: echo {EVENT}\n", ".github/workflows/n.txt")
        self.assertEqual(repo_rules.check_event_text(self.root), [])

    def test_r3_no_folders(self) -> None:
        self.assertEqual(repo_rules.check_event_text(self.root), [])

    def test_run_without_base_includes_r3_and_not_r2(self) -> None:
        _run_workflow(self.root, f"      - run: echo {EVENT}\n")
        found = repo_rules.run(self.root, None)
        self.assertEqual([f.check for f in found], ["R3"])

    def test_run_reports_r1_and_r3_together(self) -> None:
        _write(self.root, ".github/workflows/ci.yml",
               "jobs:\n  j:\n    steps:\n      - uses: a/b@v1\n"
               f"      - run: echo {EVENT}\n")
        found = repo_rules.run(self.root, None)
        self.assertEqual(sorted(f.check for f in found), ["R1", "R3"])

    def test_r3_passes_on_real_repo(self) -> None:
        self.assertEqual(repo_rules.check_event_text(REPO_ROOT), [])
        self.assertEqual([f for f in repo_rules.run(REPO_ROOT, None) if f.check == "R3"], [])


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
        self.assertNotIn("R2", out)
        self.assertIn("check-rules: 0 error(s).", out)

    def test_r3_error_returns_1_without_base(self) -> None:
        _run_workflow(self.root, f"      - run: echo {EVENT}\n")
        code, out = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("R3", out)
        self.assertIn("check-rules: 1 error(s).", out)

    def test_r3_github_format(self) -> None:
        _run_workflow(self.root, f"      - run: echo {EVENT}\n")
        code, out = self.run_cli("--format", "github")
        self.assertEqual(code, 1)
        self.assertIn("::error", out)

    def test_summary_line_counts_errors(self) -> None:
        _workflow(self.root, f"- uses: a/b@{SHA}")
        self.assertIn("check-rules: 0 error(s).", self.run_cli()[1])

    def test_r3_with_base_runs_with_r2(self) -> None:
        _write(self.root, SKILL, "two\n")
        _run_workflow(self.root, f"      - run: echo {EVENT}\n")
        self.commit("both")
        code, out = self.run_cli("--base", "main")
        self.assertEqual(code, 1)
        self.assertIn("R2", out)
        self.assertIn("R3", out)
        self.assertIn("check-rules: 2 error(s).", out)

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
