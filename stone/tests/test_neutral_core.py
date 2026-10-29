"""Tests for P12: the core and the code of stone name no tool (D76)."""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from stone import framework_check, render

REPO = Path(__file__).resolve().parents[2]
FRAMEWORK = REPO / "framework"
CONFIG: dict[str, Any] = {
    "framework_version": "0.8.0",
    "harness": "claude-code",
    "model_profile": "claude-5",
    "profiles": ["single-ticket"],
    "branches": {"integration": "dev", "main": "main"},
    "commands": {"install": "pip install .", "test_unit": "python -m unittest",
                 "all_checks": "make check"},
    "paths": {"tests": ["tests/"], "checks": [".github/workflows/", ".cornerstone/checks/"],
              "plans": "docs/plans/"},
    "owners": {"default": "octocat"},
}


class NeutralDocTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.framework = Path(self.folder.name) / "framework"
        (self.framework / "adapters").mkdir(parents=True)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_core_doc_names_spec_tool(self) -> None:
        for name in ["Spec Kit", "BMAD", "SpecKit", "Agentic Code"]:
            with self.subTest(name=name):
                (self.framework / "core.md").write_text(f"We use {name} here.\n", encoding="utf-8")
                findings = framework_check.check_neutral(self.framework)
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0].check, framework_check.CHECK)
                self.assertIn("names", findings[0].message)

    def test_adapter_doc_may_name_spec_tool(self) -> None:
        (self.framework / "core.md").write_text("No tool here.\n", encoding="utf-8")
        (self.framework / "adapters" / "spec-tools.md").write_text("Spec Kit and BMAD.\n",
                                                                  encoding="utf-8")
        self.assertEqual(framework_check.check_neutral(self.framework), [])


class NeutralCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.code = self.root / "stone" / "src" / "stone"
        self.code.mkdir(parents=True)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_finds_harness_folder(self) -> None:
        (self.code / "x.py").write_text('A = 1\nPATH = ".claude/settings.json"\n', encoding="utf-8")
        findings = framework_check.check_neutral_code(self.code)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line, 2)
        self.assertIn(".claude/", findings[0].message)

    def test_ignores_allowed_files(self) -> None:
        for name in ["framework_check.py", "writing_check.py"]:
            (self.code / name).write_text('X = ".claude/"\n', encoding="utf-8")
        self.assertEqual(framework_check.check_neutral_code(self.code), [])

    def test_clean_code_and_missing_folder(self) -> None:
        (self.code / "x.py").write_text("A = 1\n", encoding="utf-8")
        self.assertEqual(framework_check.check_neutral_code(self.code), [])
        self.assertEqual(framework_check.check_neutral_code(self.root / "nowhere"), [])

    def test_run_reports_it(self) -> None:
        (self.code / "x.py").write_text('P = ".claude/"\n', encoding="utf-8")
        shutil.copytree(FRAMEWORK, self.root / "framework")
        messages = [f.message for f in framework_check.run(self.root)]
        self.assertTrue(any("harness folder" in m for m in messages), messages)


class RenderHarnessDirsTest(unittest.TestCase):
    def hook_list(self, framework: Path, var: str) -> list[str]:
        components = render.build_components(framework, CONFIG)
        text = next(content for c in components for target, content in c.files.items()
                    if target.endswith("protect-paths.py"))
        match = re.search(rf"^{var} = (\[.*\])$", text, re.M)
        assert match, text
        return yaml.safe_load(match.group(1))

    def test_template_values_use_given_dirs(self) -> None:
        values = render.template_values(CONFIG, "", [".demo/"])
        self.assertEqual(yaml.safe_load(values["harness_json"]), [".demo/", ".cornerstone/"])
        self.assertIn(".demo/", yaml.safe_load(values["protected_json"]))
        self.assertNotIn(".claude/", values["protected_json"])

    def test_template_values_default_has_only_core(self) -> None:
        values = render.template_values(CONFIG, "")
        self.assertEqual(yaml.safe_load(values["harness_json"]), [".cornerstone/"])

    def test_adapter_protected_dirs_reach_the_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            framework = Path(tmp) / "framework"
            shutil.copytree(FRAMEWORK, framework)
            path = framework / "adapters" / "claude-code" / "components.yaml"
            text = path.read_text(encoding="utf-8")
            self.assertIn("protected_dirs:\n  - .claude/\n", text)
            path.write_text(text.replace("protected_dirs:\n  - .claude/\n",
                                         "protected_dirs:\n  - .demo/\n"), encoding="utf-8")
            self.assertEqual(self.hook_list(framework, "HARNESS"), [".demo/", ".cornerstone/"])
            self.assertIn(".demo/", self.hook_list(framework, "PROTECTED"))

    def test_real_adapter_gives_claude_folder(self) -> None:
        self.assertEqual(self.hook_list(FRAMEWORK, "HARNESS"), [".claude/", ".cornerstone/"])
        self.assertIn(".claude/", self.hook_list(FRAMEWORK, "PROTECTED"))


class RealRepoTest(unittest.TestCase):
    def test_core_is_neutral(self) -> None:
        self.assertEqual(framework_check.check_neutral(FRAMEWORK), [])

    def test_code_is_neutral(self) -> None:
        self.assertEqual(framework_check.check_neutral_code(REPO / "stone" / "src" / "stone"), [])


if __name__ == "__main__":
    unittest.main()
