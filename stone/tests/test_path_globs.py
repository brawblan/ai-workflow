"""Tests for issue #119 and D62: a glob in `paths.tests` and `paths.checks`.

The tests render a temp repo with the real framework, as test_render.py does. Then they run the
rendered hook (.cornerstone/hooks/protect-paths.py) and the rendered K6
(.cornerstone/checks/protected_paths.py) as subprocesses. They do not import the match function.
The hook and K6 import `covers` from one rendered module, .cornerstone/lib/path_match.py (D62).

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
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from path_match_helpers import FRAMEWORK, HOOK, K6, PATH_MATCH, REPO, prefix_only_covers
from stone import cli, framework_check, render

TODAY = dt.date(2026, 10, 22)
TEMPLATE = FRAMEWORK / "adapters" / "claude-code" / "templates" / "lib" / "path_match.py"
GOLDEN = Path(__file__).resolve().parent / "golden"
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

    @classmethod
    def run_hook(cls, path: str, role: str, agent_type: str | None = None,
                 cwd: Path | None = None) -> subprocess.CompletedProcess:
        """Run the rendered hook for a file-tool edit of path (relative to the root)."""
        event: dict = {"hook_event_name": "PreToolUse", "tool_name": "Write",
                       "tool_input": {"file_path": str(cls.root / path)}}
        if agent_type is not None:
            event["agent_type"] = agent_type
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(cls.root), "STONE_ROLE": role}
        return subprocess.run([sys.executable, "-B", str(cls.root / HOOK)],
                              cwd=cwd or cls.root, input=json.dumps(event), env=env,
                              capture_output=True, text=True)

    def hook(self, path: str, role: str, agent_type: str | None = None) -> int:
        return self.run_hook(path, role, agent_type).returncode

    def hook_codes(self, paths: list[str], role: str) -> dict[str, int]:
        with ThreadPoolExecutor(max_workers=8) as pool:
            return dict(zip(paths, pool.map(lambda p: self.hook(p, role), paths)))

    def k6(self, base: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", K6, base], cwd=self.root,
                              capture_output=True, text=True)

    @contextlib.contextmanager
    def new_branch(self, name: str) -> Iterator[str]:
        """Check out a new branch from main, give the base commit, then go back to a clean main."""
        base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-q", "-b", name)
        try:
            yield base
        finally:
            self.git("checkout", "-q", "-f", "main")
            self.git("clean", "-fdq")

    @staticmethod
    def named(output: str) -> set[str]:
        return set(re.findall(r"changes (\S+), a protected path", output))

    def k6_named_for_an_implementer_commit(self, paths: list[str]) -> set[str]:
        """Commit each path with no Role trailer on a new branch, run K6, and go back."""
        with self.new_branch(f"probe-{len(paths)}-{abs(hash(tuple(paths)))}") as base:
            self.commit({p: f"{p}\n" for p in paths}, "feat: change files")
            run = self.k6(base)
        named = self.named(run.stdout)
        self.assertEqual(run.returncode, 1 if named else 0, run.stdout + run.stderr)
        return named


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
        with self.new_branch("tester-commit") as base:
            self.commit({p: "x\n" for p in COVERED_BY_TESTS}, "test: add tests\n\nRole: tester")
            run = self.k6(base)
        self.assertEqual(run.returncode, 0, run.stdout)

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
                old = prefix_only_covers(self.protected(), path)
                self.assertEqual(codes[path], 2 if old else 0)

    def test_hook_gives_the_old_tester_decisions(self) -> None:
        codes = self.hook_codes(NO_GLOB_PROBES, "tester")
        for path in NO_GLOB_PROBES:
            with self.subTest(path=path):
                self.assertEqual(codes[path], 0 if prefix_only_covers(NO_GLOB_TESTS, path) else 2)

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
        self.assertEqual(named, {p for p in files if prefix_only_covers(self.protected(), p)})
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
        with self.new_branch("colocated") as base:
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
        with self.new_branch("colocated-no-role") as base:
            self.commit({"src/widget/widget.test.js": "changed\n"}, "fix: widget test")
            run = self.k6(base)
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertEqual(self.named(run.stdout), {"src/widget/widget.test.js"})

    def test_hook_finds_the_match_module_from_another_working_folder(self) -> None:
        # The harness runs the hook by its full path. The working folder can be any folder.
        (self.root / "src" / "widget").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as outside:
            for cwd in (self.root / "src" / "widget", Path(outside)):
                with self.subTest(cwd=str(cwd)):
                    run = self.run_hook("src/widget/widget.test.js", "implementer", cwd=cwd)
                    self.assertEqual(run.returncode, 2, run.stderr)
                    self.assertIn("src/widget/widget.test.js", run.stderr)
                    run = self.run_hook("src/widget/widget.js", "implementer", cwd=cwd)
                    self.assertEqual(run.returncode, 0, run.stderr)

    def test_the_match_module_is_a_protected_path(self) -> None:
        # A role that changes the module changes the rule of the hook and of K6.
        for role in ("implementer", "tester", "planner", "investigator", "reviewer"):
            with self.subTest(role=role):
                self.assertEqual(self.hook(PATH_MATCH, role), 2)

    def test_k6_names_an_implementer_change_to_the_match_module(self) -> None:
        text = (self.root / PATH_MATCH).read_text(encoding="utf-8")
        with self.new_branch("module-change") as base:
            self.commit({PATH_MATCH: text + "# changed\n"}, "refactor: match module")
            run = self.k6(base)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertEqual(self.named(run.stdout), {PATH_MATCH})


# The names of the match code (D62). Only the rendered module defines them.
MATCH_NAMES = ("covers", "_glob_level", "compile_path", "GLOB_CHARS")


def defined_names(path: Path) -> set[str]:
    """Return each name that a file defines: a function, a class, or an assigned name."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names |= {sub.id for target in targets for sub in ast.walk(target)
                      if isinstance(sub, ast.Name)}
    return names


def path_match_imports(path: Path) -> list[list[str]]:
    """Return the imported names of each `from path_match import ...` in a file."""
    return [[alias.name for alias in node.names]
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.ImportFrom) and node.module == "path_match"]


def match_code_files(root: Path, folders: tuple[str, ...] = (".claude", ".cornerstone")) -> dict:
    """Return, for each match name, the Python files under root/folders that define it.

    A linked worktree under .claude/worktrees/ is a copy of a repo, not a part of this one.
    """
    files = sorted(p for folder in folders for p in (root / folder).rglob("*.py")
                   if not p.relative_to(root).as_posix().startswith(".claude/worktrees/"))
    return {name: sorted(p.relative_to(root).as_posix() for p in files
                         if name in defined_names(p))
            for name in MATCH_NAMES}


def golden_roots() -> list[Path]:
    """Return each golden repo that has a rendered hook."""
    return sorted(hook.parents[2] for hook in GOLDEN.rglob("protect-paths.py")
                  if hook.parent.name == "hooks" and hook.parent.parent.name == ".cornerstone")


class OneMatchModuleTest(RenderedRepo):
    """Criterion 3 and D62: the match code has one copy, the module that the hook and K6 import."""

    TESTS = ["**/*.test.js", "tests/"]

    def assert_no_match_code_and_one_import(self, root: Path) -> None:
        for file in (HOOK, K6):
            with self.subTest(root=str(root), file=file):
                text = (root / file).read_text(encoding="utf-8")
                self.assertFalse(set(MATCH_NAMES) & defined_names(root / file),
                                 sorted(set(MATCH_NAMES) & defined_names(root / file)))
                self.assertNotIn("def covers", text)
                self.assertNotIn("_glob_level", text)
                self.assertNotIn("compile_path", text)
                self.assertEqual(path_match_imports(root / file), [["covers"]])

    def test_rendered_hook_and_k6_define_no_match_code_and_import_covers(self) -> None:
        self.assert_no_match_code_and_one_import(self.root)

    def test_the_hook_and_k6_of_this_repo_define_no_match_code_and_import_covers(self) -> None:
        self.assert_no_match_code_and_one_import(REPO)

    def test_the_match_code_exists_once_in_a_rendered_repo(self) -> None:
        self.assertEqual(match_code_files(self.root),
                         {name: [PATH_MATCH] for name in MATCH_NAMES})

    def test_the_match_code_exists_once_in_this_repo(self) -> None:
        self.assertEqual(match_code_files(REPO), {name: [PATH_MATCH] for name in MATCH_NAMES})

    def test_each_golden_repo_has_the_match_code_once(self) -> None:
        roots = golden_roots()
        self.assertGreaterEqual(len(roots), 11, roots)
        for root in roots:
            with self.subTest(golden=root.relative_to(GOLDEN).as_posix()):
                self.assertEqual(match_code_files(root, (".cornerstone",)),
                                 {name: [PATH_MATCH] for name in MATCH_NAMES})
                self.assertEqual(path_match_imports(root / HOOK), [["covers"]])
                if (root / K6).exists():
                    self.assertEqual(path_match_imports(root / K6), [["covers"]])

    def test_the_rendered_module_is_the_template_that_stone_check_uses(self) -> None:
        # stone check tests each glob with the template, so the module must be the same text.
        template = TEMPLATE.read_bytes()
        self.assertEqual((self.root / PATH_MATCH).read_bytes(), template)
        self.assertEqual((REPO / PATH_MATCH).read_bytes(), template)
        for root in golden_roots():
            with self.subTest(golden=root.relative_to(GOLDEN).as_posix()):
                self.assertEqual((root / PATH_MATCH).read_bytes(), template)

    def test_the_manifest_lists_the_module_as_component_hook_path_match(self) -> None:
        manifest = yaml.safe_load((self.root / ".cornerstone/manifest.yaml")
                                  .read_text(encoding="utf-8"))
        entries = {c["id"]: c for c in manifest["components"]}
        self.assertIn("hook.path-match", entries)
        self.assertEqual(entries["hook.path-match"]["kind"], "hook")
        self.assertEqual(entries["hook.path-match"]["files"], [PATH_MATCH])


# Paths that the hook allows when the module is there: (path, STONE_ROLE, agent_type).
ALLOWED_EDITS = [
    ("src/widget/widget.js", "implementer", None),
    ("src/widget/widget.js", "", "implementer"),
    ("src/widget/widget.test.js", "tester", None),
    ("tests/test_a.py", "", "tester"),
    ("docs/plans/T-1.md", "planner", None),
    ("docs/reports/T-1.md", "investigator", None),
    ("src/a.py", "shaper", None),
]
K6_MODULE_MESSAGE = "K6: .cornerstone/lib/path_match.py is missing or broken. Run stone render."
# A module that does not import: (text, the error of a plain import). Exit code 1 of the hook
# would let the edit through, so each one must give exit code 2.
BROKEN_MODULES = {
    "a syntax error": ("def covers(patterns, path:\n    return False\n", "SyntaxError"),
    "an error on import": ("raise RuntimeError('broken on purpose')\n", "RuntimeError"),
}


class ModuleGuardCase(RenderedRepo):
    """D62: if the match module is missing or broken, the hook blocks each edit, and K6 fails."""

    TESTS = ["**/*.test.js", "tests/"]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        # The control: with the module, the hook allows each of these edits.
        cls.codes_with_module = {edit: cls.run_hook(*edit).returncode for edit in ALLOWED_EDITS}
        cls.module_text = (cls.root / PATH_MATCH).read_text(encoding="utf-8")

    def assert_hook_blocks_each_edit(self) -> None:
        """Each allowed edit, and an edit outside the repo, exits 2 and names the module."""
        self.assertEqual(set(self.codes_with_module.values()), {0}, self.codes_with_module)
        with tempfile.TemporaryDirectory() as outside:
            edits = [*ALLOWED_EDITS, (str(Path(outside) / "a.txt"), "implementer", None)]
            with ThreadPoolExecutor(max_workers=8) as pool:
                runs = list(pool.map(lambda edit: self.run_hook(*edit), edits))
        for (path, role, agent_type), run in zip(edits, runs):
            with self.subTest(path=path, role=role, agent_type=agent_type):
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn(PATH_MATCH, run.stderr)
                self.assertNotIn("Traceback", run.stderr)

    def assert_k6_message(self, base: str, commit: str) -> None:
        with self.subTest(commit=commit):
            run = self.k6(base)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            self.assertIn(K6_MODULE_MESSAGE, run.stdout)
            self.assertNotIn("Traceback", run.stdout + run.stderr)

    def assert_k6_fails_with_its_message(self, branch: str) -> None:
        """K6 exits 1 with its message, with no commit and for a tester commit."""
        with self.new_branch(branch) as base:
            self.assert_k6_message(base, "none")
            self.commit({"tests/test_a.py": "x\n", "src/a.test.js": "x\n"},
                        "test: add tests\n\nRole: tester")
            self.assert_k6_message(base, "a tester commit")
            # The control: the same commits pass K6 when the module is there.
            (self.root / PATH_MATCH).parent.mkdir(parents=True, exist_ok=True)
            (self.root / PATH_MATCH).write_text(self.module_text, encoding="utf-8")
            run = self.k6(base)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


class MissingModuleTest(ModuleGuardCase):
    """D62: if the match module is missing, the hook blocks each edit, and K6 fails."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.git("rm", "-q", PATH_MATCH)
        cls.git("commit", "-qm", "chore: remove the match module\n\nRole: generator")

    def test_the_module_is_missing_and_the_hook_is_there(self) -> None:
        self.assertFalse((self.root / PATH_MATCH).exists())
        self.assertTrue((self.root / HOOK).is_file())
        self.assertTrue((self.root / K6).is_file())

    def test_hook_blocks_each_edit_and_names_the_module(self) -> None:
        self.assert_hook_blocks_each_edit()

    def test_k6_exits_1_and_prints_its_message_with_no_traceback(self) -> None:
        self.assert_k6_fails_with_its_message("tester-commit-no-module")


class BrokenModuleTest(ModuleGuardCase):
    """D62: if the match module does not import, the hook blocks each edit, and K6 fails."""

    def break_module(self, text: str) -> None:
        """Write text to the module, and write the real module back after the test."""
        self.addCleanup((self.root / PATH_MATCH).write_text, self.module_text, encoding="utf-8")
        (self.root / PATH_MATCH).write_text(text, encoding="utf-8")

    def test_each_broken_module_raises_its_error_on_a_plain_import(self) -> None:
        # The control: each case is broken in the way that its name says.
        for case, (text, error) in BROKEN_MODULES.items():
            with self.subTest(case=case):
                self.break_module(text)
                run = subprocess.run([sys.executable, "-B", "-c", "import path_match"],
                                     cwd=(self.root / PATH_MATCH).parent, capture_output=True,
                                     text=True)
                self.assertNotEqual(run.returncode, 0, run.stderr)
                self.assertIn(error, run.stderr)

    def test_hook_blocks_each_edit_and_names_the_module(self) -> None:
        for case, (text, _) in BROKEN_MODULES.items():
            with self.subTest(case=case):
                self.break_module(text)
                self.assert_hook_blocks_each_edit()

    def test_k6_exits_1_and_prints_its_message_with_no_traceback(self) -> None:
        for number, (case, (text, _)) in enumerate(BROKEN_MODULES.items()):
            with self.subTest(case=case):
                self.break_module(text)
                self.assert_k6_fails_with_its_message(f"tester-commit-broken-module-{number}")


class NoBytecodeTest(RenderedRepo):
    """The hook and K6 write no __pycache__ folder in .cornerstone/lib (D62)."""

    TESTS = ["**/*.test.js", "tests/"]

    @staticmethod
    def plain_env(**extra: str) -> dict[str, str]:
        """The environment with no setting that stops or moves the bytecode files."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
        return {**env, **extra}

    def pycache_folders(self, folder: Path) -> list[str]:
        return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("__pycache__"))

    def test_a_plain_import_of_the_module_writes_bytecode_here(self) -> None:
        # The control: this Python writes a __pycache__ folder for a plain import.
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(self.root / PATH_MATCH, tmp)
            subprocess.run([sys.executable, "-c", "import path_match"], cwd=tmp, check=True,
                           env=self.plain_env(), capture_output=True)
            self.assertEqual(self.pycache_folders(Path(tmp)), ["__pycache__"])

    def test_the_hook_and_k6_write_no_pycache_folder(self) -> None:
        # Run them as the harness settings and the CI step do: python3 and the file, no -B.
        event = {"hook_event_name": "PreToolUse", "tool_name": "Write"}
        for path, role in (("src/a.test.js", "implementer"), ("src/a.js", "implementer"),
                           ("tests/test_a.py", "tester")):
            run = subprocess.run(
                [sys.executable, str(self.root / HOOK)], cwd=self.root,
                input=json.dumps({**event, "tool_input": {"file_path": str(self.root / path)}}),
                env=self.plain_env(CLAUDE_PROJECT_DIR=str(self.root), STONE_ROLE=role),
                capture_output=True, text=True)
            self.assertIn(run.returncode, (0, 2), run.stderr)
        with self.new_branch("bytecode") as base:
            self.commit({"src/a.test.js": "x\n"}, "feat: change a test")
            run = subprocess.run([sys.executable, K6, base], cwd=self.root, env=self.plain_env(),
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            self.assertEqual(self.named(run.stdout), {"src/a.test.js"})
            # Before the clean of the branch: an untracked __pycache__ folder must still show.
            self.assertEqual(self.pycache_folders(self.root / ".cornerstone"), [])
            status = self.git("status", "--porcelain", "--untracked-files=all", "--",
                              ".cornerstone")
            self.assertEqual(status, "")


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

    def test_check_and_render_test_each_glob_with_the_match_module_template(self) -> None:
        # D62: stone check uses the template of the module that the hook and K6 import. A copy of
        # the framework gets a template that also rejects a glob with "zzz".
        framework = Path(self.folder.name) / "framework"
        shutil.copytree(FRAMEWORK, framework)
        template = framework / TEMPLATE.relative_to(FRAMEWORK)
        template.write_text(template.read_text(encoding="utf-8") + (
            "\n\n_compile_path = compile_path\n\n\n"
            "def compile_path(pattern: str):\n"
            "    if 'zzz' in pattern:\n"
            "        raise ValueError(f\"'{pattern}' has zzz.\")\n"
            "    return _compile_path(pattern)\n"), encoding="utf-8")
        self.configure(["tests/", "zzz/*.test.js"])
        self.assertEqual(self.glob_findings(), [])  # the real template accepts the glob
        named = [f for f in framework_check.check_config(self.root, framework)
                 if "paths.tests" in f.message]
        self.assertEqual(len(named), 1)
        self.assertIn("zzz", named[0].message)
        self.assertEqual(named[0].severity, "error")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(render.RenderError) as caught:
                render.render(self.root, framework, today=TODAY)
        self.assertIn("paths.tests", str(caught.exception))
        self.assertFalse((self.root / PATH_MATCH).exists())

    def test_a_config_with_no_glob_has_no_glob_finding(self) -> None:
        self.configure(["tests/", "spec/helper.rb"], [".github/workflows/", "ci"])
        self.assertEqual(self.glob_findings(), [])


if __name__ == "__main__":
    unittest.main()
