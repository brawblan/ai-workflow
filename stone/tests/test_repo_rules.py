"""Tests for stone.repo_rules (R1 pins, R2 version bump, R3 event text, R4 commit format) and
`stone check-rules` (D78, D97, D98)."""

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

    def r3(self, run_text: str) -> list:
        _run_workflow(self.root, run_text)
        return repo_rules.check_event_text(self.root)

    def test_r3_expression_forms_fail_once_each(self) -> None:
        for expr in [
            "${{ format('{0}', github.event.pull_request.title) }}",
            "${{ toJSON(github.event) }}",
            "${{ github.event['pull_request']['title'] }}",
            "${{ GitHub.Event.pull_request.title }}",
            "${{ github['event'].pull_request.title }}",
        ]:
            with self.subTest(expr=expr):
                found = self.r3(f"      - run: echo {expr}\n")
                self.assertEqual([(f.check, f.line) for f in found], [("R3", 4)])

    def test_r3_one_expression_with_two_fields_gives_one_finding(self) -> None:
        expr = "github.event.a || github.event.b"
        found = self.r3(f"      - run: echo ${{{{ {expr} }}}}\n")
        self.assertEqual(len(found), 1)
        self.assertIn(expr, found[0].message)

    def test_r3_value_on_next_line_fails(self) -> None:
        found = self.r3(f"      - run:\n          echo {EVENT}\n")
        self.assertEqual([f.line for f in found], [5])

    def test_r3_plain_value_on_two_lines_fails_on_line_2(self) -> None:
        found = self.r3(f"      - run: echo a\n          {EVENT}\n")
        self.assertEqual([f.line for f in found], [5])

    def test_r3_double_quoted_value_on_two_lines_fails(self) -> None:
        found = self.r3(f'      - run: "echo a\n          {EVENT}"\n')
        self.assertEqual([f.line for f in found], [5])

    def test_r3_block_with_indent_indicator_fails(self) -> None:
        for indicator in ["|2-", "|2", ">2+", "|+2", "|-"]:
            with self.subTest(indicator=indicator):
                found = self.r3(f"      - run: {indicator}\n          echo {EVENT}\n")
                self.assertEqual([f.line for f in found], [5])

    def test_r3_steps_context_with_github_event_name_part_passes(self) -> None:
        self.assertEqual(self.r3("      - run: echo ${{ steps.github.event.x }}\n"), [])

    def test_r3_defaults_run_mapping_passes(self) -> None:
        text = ("defaults:\n  run:\n    shell: bash\n"
                f"    working-directory: {EVENT}\n")
        _write(self.root, ".github/workflows/ci.yml", text)
        self.assertEqual(repo_rules.check_event_text(self.root), [])

    def test_r3_run_comment_on_non_dash_key_passes(self) -> None:
        text = f"defaults:\n  run: # note\n    shell: {EVENT}\n"
        _write(self.root, ".github/workflows/ci.yml", text)
        self.assertEqual(repo_rules.check_event_text(self.root), [])

    def test_r3_crlf_valid_file_passes(self) -> None:
        text = ("jobs:\r\n  j:\r\n    steps:\r\n      - env:\r\n          T: " + EVENT +
                "\r\n        run: |\r\n          echo \"$T\"\r\n      - run: echo ok\r\n")
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/ci.yml").write_bytes(text.encode())
        self.assertEqual(repo_rules.check_event_text(self.root), [])

    def test_r3_crlf_bad_file_fails(self) -> None:
        text = "jobs:\r\n  j:\r\n    steps:\r\n      - run: echo " + EVENT + "\r\n"
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/ci.yml").write_bytes(text.encode())
        self.assertEqual(len(repo_rules.check_event_text(self.root)), 1)

    def test_r3_quoted_inline_value_without_event_text_passes(self) -> None:
        self.assertEqual(self.r3('      - run: "echo ${{ github.sha }}"\n'), [])
        self.assertEqual(self.r3("      - run: 'echo hi'\n"), [])

    def test_r3_event_text_outside_expression_passes(self) -> None:
        self.assertEqual(self.r3("      - run: echo github.event.x\n"), [])

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

    def test_r4_git_reapply_subject_passes(self) -> None:
        self.assertIsNone(repo_rules.subject_problem('Reapply "feat(stone): x"'))

    def test_r4_revert_without_closing_quote_fails(self) -> None:
        self.assertIsNotNone(repo_rules.subject_problem('Revert "anything'))
        self.assertIsNotNone(repo_rules.subject_problem('Reapply "anything'))

    def test_r4_scope_with_comma_and_space_fails(self) -> None:
        self.assertIsNotNone(repo_rules.subject_problem("docs(tips, framework): x"))

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

    def test_r4_detached_pull_request_merge_ref_tests_only_feature_commits(self) -> None:
        self.change("a.txt", "bad")
        bad = self.head_sha()
        _git(self.root, "checkout", "-q", "main")
        self.change("m.txt", "bad base commit")
        _git(self.root, "checkout", "-q", "--detach")
        _git(self.root, "merge", "-q", "--no-ff", "-m", "Merge feature into main", "feature")
        self.assertEqual(_git(self.root, "branch", "--show-current").strip(), "")
        self.assertEqual([f.path for f in self.r4()], [f"commit {bad[:12]}"])

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
        self.commit("feat(skill): both")
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


def _fn(text: str):
    import ast
    return ast.parse(text).body[0]


class CyclomaticTests(unittest.TestCase):
    def score(self, body: str) -> int:
        return repo_rules.cyclomatic(_fn("def f(x):\n" + "".join(
            f"    {line}\n" for line in body.splitlines())))

    def test_k9_plain_function_is_1(self) -> None:
        self.assertEqual(self.score("return 1"), 1)

    def test_k9_if_elif(self) -> None:
        self.assertEqual(self.score("if x:\n    pass\nelif x > 1:\n    pass"), 3)

    def test_k9_conditional_expression(self) -> None:
        self.assertEqual(self.score("return 1 if x else 2"), 2)

    def test_k9_for_while(self) -> None:
        self.assertEqual(self.score("for i in x:\n    pass\nwhile x:\n    pass"), 3)

    def test_k9_async_for(self) -> None:
        tree = _fn("async def f(x):\n    async for i in x:\n        pass\n")
        self.assertEqual(repo_rules.cyclomatic(tree), 2)

    def test_k9_except(self) -> None:
        self.assertEqual(self.score("try:\n    pass\nexcept A:\n    pass\n"
                                    "except B:\n    pass"), 3)

    def test_k9_match_case(self) -> None:
        self.assertEqual(self.score("match x:\n    case 1:\n        pass\n"
                                    "    case 2:\n        pass"), 3)

    def test_k9_comprehension(self) -> None:
        self.assertEqual(self.score("return [i for i in x]"), 2)
        self.assertEqual(self.score("return [i for i in x if i if i > 1]"), 4)

    def test_k9_bool_operands(self) -> None:
        self.assertEqual(self.score("return x and 1"), 2)
        self.assertEqual(self.score("return x and 1 or 2 or 3"), 4)

    def test_k9_nested_function_and_class_not_counted(self) -> None:
        body = ("def g():\n    if x:\n        pass\n"
                "class C:\n    def m(self):\n        if x:\n            pass")
        self.assertEqual(self.score(body), 1)


DIFF = """diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1,2 +5,3 @@
+x
@@ -9 +12 @@
+y
@@ -20,2 +30,0 @@
-gone
@@ -40,0 +50 @@
+z
diff --git a/src/b.py b/src/b.py
--- a/src/b.py
+++ b/src/b.py
@@ -1 +1,2 @@
+q
diff --git a/src/old.py b/src/old.py
--- a/src/old.py
+++ /dev/null
@@ -1,3 +0,0 @@
-a
"""


class ChangedLinesTests(unittest.TestCase):
    def test_k9_hunks_per_path(self) -> None:
        found = repo_rules.changed_lines(DIFF)
        self.assertEqual(found["src/a.py"], {5, 6, 7, 12, 50})
        self.assertEqual(found["src/b.py"], {1, 2})

    def test_k9_no_count_is_one_line(self) -> None:
        self.assertEqual(repo_rules.changed_lines(DIFF)["src/a.py"] & {12, 13}, {12})

    def test_k9_zero_count_adds_nothing(self) -> None:
        self.assertNotIn(30, repo_rules.changed_lines(DIFF)["src/a.py"])

    def test_k9_deleted_file_has_no_entry(self) -> None:
        self.assertNotIn("src/old.py", repo_rules.changed_lines(DIFF))
        self.assertNotIn("", repo_rules.changed_lines(DIFF))

    def test_k9_empty_diff(self) -> None:
        self.assertEqual(repo_rules.changed_lines(""), {})


class ComplexityLimitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_k9_defaults_without_file(self) -> None:
        self.assertEqual(repo_rules.complexity_limits(self.root),
                         ({"cyclomatic": 10, "function_lines": 60}, ("src/",)))

    def test_k9_reads_config(self) -> None:
        _write(self.root, ".cornerstone/config.yaml",
               "limits:\n  cyclomatic: 5\n  function_lines: 20\npaths:\n  source:\n"
               "    - lib/\n    - app/\n")
        self.assertEqual(repo_rules.complexity_limits(self.root),
                         ({"cyclomatic": 5, "function_lines": 20}, ("lib/", "app/")))

    def test_k9_missing_keys_use_defaults(self) -> None:
        _write(self.root, ".cornerstone/config.yaml", "limits:\n  cyclomatic: 7\n")
        self.assertEqual(repo_rules.complexity_limits(self.root),
                         ({"cyclomatic": 7, "function_lines": 60}, ("src/",)))

    def test_k9_empty_file_uses_defaults(self) -> None:
        _write(self.root, ".cornerstone/config.yaml", "")
        self.assertEqual(repo_rules.complexity_limits(self.root)[1], ("src/",))

    def test_k9_unknown_limit_keys_ignored(self) -> None:
        _write(self.root, ".cornerstone/config.yaml", "limits:\n  pr_changed_lines: 9\n")
        self.assertEqual(repo_rules.complexity_limits(self.root)[0],
                         {"cyclomatic": 10, "function_lines": 60})


def _branchy(n: int, name: str = "f") -> str:
    """A function with cyclomatic 1 + n."""
    return f"def {name}(x):\n" + "".join(f"    if x == {i}:\n        pass\n"
                                          for i in range(n)) + "    return x\n"


LIM = {"cyclomatic": 3, "function_lines": 8}


class FunctionProblemsTests(unittest.TestCase):
    def test_k9_untouched_function_not_tested(self) -> None:
        text = _branchy(5, "a") + "\n\ndef b():\n    return 1\n"
        self.assertEqual(repo_rules.function_problems(text, {len(text.splitlines())}, LIM), [])

    def test_k9_over_cyclomatic_fails(self) -> None:
        out = repo_rules.function_problems(_branchy(3), {1}, {**LIM, "function_lines": 99})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], 1)
        self.assertIn("cyclomatic complexity of 4", out[0][1])
        self.assertIn("'f'", out[0][1])

    def test_k9_at_cyclomatic_limit_passes(self) -> None:
        self.assertEqual(repo_rules.function_problems(
            _branchy(2), {1}, {**LIM, "function_lines": 99}), [])

    def test_k9_over_function_lines_fails(self) -> None:
        text = "def f():\n" + "    pass\n" * 8  # 9 lines
        out = repo_rules.function_problems(text, {2}, LIM)
        self.assertEqual(len(out), 1)
        self.assertIn("9 lines", out[0][1])

    def test_k9_at_function_lines_limit_passes(self) -> None:
        text = "def f():\n" + "    pass\n" * 7  # 8 lines
        self.assertEqual(repo_rules.function_problems(text, {1}, LIM), [])

    def test_k9_method_has_qualified_name(self) -> None:
        text = "class Cls:\n" + "".join(
            "    " + line + "\n" for line in _branchy(3, "method").splitlines())
        out = repo_rules.function_problems(text, {2}, {**LIM, "function_lines": 99})
        self.assertIn("'Cls.method'", out[0][1])

    def test_k9_old_over_limit_same_passes(self) -> None:
        old = _branchy(4)
        new = old.replace("return x", "return x + 1")
        self.assertEqual(repo_rules.function_problems(new, {10}, {**LIM, "function_lines": 99},
                                                      old), [])

    def test_k9_old_over_limit_lower_passes(self) -> None:
        self.assertEqual(repo_rules.function_problems(
            _branchy(4), {1}, {**LIM, "function_lines": 99}, _branchy(6)), [])

    def test_k9_old_over_limit_increased_fails(self) -> None:
        out = repo_rules.function_problems(_branchy(5), {1}, {**LIM, "function_lines": 99},
                                           _branchy(4))
        self.assertEqual(len(out), 1)
        self.assertIn("(it was 5)", out[0][1])

    def test_k9_old_under_limit_now_over_has_no_was(self) -> None:
        out = repo_rules.function_problems(_branchy(3), {1}, {**LIM, "function_lines": 99},
                                           _branchy(1))
        self.assertEqual(len(out), 1)
        self.assertNotIn("it was", out[0][1])

    def test_k9_new_function_over_fails(self) -> None:
        out = repo_rules.function_problems(_branchy(3, "g"), {1}, {**LIM, "function_lines": 99},
                                           _branchy(9, "other"))
        self.assertEqual(len(out), 1)
        self.assertNotIn("it was", out[0][1])

    def test_k9_unparsable_old_text_counts_as_new(self) -> None:
        out = repo_rules.function_problems(_branchy(3), {1}, {**LIM, "function_lines": 99},
                                           "def (:\n")
        self.assertEqual(len(out), 1)


class ComplexityCheckTests(GitRepoCase):
    def k9(self) -> list:
        return repo_rules.check_complexity(self.root, "main")

    def test_k9_finds_changed_over_limit_function(self) -> None:
        _write(self.root, "src/a.py", _branchy(11))
        self.commit("feat: a")
        out = self.k9()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].check, "K9")
        self.assertEqual(out[0].path, "src/a.py")
        self.assertEqual(out[0].line, 1)

    def test_k9_within_limits_passes(self) -> None:
        _write(self.root, "src/a.py", _branchy(2))
        self.commit("feat: a")
        self.assertEqual(self.k9(), [])

    def test_k9_ignores_file_outside_source(self) -> None:
        _write(self.root, "tools/a.py", _branchy(11))
        self.commit("feat: a")
        self.assertEqual(self.k9(), [])

    def test_k9_ignores_non_py_file(self) -> None:
        _write(self.root, "src/a.txt", _branchy(11))
        self.commit("feat: a")
        self.assertEqual(self.k9(), [])

    def test_k9_uses_configured_source_and_limits(self) -> None:
        _write(self.root, ".cornerstone/config.yaml",
               "limits:\n  cyclomatic: 2\npaths:\n  source:\n    - lib/\n")
        self.commit("chore: config")
        _write(self.root, "lib/a.py", _branchy(2))
        _write(self.root, "src/b.py", _branchy(2))
        self.commit("feat: a")
        out = self.k9()
        self.assertEqual([f.path for f in out], ["lib/a.py"])

    def test_k9_ignores_untouched_over_limit_function(self) -> None:
        _write(self.root, "src/a.py", _branchy(11, "big") + "\n\ndef small():\n    return 1\n")
        self.commit("feat: a")
        _git(self.root, "checkout", "-q", "-B", "main", "HEAD")
        _git(self.root, "checkout", "-q", "-b", "feature2")
        text = (self.root / "src/a.py").read_text().replace("return 1", "return 2")
        _write(self.root, "src/a.py", text)
        self.commit("fix: small")
        self.assertEqual(self.k9(), [])

    def test_k9_deleted_file_ignored(self) -> None:
        _write(self.root, "src/a.py", _branchy(11))
        self.commit("feat: a")
        _git(self.root, "checkout", "-q", "-B", "main", "HEAD")
        _git(self.root, "checkout", "-q", "-b", "feature2")
        (self.root / "src/a.py").unlink()
        self.commit("chore: drop")
        self.assertEqual(self.k9(), [])

    def test_k9_unparsable_head_file(self) -> None:
        _write(self.root, "src/a.py", "def (:\n")
        self.commit("feat: a")
        out = self.k9()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].check, "K9")
        self.assertIn("does not parse", out[0].message)

    def test_k9_run_with_base_reports(self) -> None:
        _write(self.root, "src/a.py", _branchy(11))
        self.commit("feat: a")
        self.assertIn("K9", [f.check for f in repo_rules.run(self.root, "main")])

    def test_k9_run_without_base_skips(self) -> None:
        _write(self.root, "src/a.py", _branchy(11))
        self.commit("feat: a")
        self.assertNotIn("K9", [f.check for f in repo_rules.run(self.root, None)])


class SkipComplexityTests(GitRepoCase):
    """D103: --skip-k9 skips K9 and keeps R2 and R4."""

    def run_cli(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["check-rules", "--root", str(self.root), *args])
        return code, out.getvalue()

    def test_run_without_complexity_skips_k9(self) -> None:
        _write(self.root, "src/a.py", _branchy(11))
        self.commit("feat: a")
        self.assertEqual([f.check for f in repo_rules.run(self.root, "main")], ["K9"])
        self.assertEqual(repo_rules.run(self.root, "main", complexity=False), [])

    def test_run_without_complexity_keeps_r2(self) -> None:
        _write(self.root, SKILL, "two\n")
        self.commit("feat(skill): change")
        found = repo_rules.run(self.root, "main", complexity=False)
        self.assertEqual([f.check for f in found], ["R2"])

    def test_cli_skip_k9_returns_0(self) -> None:
        _write(self.root, "src/a.py", _branchy(11))
        self.commit("feat: a")
        code, out = self.run_cli("--base", "main")
        self.assertEqual(code, 1)
        self.assertIn("K9", out)
        code, out = self.run_cli("--base", "main", "--skip-k9")
        self.assertEqual(code, 0)
        self.assertNotIn("K9", out)

    def test_cli_skip_k9_keeps_r4(self) -> None:
        _write(self.root, "src/a.py", "x = 1\n")
        self.commit("bad subject")
        code, out = self.run_cli("--base", "main", "--skip-k9")
        self.assertEqual(code, 1)
        self.assertIn("R4", out)


class StoneWorkflowTests(unittest.TestCase):
    """D103: the stone workflow skips K9 only on a PR into main."""

    def test_rules_step_skips_k9_for_main_only(self) -> None:
        text = (REPO_ROOT / ".github/workflows/stone.yml").read_text()
        self.assertIn('if [ "$BASE_REF" = "main" ]; then skip=(--skip-k9); fi', text)
        self.assertIn('stone check-rules --base "origin/${BASE_REF}" "${skip[@]}"', text)


class OldPathsTests(unittest.TestCase):
    def test_k9_old_paths_rename(self) -> None:
        diff = ("diff --git a/src/a.py b/src/b.py\nsimilarity index 90%\n"
                "rename from src/a.py\nrename to src/b.py\n"
                "--- a/src/a.py\n+++ b/src/b.py\n@@ -1 +1 @@\n-x\n+y\n")
        self.assertEqual(repo_rules.old_paths(diff), {"src/b.py": "src/a.py"})

    def test_k9_old_paths_unmoved_file_has_no_entry(self) -> None:
        diff = "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-x\n+y\n"
        self.assertEqual(repo_rules.old_paths(diff), {})

    def test_k9_old_paths_new_file_has_no_entry(self) -> None:
        diff = "--- /dev/null\n+++ b/src/a.py\n@@ -0,0 +1 @@\n+y\n"
        self.assertEqual(repo_rules.old_paths(diff), {})

    def test_k9_old_paths_empty(self) -> None:
        self.assertEqual(repo_rules.old_paths(""), {})


class ComplexityLimitsRobustnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_k9_string_source_becomes_one_tuple(self) -> None:
        _write(self.root, ".cornerstone/config.yaml", "paths:\n  source: lib/\n")
        self.assertEqual(repo_rules.complexity_limits(self.root)[1], ("lib/",))

    def test_k9_string_limit_uses_default(self) -> None:
        _write(self.root, ".cornerstone/config.yaml",
               "limits:\n  cyclomatic: \"10\"\n  function_lines: 20\n")
        self.assertEqual(repo_rules.complexity_limits(self.root)[0],
                         {"cyclomatic": 10, "function_lines": 20})

    def test_k9_list_config_uses_defaults(self) -> None:
        _write(self.root, ".cornerstone/config.yaml", "- a\n- b\n")
        self.assertEqual(repo_rules.complexity_limits(self.root),
                         ({"cyclomatic": 10, "function_lines": 60}, ("src/",)))

    def test_k9_non_dict_limits_and_paths_use_defaults(self) -> None:
        _write(self.root, ".cornerstone/config.yaml", "limits: 5\npaths: [a]\n")
        self.assertEqual(repo_rules.complexity_limits(self.root),
                         ({"cyclomatic": 10, "function_lines": 60}, ("src/",)))


NOLIM = {**LIM, "function_lines": 99}


class SameNameTests(unittest.TestCase):
    def test_k9_setter_over_limit_found_once(self) -> None:
        text = ("class C:\n"
                "    @property\n"
                "    def v(self):\n"
                "        return 1\n"
                "\n"
                "    @v.setter\n"
                "    def v(self, x):\n"
                + "".join(f"        if x == {i}:\n            pass\n" for i in range(3)))
        lines = set(range(7, len(text.splitlines()) + 1))
        out = repo_rules.function_problems(text, lines, NOLIM)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], 7)
        self.assertIn("'C.v'", out[0][1])

    def test_k9_setter_not_worse_than_old_passes(self) -> None:
        text = ("class C:\n    @property\n    def v(self):\n        return 1\n\n"
                "    @v.setter\n    def v(self, x):\n"
                + "".join(f"        if x == {i}:\n            pass\n" for i in range(3)))
        new = text + "        return None\n"
        self.assertEqual(repo_rules.function_problems(
            new, {len(new.splitlines())}, NOLIM, text), [])

    def test_k9_conditional_second_def_over_limit_found(self) -> None:
        text = ("if cond:\n    def g():\n        return 1\nelse:\n"
                + "".join(f"    {line}\n" for line in _branchy(3, "g").splitlines()))
        out = repo_rules.function_problems(text, set(range(1, len(text.splitlines()) + 1)),
                                           NOLIM)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], 5)
        self.assertIn("'g'", out[0][1])


class FunctionLengthTests(unittest.TestCase):
    def test_k9_decorators_not_counted(self) -> None:
        text = "@a\n@b\ndef f():\n" + "    pass\n" * 7  # def line + 7 = 8 lines
        self.assertEqual(repo_rules.function_problems(text, {4}, LIM), [])

    def test_k9_docstring_and_comment_lines_counted(self) -> None:
        text = ('def f():\n    """Doc.\n\n    More.\n    """\n    # note\n'
                "    pass\n    pass\n    pass\n")  # 9 lines
        out = repo_rules.function_problems(text, {7}, LIM)
        self.assertEqual(len(out), 1)
        self.assertIn("9 lines", out[0][1])

    def test_k9_function_lines_increase_on_old_over_limit_fails(self) -> None:
        old = "def f():\n" + "    pass\n" * 9  # 10 lines
        new = old + "    pass\n"  # 11 lines
        out = repo_rules.function_problems(new, {11}, LIM, old)
        self.assertEqual(len(out), 1)
        self.assertIn("(it was 10)", out[0][1])

    def test_k9_function_lines_same_on_old_over_limit_passes(self) -> None:
        old = "def f():\n" + "    pass\n" * 9
        new = old.replace("pass", "return", 1)
        self.assertEqual(repo_rules.function_problems(new, {2}, LIM, old), [])


class MergeBaseTextTests(GitRepoCase):
    """check_complexity must pass the text at the merge base on to the pairing."""

    def k9(self) -> list:
        return repo_rules.check_complexity(self.root, "main")

    def start_from(self, path: str, text: str) -> None:
        """Commit `text` at `path`, make it the new `main`, and branch again."""
        _write(self.root, path, text)
        self.commit("feat: old")
        _git(self.root, "checkout", "-q", "-B", "main", "HEAD")
        _git(self.root, "checkout", "-q", "-b", "feature2")

    def test_k9_old_over_limit_unchanged_complexity_passes(self) -> None:
        self.start_from("src/a.py", _branchy(11))
        _write(self.root, "src/a.py", _branchy(11).replace("return x", "return x + 1"))
        self.commit("fix: line")
        self.assertEqual(self.k9(), [])

    def test_k9_old_over_limit_made_worse_fails(self) -> None:
        self.start_from("src/a.py", _branchy(11))
        _write(self.root, "src/a.py", _branchy(12))
        self.commit("fix: worse")
        out = self.k9()
        self.assertEqual(len(out), 1)
        self.assertIn("(it was 12)", out[0].message)

    def test_k9_moved_file_old_over_limit_not_worse_passes(self) -> None:
        self.start_from("src/a.py", _branchy(11))
        _git(self.root, "mv", "src/a.py", "src/b.py")
        _write(self.root, "src/b.py", _branchy(11).replace("return x", "return x + 1"))
        self.commit("refactor: move")
        self.assertEqual(self.k9(), [])

    def test_k9_moved_file_made_worse_fails(self) -> None:
        self.start_from("src/a.py", _branchy(11))
        _git(self.root, "mv", "src/a.py", "src/b.py")
        _write(self.root, "src/b.py", _branchy(12))
        self.commit("refactor: move and worsen")
        out = self.k9()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].path, "src/b.py")
        self.assertIn("(it was 12)", out[0].message)

    def test_k9_noprefix_config_still_finds_worse_function(self) -> None:
        _git(self.root, "config", "diff.noprefix", "true")
        self.start_from("src/a.py", _branchy(11))
        _write(self.root, "src/a.py", _branchy(12))
        self.commit("fix: worse")
        out = self.k9()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].path, "src/a.py")

    def test_k9_setter_old_over_limit_not_worse_passes(self) -> None:
        text = ("class C:\n    @property\n    def v(self):\n        return 1\n\n"
                "    @v.setter\n    def v(self, x):\n"
                + "".join(f"        if x == {i}:\n            pass\n" for i in range(11)))
        self.start_from("src/a.py", text)
        _write(self.root, "src/a.py", text.replace("if x == 0", "if x == 100"))
        self.commit("fix: setter")
        out = self.k9()
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
