"""Tests for D87 and issue #218, part 2: the `protect_instruction_files` key.

With the key true, the rendered hook and K6 protect `**/AGENTS.md`, `**/CLAUDE.md`, and
`**/CLAUDE.local.md`. With the key false or absent, they do not (the 1.x default).
"""

from __future__ import annotations

import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from path_match_helpers import FRAMEWORK, HOOK, K6, PATH_MATCH
from stone import framework_check, render
from test_path_globs import TODAY, RenderedRepo, config

ADAPTER = FRAMEWORK / "adapters" / "claude-code" / "components.yaml"
# D88: the adapter lists each letter as a class of both cases. Render must copy this list.
PATTERNS = yaml.safe_load(ADAPTER.read_text(encoding="utf-8"))["instruction_files"]
COVERED = ["AGENTS.md", "docs/AGENTS.md", "a/b/CLAUDE.local.md", "CLAUDE.md",
           "a/b/c/CLAUDE.md", "CLAUDE.local.md", "agents.md", "docs/Agents.MD",
           "sub/claude.md", "x/claude.LOCAL.md"]
NOT_COVERED = ["AGENTS.md.bak", "docs/MY_AGENTS.md", "docs/AGENTS.md.bak", "CLAUDE.md.old",
               "NOTCLAUDE.md", "docs/readme.md", "agentsXmd", "docs/agents.md.bak"]


def assigned(text: str, name: str) -> list[str]:
    """The list that the rendered file assigns to the constant `name`."""
    import json
    match = re.search(rf"^{name} = (\[.*\])$", text, re.MULTILINE)
    assert match, f"{name} not found"
    return json.loads(match.group(1))


class RenderedInstructionRepo(RenderedRepo):
    """A RenderedRepo whose config has the key set by EXTRA."""

    EXTRA = ""

    @classmethod
    def setUpClass(cls) -> None:
        original = config

        def with_key(tests: list[str], checks: list[str]) -> str:
            return original(tests, checks) + cls.EXTRA

        import test_path_globs
        test_path_globs.config = with_key
        try:
            super().setUpClass()
        finally:
            test_path_globs.config = original

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")


class KeyOnTest(RenderedInstructionRepo):
    TESTS = ["tests/"]
    EXTRA = "protect_instruction_files: true\n"

    def test_hook_protected_has_the_patterns(self) -> None:
        protected = assigned(self.read(HOOK), "PROTECTED")
        for pattern in PATTERNS:
            self.assertIn(pattern, protected)

    def test_hook_harness_has_the_patterns(self) -> None:
        harness = assigned(self.read(HOOK), "HARNESS")
        for pattern in PATTERNS:
            self.assertIn(pattern, harness)

    def test_k6_protected_has_the_patterns(self) -> None:
        protected = assigned(self.read(K6), "PROTECTED")
        for pattern in PATTERNS:
            self.assertIn(pattern, protected)

    def test_path_match_covers_the_patterns(self) -> None:
        namespace: dict = {}
        exec(self.read(PATH_MATCH), namespace)
        covers = namespace["covers"]
        for path in COVERED:
            with self.subTest(path=path):
                self.assertTrue(covers(PATTERNS, path))
        for path in NOT_COVERED:
            with self.subTest(path=path):
                self.assertFalse(covers(PATTERNS, path))

    def test_hook_blocks_the_implementer_on_instruction_files_only(self) -> None:
        codes = self.hook_codes(COVERED + NOT_COVERED, "implementer")
        for path in COVERED:
            with self.subTest(path=path):
                self.assertEqual(codes[path], 2)
        for path in NOT_COVERED:
            with self.subTest(path=path):
                self.assertEqual(codes[path], 0)

    def test_hook_blocks_the_investigator_on_instruction_files(self) -> None:
        self.assertEqual(self.hook("docs/AGENTS.md", "investigator"), 2)

    def test_k6_fails_an_implementer_commit_on_docs_agents_md(self) -> None:
        named = self.k6_named_for_an_implementer_commit(["docs/AGENTS.md"])
        self.assertEqual(named, {"docs/AGENTS.md"})

    def test_the_adapter_list_has_the_three_files(self) -> None:
        self.assertEqual(len(PATTERNS), 3)

    def test_hook_blocks_the_planner_on_docs_agents_md(self) -> None:
        self.assertEqual(self.hook("docs/AGENTS.md", "planner"), 2)

    def test_k6_names_each_instruction_file_only(self) -> None:
        # A file system that ignores case folds two paths that differ only in case.
        seen: set[str] = set()
        paths = [p for p in COVERED if not (p.lower() in seen or seen.add(p.lower()))]
        named = self.k6_named_for_an_implementer_commit(paths + NOT_COVERED)
        self.assertEqual(named, set(paths))

    def test_k6_fails_an_implementer_commit_on_sub_claude_md(self) -> None:
        with self.new_branch("impl-lower-claude") as base:
            self.commit({"sub/claude.md": "rules\n"}, "feat: x\n\nRole: implementer")
            run = self.k6(base)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertEqual(self.named(run.stdout), {"sub/claude.md"})

    def test_k6_passes_a_human_commit_on_docs_agents_md(self) -> None:
        with self.new_branch("human-instr") as base:
            self.commit({"docs/AGENTS.md": "rules\n"}, "docs: rules\n\nRole: human")
            run = self.k6(base)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


class KeyOffHookTest(RenderedInstructionRepo):
    """The key absent, in a rendered repo: the hook allows an instruction file edit."""

    TESTS = ["tests/"]

    def test_hook_allows_the_implementer_on_docs_agents_md(self) -> None:
        self.assertEqual(self.hook("docs/AGENTS.md", "implementer"), 0)


class KeyOffTest(unittest.TestCase):
    """The key false, and the key absent: the old behavior."""

    def render_with(self, extra: str) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".cornerstone").mkdir()
            (root / ".cornerstone" / "config.yaml").write_text(
                config(["tests/"], [".github/workflows/"]) + extra, encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                result = render.render(root, FRAMEWORK, today=TODAY)
            self.assertEqual(result.exit_code, 0)
            return ((root / HOOK).read_text(encoding="utf-8"),
                    (root / K6).read_text(encoding="utf-8"))

    def test_absent_and_false_do_not_add_the_patterns(self) -> None:
        for label, extra in {"absent": "", "false": "protect_instruction_files: false\n"}.items():
            with self.subTest(key=label):
                hook, k6 = self.render_with(extra)
                for pattern in PATTERNS:
                    self.assertNotIn(pattern, assigned(hook, "PROTECTED"))
                    self.assertNotIn(pattern, assigned(hook, "HARNESS"))
                    self.assertNotIn(pattern, assigned(k6, "PROTECTED"))


class KeyCheckTest(unittest.TestCase):
    """`stone check` (framework_check.check_config) on the key."""

    def messages(self, extra: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".cornerstone").mkdir()
            (root / ".cornerstone" / "config.yaml").write_text(
                config(["tests/"], [".github/workflows/"]) + extra, encoding="utf-8")
            return [f.message for f in framework_check.check_config(root, FRAMEWORK)]

    def test_a_string_value_is_a_problem(self) -> None:
        for value in ['"yes"', "yes_please", "1", "[true]"]:
            with self.subTest(value=value):
                found = self.messages(f"protect_instruction_files: {value}\n")
                self.assertTrue(any("protect_instruction_files" in m for m in found), found)

    def test_true_false_and_absent_are_no_problem(self) -> None:
        for extra in ["", "protect_instruction_files: true\n", "protect_instruction_files: false\n"]:
            with self.subTest(extra=extra):
                found = self.messages(extra)
                self.assertFalse(any("protect_instruction_files" in m for m in found), found)


if __name__ == "__main__":
    unittest.main()
