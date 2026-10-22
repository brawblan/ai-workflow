"""Tests for issue #119 and D56: a glob in `paths.tests` and `paths.checks`.

The tests render a temp repo with the real framework, as test_render.py does. Then they run the
rendered hook (.cornerstone/hooks/protect-paths.py) and the rendered K6
(.cornerstone/checks/protected_paths.py) as subprocesses. They do not import the match function.

The rules (owner choice, issue #119):
- A glob starts at the repo root.
- `*`, `?`, `[...]`, and `[!...]` match in one folder level.
- `**` as one level matches any number of levels, also zero.
- A glob also covers each path under a folder that it matches.
- A glob that ends with `/` covers each path under the matched folders.
- A value with no glob character keeps the old prefix rule.
- Render and `stone check` fail on a glob that is not valid, and name the key. They do not test
  that a glob matches a file.
"""

from __future__ import annotations

import ast
import contextlib
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from stone import cli, framework_check, render

REPO = Path(__file__).resolve().parents[2]
FRAMEWORK = REPO / "framework"
TODAY = dt.date(2026, 10, 22)
HOOK = ".cornerstone/hooks/protect-paths.py"
K6 = ".cornerstone/checks/protected_paths.py"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
CONFIG = """framework_version: 0.5.0
harness: claude-code
model_profile: claude-5
profiles: [single-ticket]
branches: {integration: dev, main: main}
commands:
  install: pip install .
  test_unit: python -m unittest
  all_checks: make check
paths:
TESTS
CHECKS
  plans: docs/plans/
owners: {default: octocat}
"""


def config(tests: list[str], checks: list[str]) -> str:
    return (CONFIG.replace("TESTS", f"  tests: {json.dumps(tests)}")
            .replace("CHECKS", f"  checks: {json.dumps(checks)}"))


def old_covers(prefixes: list[str], path: str) -> bool:
    """The match rule before D56 (the main branch): the path, or a path under the folder."""
    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes)


class RenderedRepo(unittest.TestCase):
    """A temp repo with a rendered hook and K6, made once for each class."""

    TESTS: list[str] = []
    CHECKS: list[str] = [".github/workflows/", ".cornerstone/checks/"]

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name).resolve()
        (cls.root / ".cornerstone").mkdir()
        (cls.root / ".cornerstone" / "config.yaml").write_text(
            config(cls.TESTS, cls.CHECKS), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            result = render.render(cls.root, FRAMEWORK, today=TODAY)
        assert result.exit_code == 0, result
        cls.git("init", "-q", "-b", "main")
        cls.commit({"README.md": "base\n"}, "chore: base\n\nRole: generator")
        cls.git("add", "-A")
        cls.git("commit", "-qm", "chore: render\n\nRole: generator")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.folder.cleanup()

    @classmethod
    def git(cls, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cls.root, check=True, capture_output=True,
                              text=True, env={**os.environ, **GIT_ENV}).stdout

    @classmethod
    def commit(cls, files: dict[str, str], message: str) -> None:
        for path, text in files.items():
            (cls.root / path).parent.mkdir(parents=True, exist_ok=True)
            (cls.root / path).write_text(text, encoding="utf-8")
            cls.git("add", path)
        cls.git("commit", "-qm", message)

    def hook(self, path: str, role: str, agent_type: str | None = None) -> int:
        """Run the rendered hook for a file-tool edit of path (relative to the root)."""
        event: dict = {"hook_event_name": "PreToolUse", "tool_name": "Write",
                       "tool_input": {"file_path": str(self.root / path)}}
        if agent_type is not None:
            event["agent_type"] = agent_type
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root), "STONE_ROLE": role}
        return subprocess.run([sys.executable, "-B", HOOK], cwd=self.root,
                              input=json.dumps(event), env=env, capture_output=True,
                              text=True).returncode

    def hook_codes(self, paths: list[str], role: str) -> dict[str, int]:
        with ThreadPoolExecutor(max_workers=8) as pool:
            return dict(zip(paths, pool.map(lambda p: self.hook(p, role), paths)))

    def k6(self, base: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", K6, base], cwd=self.root,
                              capture_output=True, text=True)

    @staticmethod
    def named(output: str) -> set[str]:
        return set(re.findall(r"changes (\S+), a protected path", output))

    def k6_named_for_an_implementer_commit(self, paths: list[str]) -> set[str]:
        """Commit each path with no Role trailer on a new branch, run K6, and go back."""
        base = self.git("rev-parse", "HEAD").strip()
        branch = f"probe-{len(paths)}-{abs(hash(tuple(paths)))}"
        self.git("checkout", "-q", "-b", branch)
        try:
            self.commit({p: f"{p}\n" for p in paths}, "feat: change files")
            run = self.k6(base)
            named = self.named(run.stdout)
            self.assertEqual(run.returncode, 1 if named else 0, run.stdout + run.stderr)
            return named
        finally:
            self.git("checkout", "-q", "-f", "main")
            self.git("clean", "-fdq")


# Each value shows one rule. The probes below keep each value apart from the others.
GLOB_TESTS = [
    "*.test.js",          # starts at the repo root
    "src/*_spec.rb",      # * in one level
    "lib/?.py",           # ? is one character
    "q?z",                # ? does not match /
    "lib/[ab].go",        # [...]
    "lib/[!ab].rs",       # [!...]
    "lib/[x-z].c",        # a range in [...]
    "**/*.spec.ts",       # ** as the first level: zero or more levels
    "src/**/*.spec.js",   # ** in the middle
    "pkg/**/fixtures",    # ** in the middle, and a matched folder covers its paths
    "app/*/spec",         # a matched folder covers each path under it
    "e2e*/",              # ends with /: each path under a matched folder
    "web/**.vue",         # ** inside a level is not a ** level
    "tests/",             # no glob character: the prefix rule
]
GLOB_CHECKS = [".github/workflows/", ".cornerstone/checks/", "ci/*.yml", "tools/lint.sh"]
COVERED_BY_TESTS = [
    "a.test.js",
    "src/x_spec.rb",
    "lib/a.py",
    "qaz",
    "lib/a.go", "lib/b.go",
    "lib/c.rs",
    "lib/y.c",
    "b.spec.ts", "src/deep/er/c.spec.ts",
    "src/a.spec.js", "src/x/y/a.spec.js",
    "pkg/fixtures/data.json", "pkg/a/b/fixtures/data.json",
    "app/users/spec/user_spec.rb", "app/users/spec/deep/x.rb",
    "e2e/login.js", "e2e-web/a/b.js",
    "web/App.vue",
    "tests/test_a.py",
]
COVERED_BY_CHECKS = ["ci/build.yml", "tools/lint.sh"]
NOT_COVERED = [
    "src/a.test.js",           # *.test.js starts at the root
    "src/a/x_spec.rb",         # * does not cross a folder
    "src/x_spec.rbx",          # the glob matches the full level
    "lib/ab.py",               # ? is one character
    "q/z",                     # ? does not match /
    "lib/c.go",                # not in [ab]
    "lib/a.rs",                # in [!ab]
    "lib/w.c",                 # not in [x-z]
    "a.spec.tsx",
    "lib/a.spec.js",           # src/**/ starts at src
    "pkg/fixtures_old/x.json",
    "pkgs/fixtures/x.json",
    "app/spec/x.rb",           # app/*/spec needs one level between
    "app/users/specs/x.rb",
    "e2e-notes.md",            # e2e*/ covers only paths under a folder
    "web/components/App.vue",  # ** inside a level is one level
    "testsuite/a.py",          # prefix rule: not only the same letters
    "tests.py",
    "ci/sub/build.yml",
    "tools/lint.sh.bak",
    "src/widget.js",
]


class GlobRulesTest(RenderedRepo):
    """Criterion 1: the match rules, through the rendered hook and K6."""

    TESTS = GLOB_TESTS
    CHECKS = GLOB_CHECKS

    def test_hook_blocks_the_implementer_on_each_covered_path_only(self) -> None:
        codes = self.hook_codes(COVERED_BY_TESTS + COVERED_BY_CHECKS + NOT_COVERED, "implementer")
        for path in COVERED_BY_TESTS + COVERED_BY_CHECKS:
            with self.subTest(path=path):
                self.assertEqual(codes[path], 2, f"{path} must be protected")
        for path in NOT_COVERED:
            with self.subTest(path=path):
                self.assertEqual(codes[path], 0, f"{path} must not be protected")

    def test_hook_allows_the_tester_only_on_each_test_path(self) -> None:
        codes = self.hook_codes(COVERED_BY_TESTS + COVERED_BY_CHECKS + NOT_COVERED, "tester")
        for path in COVERED_BY_TESTS:
            with self.subTest(path=path):
                self.assertEqual(codes[path], 0, f"{path} is a test path")
        for path in COVERED_BY_CHECKS + NOT_COVERED:
            with self.subTest(path=path):
                self.assertEqual(codes[path], 2, f"{path} is not a test path")

    def test_hook_allows_the_tester_on_a_new_file_in_a_new_folder(self) -> None:
        # The glob matches a path, not a file on disk.
        self.assertFalse((self.root / "src/brand/new").exists())
        self.assertEqual(self.hook("src/brand/new/n.spec.ts", "tester"), 0)
        self.assertEqual(self.hook("src/brand/new/n.spec.ts", "implementer"), 2)

    def test_k6_names_each_covered_path_of_an_implementer_commit(self) -> None:
        named = self.k6_named_for_an_implementer_commit(
            COVERED_BY_TESTS + COVERED_BY_CHECKS + NOT_COVERED)
        self.assertEqual(named, set(COVERED_BY_TESTS + COVERED_BY_CHECKS))

    def test_k6_passes_a_tester_commit_to_glob_test_paths(self) -> None:
        base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "-b", "tester-commit")
        try:
            self.commit({p: "x\n" for p in COVERED_BY_TESTS}, "test: add tests\n\nRole: tester")
            run = self.k6(base)
            self.assertEqual(run.returncode, 0, run.stdout)
        finally:
            self.git("checkout", "-q", "-f", "main")
            self.git("clean", "-fdq")

    def test_hook_starts_a_glob_at_the_worktree_root(self) -> None:
        # A linked worktree gets the same rules: the path is relative to its work tree.
        self.git("worktree", "add", "-q", "-b", "wt-glob", ".claude/worktrees/wt")
        self.addCleanup(self.git, "worktree", "remove", "--force", ".claude/worktrees/wt")
        tree = ".claude/worktrees/wt/"
        self.assertEqual(self.hook(tree + "src/x/a.spec.js", "tester"), 0)
        self.assertEqual(self.hook(tree + "a.test.js", "tester"), 0)
        self.assertEqual(self.hook(tree + "src/a.test.js", "tester"), 2)
        self.assertEqual(self.hook(tree + "src/x/a.spec.js", "implementer"), 2)
        self.assertEqual(self.hook(tree + "src/x/a.js", "implementer"), 0)


NO_GLOB_TESTS = ["tests/", "spec/helper.rb", "test.d/", "it"]
NO_GLOB_CHECKS = [".github/workflows/", ".cornerstone/checks/", "ci"]
NO_GLOB_PROBES = [
    "tests/test_a.py", "tests/deep/b.py", "tests",
    "testsuite/a.py", "tests.py", "test/a.py",
    "spec/helper.rb", "spec/helper.rb.bak", "spec/helper.rbx", "spec/other.rb",
    "test.d/a.py", "testXd/a.py",
    "it/a.py", "it", "items/a.py",
    "ci/x.yml", "ci", "cix/x.yml",
    "src/a.py",
]


class NoGlobTest(RenderedRepo):
    """Criterion 2: a config with no glob gives the same decisions as before."""

    TESTS = NO_GLOB_TESTS
    CHECKS = NO_GLOB_CHECKS

    def protected(self) -> list[str]:
        return [".claude/", ".cornerstone/", *NO_GLOB_CHECKS, *NO_GLOB_TESTS]

    def test_hook_gives_the_old_implementer_decisions(self) -> None:
        codes = self.hook_codes(NO_GLOB_PROBES, "implementer")
        for path in NO_GLOB_PROBES:
            with self.subTest(path=path):
                self.assertEqual(codes[path], 2 if old_covers(self.protected(), path) else 0)

    def test_hook_gives_the_old_tester_decisions(self) -> None:
        codes = self.hook_codes(NO_GLOB_PROBES, "tester")
        for path in NO_GLOB_PROBES:
            with self.subTest(path=path):
                self.assertEqual(codes[path], 0 if old_covers(NO_GLOB_TESTS, path) else 2)

    def test_the_prefix_rule_covers_a_folder_and_an_exact_file_only(self) -> None:
        # The expected values written out, so that the old rule above is not the only oracle.
        codes = self.hook_codes(NO_GLOB_PROBES, "implementer")
        blocked = {p for p, code in codes.items() if code == 2}
        self.assertEqual(blocked, {"tests/test_a.py", "tests/deep/b.py", "tests",
                                   "spec/helper.rb", "test.d/a.py", "it/a.py", "it",
                                   "ci/x.yml", "ci"})

    def test_k6_gives_the_old_decisions(self) -> None:
        files = [p for p in NO_GLOB_PROBES if p not in ("tests", "it", "ci")]
        named = self.k6_named_for_an_implementer_commit(files)
        self.assertEqual(named, {p for p in files if old_covers(self.protected(), p)})
        self.assertEqual(named, {"tests/test_a.py", "tests/deep/b.py", "spec/helper.rb",
                                 "test.d/a.py", "it/a.py", "ci/x.yml"})


class ColocatedTest(RenderedRepo):
    """Criterion 1, the colocated case of issue #119: each test file is next to its source."""

    TESTS = ["**/*.test.js"]

    def test_hook_blocks_the_implementer_on_the_colocated_test_file(self) -> None:
        self.assertEqual(self.hook("src/widget/widget.test.js", "implementer"), 2)
        self.assertEqual(self.hook("src/widget/widget.test.js", "", agent_type="implementer"), 2)

    def test_hook_allows_the_tester_on_the_colocated_test_file(self) -> None:
        self.assertEqual(self.hook("src/widget/widget.test.js", "tester"), 0)
        self.assertEqual(self.hook("src/widget/widget.test.js", "", agent_type="tester"), 0)
        self.assertEqual(self.hook("src/other/other.test.js", "tester"), 0)

    def test_hook_allows_the_implementer_on_the_source_file(self) -> None:
        self.assertEqual(self.hook("src/widget/widget.js", "implementer"), 0)
        self.assertEqual(self.hook("src/widget/widget.js", "", agent_type="implementer"), 0)

    def test_hook_blocks_the_tester_on_the_source_file(self) -> None:
        self.assertEqual(self.hook("src/widget/widget.js", "tester"), 2)

    def test_k6_fails_an_implementer_commit_to_the_colocated_test_file(self) -> None:
        base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "-b", "colocated")
        self.addCleanup(self.git, "clean", "-fdq")
        self.addCleanup(self.git, "checkout", "-q", "-f", "main")
        self.commit({"src/widget/widget.js": "export const a = 1;\n"}, "feat: widget")
        self.commit({"src/widget/widget.test.js": "test\n"}, "test: widget\n\nRole: tester")
        run = self.k6(base)
        self.assertEqual(run.returncode, 0, run.stdout)
        self.commit({"src/widget/widget.test.js": "changed\n"},
                    "fix: widget test\n\nRole: implementer")
        run = self.k6(base)
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertEqual(self.named(run.stdout), {"src/widget/widget.test.js"})

    def test_k6_fails_a_commit_with_no_role_trailer_to_the_colocated_test_file(self) -> None:
        base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "-b", "colocated-no-role")
        self.addCleanup(self.git, "clean", "-fdq")
        self.addCleanup(self.git, "checkout", "-q", "-f", "main")
        self.commit({"src/widget/widget.test.js": "changed\n"}, "fix: widget test")
        run = self.k6(base)
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertEqual(self.named(run.stdout), {"src/widget/widget.test.js"})


def match_function_text(path: Path) -> dict[str, str]:
    """Return the source of `covers` and of each top-level name that it uses, by name."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    nodes: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            nodes[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    nodes[target.id] = node
    found: dict[str, str] = {}
    todo = ["covers"]
    while todo:
        name = todo.pop()
        if name in found or name not in nodes:
            continue
        found[name] = ast.get_source_segment(text, nodes[name]) or ""
        todo += [sub.id for sub in ast.walk(nodes[name]) if isinstance(sub, ast.Name)]
    return found


class SameMatchFunctionTest(RenderedRepo):
    """Criterion 3: the hook and K6 have the same match function text."""

    TESTS = ["**/*.test.js", "tests/"]

    def assert_same(self, hook: Path, k6: Path) -> None:
        in_hook, in_k6 = match_function_text(hook), match_function_text(k6)
        self.assertIn("covers", in_hook)
        self.assertIn("covers", in_k6)
        self.assertEqual(in_hook, in_k6)

    def test_rendered_hook_and_k6_have_the_same_match_function(self) -> None:
        self.assert_same(self.root / HOOK, self.root / K6)

    def test_the_files_of_this_repo_have_the_same_match_function(self) -> None:
        self.assert_same(REPO / HOOK, REPO / K6)


class InvalidGlobTest(unittest.TestCase):
    """Criterion 4: render and `stone check` fail on a glob that is not valid, and name the key."""

    BAD_TESTS = {"[ with no ]": "src/[ab.test.js",
                 "leading / with a glob": "/src/**/*.test.js"}
    BAD_CHECKS = {"[ with no ]": "[ci/*.yml",
                  "leading / with a glob": "/ci/*.yml"}

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def configure(self, tests: list[str], checks: list[str] | None = None) -> None:
        checks = checks if checks is not None else [".github/workflows/"]
        (self.root / ".cornerstone" / "config.yaml").write_text(config(tests, checks),
                                                                encoding="utf-8")

    def render_error(self) -> str:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(render.RenderError) as caught:
                render.render(self.root, FRAMEWORK, today=TODAY)
        return str(caught.exception)

    def glob_findings(self) -> list[str]:
        return [f.message for f in framework_check.check_config(self.root, FRAMEWORK)
                if "paths." in f.message]

    def test_render_fails_and_names_paths_tests(self) -> None:
        for label, value in self.BAD_TESTS.items():
            with self.subTest(case=label):
                self.configure(["tests/", value])
                message = self.render_error()
                self.assertIn("paths.tests", message)
                self.assertNotIn("paths.checks", message)
                self.assertFalse((self.root / HOOK).exists())
                self.assertFalse((self.root / K6).exists())
                self.assertFalse((self.root / ".claude").exists())

    def test_render_fails_and_names_paths_checks(self) -> None:
        for label, value in self.BAD_CHECKS.items():
            with self.subTest(case=label):
                self.configure(["tests/"], [".github/workflows/", value])
                message = self.render_error()
                self.assertIn("paths.checks", message)
                self.assertNotIn("paths.tests", message)
                self.assertFalse((self.root / HOOK).exists())

    def test_cli_render_exits_1_and_names_the_key(self) -> None:
        self.configure(["src/[ab.test.js"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["render", "--root", str(self.root), "--framework", str(FRAMEWORK)])
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("paths.tests", out.getvalue())

    def test_check_reports_an_error_that_names_paths_tests(self) -> None:
        for label, value in self.BAD_TESTS.items():
            with self.subTest(case=label):
                self.configure(["tests/", value])
                findings = framework_check.check_config(self.root, FRAMEWORK)
                named = [f for f in findings if "paths.tests" in f.message]
                self.assertEqual(len(named), 1, [f.message for f in findings])
                self.assertEqual(named[0].severity, "error")

    def test_check_reports_an_error_that_names_paths_checks(self) -> None:
        for label, value in self.BAD_CHECKS.items():
            with self.subTest(case=label):
                self.configure(["tests/"], [".github/workflows/", value])
                findings = framework_check.check_config(self.root, FRAMEWORK)
                named = [f for f in findings if "paths.checks" in f.message]
                self.assertEqual(len(named), 1, [f.message for f in findings])
                self.assertEqual(named[0].severity, "error")

    def test_check_names_each_key_when_both_have_a_bad_glob(self) -> None:
        self.configure(["src/[ab.test.js"], ["[ci/*.yml"])
        text = " ".join(self.glob_findings())
        self.assertIn("paths.tests", text)
        self.assertIn("paths.checks", text)

    def test_cli_check_exits_1_and_names_the_key(self) -> None:
        self.configure(["tests/"], [".github/workflows/", "[ci/*.yml"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["check", "--root", str(self.root), "--framework", str(FRAMEWORK)])
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("paths.checks", out.getvalue())

    def test_a_valid_glob_that_matches_no_file_is_not_an_error(self) -> None:
        self.configure(["**/*.test.js", "nothing/*/here/", "lib/[!x]?.py"], [".github/workflows/"])
        self.assertFalse(any(self.root.glob("**/*.test.js")))
        self.assertEqual(self.glob_findings(), [])
        with contextlib.redirect_stderr(io.StringIO()):
            result = render.render(self.root, FRAMEWORK, today=TODAY)
        self.assertEqual(result.exit_code, 0)
        self.assertTrue((self.root / HOOK).exists())

    def test_a_config_with_no_glob_has_no_glob_finding(self) -> None:
        self.configure(["tests/", "spec/helper.rb"], [".github/workflows/", "ci"])
        self.assertEqual(self.glob_findings(), [])


if __name__ == "__main__":
    unittest.main()
