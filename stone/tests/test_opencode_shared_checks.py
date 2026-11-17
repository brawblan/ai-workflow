"""Tests for the shared checks of the OpenCode adapter (issue #332).

The neutral templates are in `adapters/shared/templates/`. The OpenCode adapter renders K6, K7,
K15, K16, K22, and the G3 workflow from them. The tests cover the template lookup, the render, the
K6 script on a real git repo, and the match with the Claude Code render.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import framework_check, render
from stone.template_path import template_file

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
OPENCODE = FRAMEWORK / "adapters" / "opencode"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
K6 = ".cornerstone/checks/protected_paths.py"
CHANGE_SIZE = ".cornerstone/checks/change_size.py"
PATH_MATCH = ".cornerstone/lib/path_match.py"
INSTRUCTION_SIZE = ".cornerstone/checks/instruction_size.py"
INSTRUCTION_TEXT = ".cornerstone/checks/instruction_text.py"
G3 = ".github/workflows/cornerstone-checks.yml"
K16 = ".github/workflows/cornerstone-k16.yml"
PROTECTED_LINE = re.compile(r"^PROTECTED = .*$", re.MULTILINE)


def config(harness: str, model: str, profile: str = "single-ticket", extra: str = "",
           version: str = "0.8.0") -> str:
    """Return the text of a repo config."""
    return f"""framework_version: {version}
harness: {harness}
model_profile: {model}
profiles: [{profile}]
branches: {{integration: dev, main: main}}
commands: {{install: pip install ., test_unit: python -m unittest, all_checks: make check}}
paths: {{tests: [tests/], checks: [.github/workflows/, .cornerstone/checks/], plans: docs/plans/}}
owners: {{default: octocat}}
{extra}"""


def render_repo(root: Path, text: str) -> tuple[render.Result, str]:
    """Render a config into root. Return the result and the text on stderr."""
    (root / ".cornerstone").mkdir(parents=True, exist_ok=True)
    (root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")
    log = io.StringIO()
    with contextlib.redirect_stderr(log):
        result = render.render(root, FRAMEWORK)
    return result, log.getvalue()


class TemplateFileTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.adapters = Path(folder.name)
        self.harness = self.adapters / "own"
        self.shared = self.adapters / "shared" / "templates"
        self.own = self.harness / "templates"

    def put(self, folder: Path, name: str = "checks/a.py") -> Path:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
        return path

    def test_template_file_own_file_wins_over_a_shared_file(self) -> None:
        own = self.put(self.own)
        self.put(self.shared)
        self.assertEqual(template_file(self.harness, "checks/a.py"), own)

    def test_template_file_falls_back_to_the_shared_file(self) -> None:
        shared = self.put(self.shared)
        self.assertEqual(template_file(self.harness, "checks/a.py"), shared)

    def test_template_file_returns_the_own_path_if_no_file_exists(self) -> None:
        path = template_file(self.harness, "checks/a.py")
        self.assertEqual(path, self.own / "checks" / "a.py")
        self.assertFalse(path.exists())

    def test_template_file_uses_the_own_file_if_only_the_adapter_has_it(self) -> None:
        own = self.put(self.own)
        self.assertEqual(template_file(self.harness, "checks/a.py"), own)


class OpenCodeRenderTest(unittest.TestCase):
    def render(self, profile: str = "single-ticket", extra: str = "",
               harness: str = "opencode") -> tuple[Path, render.Result, str]:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name) / "repo"
        model = "opencode-default" if harness == "opencode" else "claude-5"
        result, log = render_repo(root, config(harness, model, profile, extra))
        return root, result, log

    def test_single_ticket_writes_the_shared_checks_and_g3(self) -> None:
        root, result, _ = self.render()
        self.assertEqual(result.exit_code, 0)
        for path in (K6, CHANGE_SIZE, PATH_MATCH, G3):
            self.assertTrue((root / path).is_file(), path)

    def test_single_ticket_writes_no_k16_k15_or_k22_file(self) -> None:
        root, _, _ = self.render()
        for path in (K16, INSTRUCTION_SIZE, INSTRUCTION_TEXT):
            self.assertFalse((root / path).exists(), path)

    def test_k16_is_written_only_for_a_profile_with_k16(self) -> None:
        for profile in ("spike", "single-ticket"):
            checks = (FRAMEWORK / "profiles" / f"{profile}.md").read_text(
                encoding="utf-8").split("---")[1]
            wanted = "K16" in yaml.safe_load(checks)["checks"]
            root, _, _ = self.render(profile)
            self.assertEqual((root / K16).exists(), wanted, profile)

    def test_k15_is_written_only_for_a_profile_with_k15(self) -> None:
        for profile in ("full-project", "single-ticket"):
            checks = (FRAMEWORK / "profiles" / f"{profile}.md").read_text(
                encoding="utf-8").split("---")[1]
            wanted = "K15" in yaml.safe_load(checks)["checks"]
            root, _, _ = self.render(profile)
            self.assertEqual((root / INSTRUCTION_SIZE).exists(), wanted, profile)

    def test_k22_text_check_needs_protect_instruction_files(self) -> None:
        on, _, _ = self.render(extra="protect_instruction_files: true\n")
        off, _, _ = self.render()
        self.assertTrue((on / INSTRUCTION_TEXT).is_file())
        self.assertFalse((off / INSTRUCTION_TEXT).exists())

    def test_trailers_none_writes_no_k6_but_still_writes_the_match_module(self) -> None:
        root, result, log = self.render(extra="commits: {trailers: none}\n")
        self.assertEqual(result.exit_code, 0)
        self.assertFalse((root / K6).exists())
        self.assertTrue((root / PATH_MATCH).is_file())
        self.assertIn("warning", log)
        self.assertIn("K6", log)
        self.assertTrue((root / CHANGE_SIZE).is_file())

    def test_k22_runs_with_trailers_none_and_finds_the_match_module(self) -> None:
        root, _, _ = self.render(
            extra="protect_instruction_files: true\ncommits: {trailers: none}\n")
        (root / "AGENTS.md").write_text("# Guide\n\nRun the tests.\n", encoding="utf-8")
        env = {**os.environ, **GIT_ENV}
        for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "base"]):
            subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=env)
        run = subprocess.run([sys.executable, "-B", INSTRUCTION_TEXT], cwd=root,
                             capture_output=True, text=True, env=env)
        self.assertNotIn("missing or broken", run.stdout + run.stderr)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_local_delivery_writes_no_workflow(self) -> None:
        root, _, _ = self.render(extra="delivery: local\n")
        self.assertFalse((root / G3).exists())
        self.assertFalse((root / K16).exists())

    def test_ac3_k6_protected_list_has_the_opencode_paths(self) -> None:
        root, _, _ = self.render()
        line = PROTECTED_LINE.search((root / K6).read_text(encoding="utf-8"))
        assert line is not None
        protected = json.loads(line.group(0).split("=", 1)[1])
        for path in (".opencode/", "opencode.json", ".cornerstone/"):
            self.assertIn(path, protected)

    def test_k6_of_opencode_does_not_list_claude_paths(self) -> None:
        root, _, _ = self.render()
        text = (root / K6).read_text(encoding="utf-8")
        self.assertNotIn(".claude/", PROTECTED_LINE.search(text).group(0))  # type: ignore[union-attr]


class SameNeutralFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.roots: dict[str, Path] = {}
        for harness, model in (("claude-code", "claude-5"), ("opencode", "opencode-default")):
            folder = tempfile.TemporaryDirectory()
            self.addCleanup(folder.cleanup)
            root = Path(folder.name) / "repo"
            render_repo(root, config(harness, model, "single-ticket, spike"))
            self.roots[harness] = root

    def read(self, harness: str, path: str) -> str:
        return (self.roots[harness] / path).read_text(encoding="utf-8")

    def test_change_size_is_the_same_on_both_adapters(self) -> None:
        self.assertEqual(self.read("claude-code", CHANGE_SIZE), self.read("opencode", CHANGE_SIZE))

    def test_path_match_is_the_same_on_both_adapters(self) -> None:
        self.assertEqual(self.read("claude-code", PATH_MATCH), self.read("opencode", PATH_MATCH))

    def test_k16_workflow_is_the_same_on_both_adapters(self) -> None:
        self.assertEqual(self.read("claude-code", K16), self.read("opencode", K16))

    def test_protected_paths_differs_only_in_the_protected_line(self) -> None:
        a, b = self.read("claude-code", K6), self.read("opencode", K6)
        self.assertNotEqual(PROTECTED_LINE.search(a).group(0),  # type: ignore[union-attr]
                            PROTECTED_LINE.search(b).group(0))  # type: ignore[union-attr]
        self.assertEqual(PROTECTED_LINE.sub("", a), PROTECTED_LINE.sub("", b))


class K25SameWorkflowTest(unittest.TestCase):
    def test_g3_workflow_with_k25_is_the_same_on_both_adapters(self) -> None:
        front = (FRAMEWORK / "profiles" / "single-ticket.md").read_text(
            encoding="utf-8").split("---")[1]
        self.assertIn("K25", yaml.safe_load(front)["checks"])
        texts = {}
        for harness, model in (("claude-code", "claude-5"), ("opencode", "opencode-default")):
            folder = tempfile.TemporaryDirectory()
            self.addCleanup(folder.cleanup)
            root = Path(folder.name) / "repo"
            render_repo(root, config(harness, model, "single-ticket, full-project",
                                     version="1.8.0"))
            texts[harness] = (root / G3).read_text(encoding="utf-8")
        self.assertIn("K25", texts["opencode"])
        self.assertEqual(texts["claude-code"], texts["opencode"])


class K6EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name).resolve() / "repo"
        render_repo(cls.root, config("opencode", "opencode-default"))
        cls.git("init", "-q", "-b", "main")
        cls.write({"README.md": "base\n", ".opencode/agents/implementer.md": "a\n"})
        cls.git("add", "-A")
        cls.git("commit", "-qm", "chore: base\n\nRole: generator\nActor: agent")
        cls.base = cls.git("rev-parse", "HEAD").strip()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.folder.cleanup()

    @classmethod
    def git(cls, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cls.root, check=True, capture_output=True,
                              text=True, env={**os.environ, **GIT_ENV}).stdout

    @classmethod
    def write(cls, files: dict[str, str]) -> None:
        for path, text in files.items():
            (cls.root / path).parent.mkdir(parents=True, exist_ok=True)
            (cls.root / path).write_text(text, encoding="utf-8")

    def run_k6(self, files: dict[str, str], message: str) -> subprocess.CompletedProcess:
        """Commit files on a branch from the base, run K6, and go back to main."""
        self.git("checkout", "-q", "-b", f"t{abs(hash((message, tuple(files))))}", self.base)
        self.addCleanup(self.git, "checkout", "-q", "-f", "main")
        self.write(files)
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return subprocess.run([sys.executable, "-B", K6, self.base], cwd=self.root,
                              capture_output=True, text=True, env={**os.environ, **GIT_ENV})

    def test_k6_fails_an_implementer_commit_that_changes_an_opencode_agent(self) -> None:
        path = ".opencode/agents/implementer.md"
        run = self.run_k6({path: "b\n"}, "feat: x\n\nRole: implementer\nActor: agent")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(path, run.stdout)

    def test_k6_fails_a_commit_with_no_role_trailer_that_changes_an_opencode_agent(self) -> None:
        path = ".opencode/agents/implementer.md"
        run = self.run_k6({path: "c\n"}, "feat: no trailer")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn(path, run.stdout)

    def test_k6_fails_an_implementer_commit_that_changes_opencode_json(self) -> None:
        run = self.run_k6({"opencode.json": "{}\n"}, "feat: x\n\nRole: implementer\nActor: agent")
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("opencode.json", run.stdout)

    def test_k6_passes_a_human_commit_that_changes_opencode_files(self) -> None:
        run = self.run_k6({".opencode/agents/implementer.md": "d\n"},
                          "chore: agent\n\nRole: human\nActor: human")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_k6_passes_an_implementer_commit_that_changes_only_source(self) -> None:
        run = self.run_k6({"src/x.py": "x = 1\n"}, "feat: x\n\nRole: implementer\nActor: agent")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


class StoneCheckTest(unittest.TestCase):
    def test_path_compiler_finds_the_match_module_of_the_opencode_adapter(self) -> None:
        compile_path = framework_check.path_compiler(OPENCODE)
        self.assertTrue(callable(compile_path))

    def test_opencode_components_list_provides_path_match(self) -> None:
        entries = yaml.safe_load((OPENCODE / "components.yaml").read_text(encoding="utf-8"))
        self.assertIn("path_match", [e.get("provides") for e in entries["components"]])


if __name__ == "__main__":
    unittest.main()
