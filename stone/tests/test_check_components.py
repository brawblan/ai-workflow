"""Tests for the P5 component rule of `stone check` (D43): each component has an eval plan and a
review date (issue #65)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stone import framework_check

LIST_OK = """components:
  - id: role.tester
    kind: role
    eval: evals/role-tester/
  - id: check.k6
    kind: check
    eval: ""
"""
MANIFEST_OK = """framework_version: 0.5.0
components:
- id: role.tester
  kind: role
  eval: evals/role-tester/
  added: '2026-10-17'
  review_by: '2027-04-17'
- id: check.k6
  kind: check
  eval: ''
  added: '2026-10-17'
  review_by: 2027-04-17
"""


class CheckComponentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.framework = self.root / "framework"
        (self.framework / "adapters" / "h").mkdir(parents=True)
        self.write_list(LIST_OK)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_list(self, text: str) -> None:
        (self.framework / "adapters" / "h" / "components.yaml").write_text(text, encoding="utf-8")

    def write_manifest(self, text: str) -> None:
        (self.root / ".cornerstone").mkdir(exist_ok=True)
        (self.root / ".cornerstone" / "manifest.yaml").write_text(text, encoding="utf-8")

    def messages(self) -> list[str]:
        return [finding.message for finding in
                framework_check.check_components(self.root, self.framework)]

    def test_valid_list_and_no_manifest_pass(self) -> None:
        self.assertEqual(self.messages(), [])

    def test_valid_manifest_passes(self) -> None:
        self.write_manifest(MANIFEST_OK)
        self.assertEqual(self.messages(), [])

    def test_check_with_empty_eval_passes(self) -> None:
        # lifecycle.md: a check is its own test, so its eval can be empty.
        self.write_list('components:\n  - id: check.k6\n    kind: check\n    eval: ""\n')
        self.assertEqual(self.messages(), [])

    def test_role_with_empty_eval_fails(self) -> None:
        self.write_list('components:\n  - id: role.tester\n    kind: role\n    eval: ""\n')
        messages = self.messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("'role.tester' has no eval plan (P5)", messages[0])
        self.assertIn("evals/role-tester/", messages[0])

    def test_ci_job_with_no_eval_value_fails(self) -> None:
        self.write_list("components:\n  - id: trigger.label\n    kind: ci-job\n    eval:\n")
        self.assertIn("'trigger.label' has no eval plan", self.messages()[0])

    def test_missing_eval_key_fails_even_for_a_check(self) -> None:
        # render reads entry["eval"], so a missing key stops the render.
        self.write_list("components:\n  - id: check.k7\n    kind: check\n")
        self.assertIn("'check.k7' has no 'eval' key", self.messages()[0])

    def test_manifest_entry_without_review_by_fails(self) -> None:
        self.write_manifest("components:\n- id: hook.x\n  kind: hook\n  eval: evals/hook-x/\n")
        self.assertIn("'hook.x' has no valid 'review_by' date", self.messages()[0])

    def test_manifest_entry_with_bad_review_by_fails(self) -> None:
        self.write_manifest("components:\n- id: hook.x\n  kind: hook\n  eval: evals/hook-x/\n"
                            "  review_by: soon\n")
        self.assertIn("'hook.x' has no valid 'review_by' date", self.messages()[0])

    def test_repo_component_in_manifest_is_tested(self) -> None:
        self.write_manifest("components:\n- id: skill.mine\n  kind: skill\n  source: repo\n"
                            "  eval: ''\n  review_by: '2027-01-01'\n")
        self.assertIn("'skill.mine' has no eval plan", self.messages()[0])

    def test_finding_names_the_file_and_the_line(self) -> None:
        self.write_list('components:\n  - id: role.a\n    kind: role\n    eval: evals/a/\n'
                        '  - id: role.b\n    kind: role\n    eval: ""\n')
        findings = framework_check.check_components(self.root, self.framework)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].path, "framework/adapters/h/components.yaml")
        self.assertEqual(findings[0].line, 5)


class RepoDataTest(unittest.TestCase):
    """The adapter lists and the manifest of this repo pass the rule (issue #65)."""

    def test_this_repo_passes(self) -> None:
        root = Path(__file__).resolve().parents[2]  # stone/tests/<this file> -> repo root
        self.assertEqual(framework_check.check_components(root, root / "framework"), [])


if __name__ == "__main__":
    unittest.main()
