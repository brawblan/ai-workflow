"""Tests for K24, the unpinned tool check (D93), and the `stone check-workflows` command."""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from stone import workflow_check
from stone.cli import main

GIT = ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
SHA = "0123456789abcdef0123456789abcdef01234567"
WF = ".github/workflows/ci.yml"


def found(text: str) -> list[int]:
    """Return the line numbers of the findings for a workflow text."""
    return [f.line for f in workflow_check.file_findings(WF, text)]


def run_line(command: str) -> str:
    return f"jobs:\n  a:\n    steps:\n      - run: {command}\n"


def body(section: str = "") -> str:
    return f"## Summary\n\nA change.\n\n{section}\n## Risks\n\nNone.\n"


class UsesTest(unittest.TestCase):
    def test_r1_unpinned_action_is_found(self) -> None:
        for ref in ("actions/checkout@v4", "actions/checkout@main", "a/b@" + SHA[:39],
                    "a/b@" + SHA + "0", "a/b"):
            with self.subTest(ref=ref):
                self.assertEqual(found(f"steps:\n  - uses: {ref}\n"), [2])

    def test_r1_pinned_or_local_action_is_not_found(self) -> None:
        for ref in (f"actions/checkout@{SHA} # v4", "./local-action", "./.github/actions/x",
                    f"docker://x@sha256:{'a' * 64}"):
            with self.subTest(ref=ref):
                self.assertEqual(found(f"steps:\n  - uses: {ref}\n"), [])

    def test_r1_quoted_and_nested_uses(self) -> None:
        self.assertEqual(found("steps:\n  - uses: 'a/b@v1'\n"), [2])
        self.assertEqual(found("steps:\n  - name: x\n    uses: \"a/b@v1\"\n"), [3])

    def test_r1_docker_image_without_digest_is_found(self) -> None:
        self.assertEqual(found("steps:\n  - uses: docker://alpine:3.19\n"), [2])

    def test_r1_comment_gives_no_finding(self) -> None:
        self.assertEqual(found("# - uses: a/b@v1\n  # curl x | bash\n"), [])
        self.assertEqual(found("steps:\n      # pip install requests\n"), [])


class DownloadTest(unittest.TestCase):
    def test_r2_download_piped_to_a_shell_is_found(self) -> None:
        for command in ("curl -fsSL https://x.sh | bash", "wget -qO- https://x.sh | sh",
                        "curl https://x.sh | sudo bash", "curl https://x.sh | sudo -E bash -s",
                        "bash <(curl -s https://x.sh)", "curl https://x | zsh",
                        "curl https://x | python3"):
            with self.subTest(command=command):
                self.assertEqual(found(run_line(command)), [4])

    def test_r2_download_to_a_file_is_not_found(self) -> None:
        for command in ("curl -fsSL -o x.sh https://x.sh", "curl https://x | tee out",
                        "echo hi | bash"):
            with self.subTest(command=command):
                self.assertEqual(found(run_line(command)), [])


class PipTest(unittest.TestCase):
    def test_r3_package_without_version_is_found(self) -> None:
        for command in ("pip install requests", "pip3 install requests",
                        "python -m pip install requests", "python3 -m pip install requests",
                        "uv pip install requests", "pipx install requests",
                        '"${RUNNER_TEMP}/stone/bin/pip" install requests',
                        "${RUNNER_TEMP}/stone/bin/pip install requests",
                        "pip install requests>=2", "pip install --upgrade requests"):
            with self.subTest(command=command):
                self.assertEqual(found(run_line(command)), [4])

    def test_r3_pinned_or_local_is_not_found(self) -> None:
        for command in ("pip install requests==2.31.0", "pip install -r requirements.txt",
                        "pip install -c constraints.txt -r r.txt", "pip install ./x",
                        "pip install .", "pip install -e .", "pip install ../pkg",
                        "pip install --require-hashes -r r.txt", "pip install a --require-hashes",
                        "pip install --require-hashes a b",
                        f"pip install git+https://github.com/o/r@{SHA}",
                        f'pip install "stone @ git+https://github.com/o/r@{SHA}#subdirectory=x"',
                        "pip install $UNSET_VAR", "pip install ${{ matrix.pkg }}",
                        "pip install pkg==1.2 # note"):
            with self.subTest(command=command):
                self.assertEqual(found(run_line(command)), [])

    def test_r3_git_tag_url_is_found(self) -> None:
        self.assertEqual(found(run_line("pip install git+https://github.com/o/r@v1.4.0")), [4])
        self.assertEqual(found(run_line("pip install git+https://github.com/o/r")), [4])

    def test_r3_second_package_without_version_is_found(self) -> None:
        self.assertEqual(len(workflow_check.file_findings(WF, run_line("pip install a==1 b"))), 1)

    def test_r3_env_key_resolves_the_variable(self) -> None:
        text = ("env:\n  STONE_REF: %s\nsteps:\n  - run: pip install "
                "git+https://github.com/o/r@${STONE_REF}\n")
        self.assertEqual(found(text % SHA), [])
        self.assertEqual(found(text % "v1.4.0"), [4])
        self.assertEqual(found((text % SHA).replace("${STONE_REF}", "$STONE_REF")), [])

    def test_r3_continuation_lines_are_joined_and_use_the_first_line(self) -> None:
        text = "steps:\n  - run: |\n      pip install \\\n        requests\n      echo done\n"
        self.assertEqual(found(text), [3])
        pinned = "steps:\n  - run: |\n      pip install \\\n        requests==1\n"
        self.assertEqual(found(pinned), [])
        both = "steps:\n  - run: |\n      pip install \\\n        --require-hashes \\\n        a\n"
        self.assertEqual(found(both), [])

    def test_r3_two_commands_on_a_line(self) -> None:
        self.assertEqual(len(workflow_check.file_findings(
            WF, run_line("pip install a && pip install b"))), 2)


class NodeTest(unittest.TestCase):
    def test_r4_runner_without_version_is_found(self) -> None:
        for command in ("npx prettier --write .", "bunx prettier", "pnpm dlx prettier",
                        "yarn dlx prettier", "npx @scope/a@latest", "npx --yes prettier",
                        "npx prettier@latest"):
            with self.subTest(command=command):
                self.assertEqual(found(run_line(command)), [4])

    def test_r4_runner_with_version_is_not_found(self) -> None:
        for command in ("npx prettier@3.1.0 --write .", "npx -p @scope/a@1.0.0 cmd",
                        "npx @scope/a@1.0.0", "pnpm dlx prettier@3.1.0 --check"):
            with self.subTest(command=command):
                self.assertEqual(found(run_line(command)), [])

    def test_r4_only_the_first_package_counts(self) -> None:
        self.assertEqual(found(run_line("npx prettier@3.1.0 other --flag")), [])
        self.assertEqual(len(workflow_check.file_findings(
            WF, run_line("npx prettier other"))), 1)

    def test_r5_global_install_without_version_is_found(self) -> None:
        for command in ("npm install -g typescript", "npm i --global typescript",
                        "pnpm add -g typescript", "yarn global add typescript",
                        "npm install typescript -g"):
            with self.subTest(command=command):
                self.assertEqual(found(run_line(command)), [4])

    def test_r5_pinned_global_or_project_install_is_not_found(self) -> None:
        for command in ("npm install -g typescript@5.4.0", "yarn global add typescript@1.22.0",
                        "npm ci", "npm install", "npm install left-pad", "pnpm install",
                        "pnpm add left-pad"):
            with self.subTest(command=command):
                self.assertEqual(found(run_line(command)), [])


class GoTest(unittest.TestCase):
    def test_r6_unpinned_go_install_is_found(self) -> None:
        for command in ("go install example.com/x@latest", "go install example.com/x",
                        "go install example.com/x@main"):
            with self.subTest(command=command):
                self.assertEqual(found(run_line(command)), [4])

    def test_r6_pinned_or_local_go_install_is_not_found(self) -> None:
        for command in ("go install example.com/x@v0.1.0", f"go install example.com/x@{SHA}",
                        "go install ./...", "go install -v ./cmd/x"):
            with self.subTest(command=command):
                self.assertEqual(found(run_line(command)), [])


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
        self.write({"README.md": "x\n", **base})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.write(head)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "head")


BAD = "steps:\n  - uses: a/b@v1\n"
OK = f"steps:\n  - uses: a/b@{SHA}\n"


class ScopeTest(RepoCase):
    def paths(self, base: str | None) -> list[str]:
        return sorted({f.path for f in workflow_check.check(self.root, base, body())})

    def test_r7_only_added_or_changed_workflows_are_read(self) -> None:
        self.make({".github/workflows/old.yml": BAD, ".github/workflows/same.yml": BAD},
                  {".github/workflows/new.yml": BAD, ".github/workflows/old.yml": BAD + "# c\n",
                   ".github/workflows/z.yaml": BAD})
        self.assertEqual(self.paths("main"),
                         [".github/workflows/new.yml", ".github/workflows/old.yml",
                          ".github/workflows/z.yaml"])

    def test_r7_other_files_are_not_read(self) -> None:
        self.make({}, {".github/workflows/notes.md": BAD, "ci.yml": BAD,
                       ".github/workflows/sub/x.txt": BAD, ".github/other/x.yml": BAD})
        self.assertEqual(self.paths("main"), [])

    def test_r7_renamed_workflow_is_read(self) -> None:
        self.make({".github/workflows/a.yml": BAD}, {})
        self.git("mv", ".github/workflows/a.yml", ".github/workflows/b.yml")
        self.git("commit", "-q", "-m", "rename")
        self.assertEqual(self.paths("main"), [".github/workflows/b.yml"])

    def test_r7_deleted_workflow_is_not_read(self) -> None:
        self.make({".github/workflows/a.yml": BAD}, {})
        self.git("rm", "-q", ".github/workflows/a.yml")
        self.git("commit", "-q", "-m", "rm")
        self.assertEqual(self.paths("main"), [])

    def test_r7_all_reads_each_tracked_workflow(self) -> None:
        self.make({".github/workflows/old.yml": BAD, ".github/workflows/good.yml": OK},
                  {".github/workflows/new.yaml": BAD})
        self.assertEqual(self.paths(None),
                         [".github/workflows/new.yaml", ".github/workflows/old.yml"])

    def test_r7_finding_has_the_path_line_and_check(self) -> None:
        self.make({}, {".github/workflows/a.yml": "x: 1\n" + BAD})
        (finding,) = workflow_check.check(self.root, "main", body())
        self.assertEqual((finding.path, finding.line, finding.check, finding.severity),
                         (".github/workflows/a.yml", 3, "K24", "error"))

    def test_r7_git_error_raises_runtime_error(self) -> None:
        self.make({}, {})
        with self.assertRaises(RuntimeError):
            workflow_check.check(self.root, "no-such-ref", body())

    def test_r7_not_a_repo_raises_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):
                workflow_check.check(Path(folder), None, body())


class WaiverTest(RepoCase):
    def check(self, text: str):
        self.make({}, {".github/workflows/a.yml": BAD})
        return workflow_check.check(self.root, "main", text)

    def test_r8_waiver_makes_each_finding_a_warning(self) -> None:
        for heading in ("## Waiver (K24)", "### waiver (k24)", "# WAIVER (K24)",
                        "## Waiver (K24): tools"):
            with self.subTest(heading=heading):
                self.setUp()
                findings = self.check(body(f"{heading}\n\nThe tool has no pin yet.\n"))
                self.assertEqual([f.severity for f in findings], ["warning"])

    def test_r8_empty_or_none_waiver_does_not_count(self) -> None:
        for section in ("## Waiver (K24)\n\n", "## Waiver (K24)\n\nNone\n",
                        "## Waiver (K24)\n\nNone.\n", "## Waiver (K23)\n\nText here.\n"):
            with self.subTest(section=section):
                self.setUp()
                findings = self.check(body(section))
                self.assertEqual([f.severity for f in findings], ["error"])

    def test_r8_has_waiver(self) -> None:
        self.assertTrue(workflow_check.has_waiver(body("## Waiver (K24)\n\nReason.\n")))
        self.assertFalse(workflow_check.has_waiver(body()))


class CliTest(RepoCase):
    def run_cli(self, argv: list[str], stdin: str = "") -> tuple[int, str]:
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
        self.make({}, {".github/workflows/a.yml": BAD})

    def test_r9_warn_mode_exits_0_and_prints_findings(self) -> None:
        code, out = self.run_cli(["check-workflows", "-", "--base", "main"], body())
        self.assertEqual(code, 0)
        self.assertIn("K24", out)
        self.assertIn("a/b@v1", out)
        self.assertIn("mode warn", out)

    def test_r9_block_mode_exits_1_with_a_finding(self) -> None:
        code, out = self.run_cli(
            ["check-workflows", "-", "--base", "main", "--mode", "block"], body())
        self.assertEqual(code, 1)
        self.assertIn("1 finding", out)

    def test_r9_block_mode_exits_0_with_no_finding(self) -> None:
        self.write({".github/workflows/a.yml": OK})
        self.git("commit", "-qam", "fix")
        code, out = self.run_cli(
            ["check-workflows", "-", "--base", "main", "--mode", "block"], body())
        self.assertEqual(code, 0)
        self.assertIn("0 finding", out)

    def test_r9_block_mode_with_a_waiver_exits_0_and_prints_a_notice(self) -> None:
        code, out = self.run_cli(
            ["check-workflows", "-", "--base", "main", "--mode", "block"],
            body("## Waiver (K24)\n\nA reason.\n"))
        self.assertEqual(code, 0)
        self.assertIn("notice", out)
        self.assertIn("Waiver (K24)", out)

    def test_r8_no_notice_without_a_waiver(self) -> None:
        _, out = self.run_cli(["check-workflows", "-", "--base", "main"], body())
        self.assertNotIn("notice", out)

    def test_r9_github_format(self) -> None:
        _, out = self.run_cli(
            ["check-workflows", "-", "--base", "main", "--format", "github"], body())
        self.assertIn("::warning", out)
        _, out = self.run_cli(
            ["check-workflows", "-", "--base", "main", "--format", "github", "--mode", "block"],
            body())
        self.assertIn("::error", out)

    def test_r9_all_reads_tracked_workflows(self) -> None:
        code, out = self.run_cli(["check-workflows", "-", "--all", "--mode", "block"], body())
        self.assertEqual(code, 1)
        self.assertIn("a/b@v1", out)

    def test_r9_base_and_all_are_exclusive_and_one_is_required(self) -> None:
        for argv in (["check-workflows", "-", "--base", "main", "--all"], ["check-workflows", "-"]):
            with self.subTest(argv=argv), mock.patch("sys.stderr", io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    self.run_cli(argv, body())
                self.assertEqual(raised.exception.code, 2)

    def test_r9_unreadable_body_file_exits_2(self) -> None:
        code, out = self.run_cli(["check-workflows", "no-such-file.md", "--all"])
        self.assertEqual(code, 2)
        self.assertIn("cannot read", out)

    def test_r9_body_file_is_read(self) -> None:
        self.write({"body.md": body("## Waiver (K24)\n\nA reason.\n")})
        code, out = self.run_cli(
            ["check-workflows", "body.md", "--all", "--mode", "block"])
        self.assertEqual(code, 0)
        self.assertIn("notice", out)

    def test_r7_git_error_exits_2(self) -> None:
        code, out = self.run_cli(["check-workflows", "-", "--base", "no-such-ref"], body())
        self.assertEqual(code, 2)
        self.assertIn("check-workflows:", out)


class OwnOutputTest(unittest.TestCase):
    """K24 passes on the G3 workflow that Cornerstone renders."""

    def test_r10_golden_g3_workflows_with_framework_commit_give_no_finding(self) -> None:
        golden = Path(__file__).resolve().parent / "golden"
        checked = 0
        for path in sorted(golden.glob("**/.github/workflows/cornerstone-checks.yml")):
            text = path.read_text(encoding="utf-8")
            if f"STONE_REF: {SHA}" not in text:
                continue  # no framework_commit: it installs from a tag, and K24 flags that
            checked += 1
            with self.subTest(path=str(path.relative_to(golden))):
                self.assertEqual(workflow_check.file_findings(WF, text), [])
        self.assertGreater(checked, 0)

    def test_r10_rendered_g3_workflow_with_the_k24_step_gives_no_finding(self) -> None:
        import contextlib
        from stone import render
        framework = Path(__file__).resolve().parents[2] / "framework"
        config = (f"framework_version: 1.5.0\nframework_commit: \"{SHA}\"\n"
                  "harness: claude-code\nmodel_profile: claude-5\nprofiles: [single-ticket]\n"
                  "branches: {integration: dev, main: main}\n"
                  "commands:\n  install: pip install .\n  test_unit: python -m unittest\n"
                  "  all_checks: make check\npaths:\n  tests: [tests/]\n"
                  "  checks: [.github/workflows/, .cornerstone/checks/]\n  plans: docs/plans/\n"
                  "owners: {default: octocat}\n")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".cornerstone").mkdir()
            (root / ".cornerstone" / "config.yaml").write_text(config, encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                render.render(root, framework)
            text = (root / ".github/workflows/cornerstone-checks.yml").read_text(encoding="utf-8")
        self.assertIn("check-workflows", text)
        self.assertEqual(workflow_check.file_findings(WF, text), [])


class ReviewFixTest(unittest.TestCase):
    def check(self, commands: list[str], expected: list[int]) -> None:
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(found(run_line(command)), expected)

    def test_f1_full_version_is_needed(self) -> None:
        self.check(["npx prettier@3", "npm install -g pnpm@9", "npx x@1.x",
                    "go install example.com/x@v1", "go install example.com/x@v1.2"], [4])
        self.check(["npx prettier@3.1.0", "npm install -g foo@1.22.0 ",
                    "go install example.com/x@v0.0.0-20200101000000-abcdef123456",
                    f"go install example.com/x@{SHA}"], [])

    def test_f2_redirections_are_not_packages(self) -> None:
        self.check(["pip install -q -r req.txt > pip.log", "npm install -g foo@1.0.0 >/dev/null",
                    "pip install foo==1 2>&1"], [])

    def test_f3_trailing_operator_joins_the_next_line(self) -> None:
        for end in ("|", "&&", "||"):
            with self.subTest(end=end):
                text = f"steps:\n  - run: |\n      curl -fsSL https://x/i.sh {end}\n        bash\n"
                self.assertEqual(found(text) if end == "|" else found(
                    text.replace("curl -fsSL https://x/i.sh", "true").replace(
                        "bash", "pip install foo")), [3])
        self.assertEqual(found("steps:\n  - run: |\n      echo hi\n"), [])

    def test_f4_url_hash_in_the_query_is_not_a_pin(self) -> None:
        self.check(["pip install https://e/p.tar.gz?sha256=1"], [4])
        self.check(["pip install https://e/p.tar.gz#sha256=abc"], [])

    def test_f5_option_before_the_subcommand(self) -> None:
        self.check(["pip -q install foo", "python -m pip --disable-pip-version-check install foo",
                    "npm -g install foo"], [4])

    def test_f6_local_and_unrelated_lines_are_not_found(self) -> None:
        self.check(["pip install dist/*.whl", "pip install stone/", "pip install x.whl",
                    "uv pip install -p 3.12 foo==1", "go install -tags netgo ./cmd/x"], [])
        self.assertEqual(found("steps:\n  - name: pip install requirements\n"), [])


if __name__ == "__main__":
    unittest.main()
