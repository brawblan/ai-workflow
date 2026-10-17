"""Tests for `stone check`."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stone import framework_check

WORKFLOW_MODEL = """# Workflow model

## Stages

| Stage | Goal |
| --- | --- |
| Build | Change the code. |
| Verify | Run the checks. |

### Loop limits

## Roles

| Role | Job |
| --- | --- |
| implementer | Change the code. |

### Session rules
"""
CHECKS = "| ID | Check |\n| --- | --- |\n| K1 | Lint |\n| K17 | Writing |\n"
GATES = """| Profile | G1 | G2 | G3 | G4 | G5 |
| --- | --- | --- | --- | --- | --- |
| [demo](profiles/demo.md) | check | — | yes | human | if needed |
"""
PROFILE = """---
id: demo
name: Demo
version: 0.1.0
purpose: Test.
triggers: [command]
stages: [build, verify]
roles: [implementer]
plan_form: decision-log
mode: agent-centric
gates:
  G1: check
  G2: skip
  G3: required
  G4: human
  G5: if-needed
checks: [K1, K17]
limits: {}
outputs: [pr]
---

# Demo
"""


class FrameworkCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        framework = self.root / "framework"
        (framework / "profiles").mkdir(parents=True)
        (framework / "adapters").mkdir()
        (framework / "workflow-model.md").write_text(WORKFLOW_MODEL, encoding="utf-8")
        (framework / "checks.md").write_text(CHECKS, encoding="utf-8")
        (framework / "gates.md").write_text(GATES, encoding="utf-8")
        self.profile = framework / "profiles" / "demo.md"
        self.profile.write_text(PROFILE, encoding="utf-8")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def messages(self) -> list[str]:
        return [f.message for f in framework_check.run(self.root)]

    def test_valid_framework_has_no_findings(self) -> None:
        self.assertEqual(self.messages(), [])

    def test_g3_must_be_required_for_a_pr(self) -> None:
        self.profile.write_text(PROFILE.replace("G3: required", "G3: skip"), encoding="utf-8")
        self.assertTrue(any("G3 is not 'required'" in m for m in self.messages()))

    def test_gate_matrix_must_agree(self) -> None:
        self.profile.write_text(PROFILE.replace("G4: human", "G4: skip"), encoding="utf-8")
        self.assertTrue(any("do not agree with gates.md" in m for m in self.messages()))

    def test_unknown_check_and_missing_k17(self) -> None:
        self.profile.write_text(PROFILE.replace("[K1, K17]", "[K99]"), encoding="utf-8")
        messages = self.messages()
        self.assertTrue(any("'K99' is not in checks.md" in m for m in messages))
        self.assertTrue(any("does not run K17" in m for m in messages))

    def test_core_must_not_name_a_vendor(self) -> None:
        (self.root / "framework" / "notes.md").write_text("Use Codex here.\n", encoding="utf-8")
        self.assertTrue(any("names 'Codex'" in m for m in self.messages()))

    def test_broken_link(self) -> None:
        (self.root / "README.md").write_text("See [x](missing.md).\n", encoding="utf-8")
        self.assertTrue(any("'missing.md' points to no file" in m for m in self.messages()))

    def test_config_waiver_cannot_remove_g3(self) -> None:
        config = self.root / ".cornerstone"
        config.mkdir()
        (self.root / "framework" / "adapters" / "demo-harness.md").write_text("x", encoding="utf-8")
        (config / "config.yaml").write_text(
            "harness: demo-harness\nprofiles: [demo]\nwaivers:\n  - gate: G3\n",
            encoding="utf-8")
        self.assertTrue(any("No waiver can remove G3" in m for m in self.messages()))


if __name__ == "__main__":
    unittest.main()
