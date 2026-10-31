"""Tests for the P5 component rule of `stone check` (D43): each component has an eval plan and a
review date (issue #65)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from stone import framework_check, results

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
  owner: brawblan
  eval: evals/role-tester/
  added: '2026-10-17'
  review_by: '2027-04-17'
- id: check.k6
  kind: check
  owner: brawblan
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

    def test_ci_job_with_a_check_id_and_empty_eval_passes(self) -> None:
        # D99: K16 renders a workflow, so its kind is ci-job. It is still a check.
        self.write_list('components:\n  - id: check.k16\n    kind: ci-job\n    eval: ""\n')
        self.assertEqual(self.messages(), [])

    def test_ci_job_with_another_id_and_empty_eval_fails(self) -> None:
        self.write_list('components:\n  - id: trigger.label\n    kind: ci-job\n    eval: ""\n')
        self.assertIn("'trigger.label' has no eval plan", self.messages()[0])

    def test_ci_job_checks_with_empty_eval_passes_in_the_list(self) -> None:
        # D102: the job of the checks has no model in it, so its eval can be empty.
        self.write_list('components:\n  - id: ci-job.checks\n    kind: ci-job\n    eval: ""\n')
        self.assertEqual(self.messages(), [])

    def test_ci_job_checks_with_empty_eval_passes_in_the_manifest(self) -> None:
        self.write_manifest("components:\n- id: ci-job.checks\n  kind: ci-job\n"
                            "  owner: brawblan\n  eval: ''\n  review_by: '2027-01-01'\n")
        self.assertEqual(self.messages(), [])

    def test_other_ci_job_id_with_empty_eval_still_fails_d102(self) -> None:
        self.write_list("components:\n  - id: trigger.label.single-ticket\n"
                        '    kind: ci-job\n    eval: ""\n')
        self.assertIn("'trigger.label.single-ticket' has no eval plan", self.messages()[0])

    def test_real_adapter_list_has_an_empty_eval_for_ci_job_checks(self) -> None:
        path = (Path(__file__).resolve().parents[2] / "framework" / "adapters" / "claude-code"
                / "components.yaml")
        entries = yaml.safe_load(path.read_text(encoding="utf-8"))["components"]
        entry = next(item for item in entries if item["id"] == "ci-job.checks")
        self.assertEqual(entry["eval"], "")

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
        self.write_manifest("components:\n- id: hook.x\n  kind: hook\n  owner: brawblan\n"
                            "  eval: evals/hook-x/\n")
        self.assertIn("'hook.x' has no valid 'review_by' date", self.messages()[0])

    def test_manifest_entry_with_bad_review_by_fails(self) -> None:
        self.write_manifest("components:\n- id: hook.x\n  kind: hook\n  owner: brawblan\n"
                            "  eval: evals/hook-x/\n  review_by: soon\n")
        self.assertIn("'hook.x' has no valid 'review_by' date", self.messages()[0])

    def test_repo_component_in_manifest_is_tested(self) -> None:
        self.write_manifest("components:\n- id: skill.mine\n  kind: skill\n  source: repo\n"
                            "  owner: brawblan\n  eval: ''\n  review_by: '2027-01-01'\n")
        self.assertIn("'skill.mine' has no eval plan", self.messages()[0])

    def test_finding_names_the_file_and_the_line(self) -> None:
        self.write_list('components:\n  - id: role.a\n    kind: role\n    eval: evals/a/\n'
                        '  - id: role.b\n    kind: role\n    eval: ""\n')
        findings = framework_check.check_components(self.root, self.framework)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].path, "framework/adapters/h/components.yaml")
        self.assertEqual(findings[0].line, 5)


def manifest_text(owner: str | None = "brawblan", models: str | None = "[]",
                  component: str = "role.tester") -> str:
    """One manifest entry. A None owner or models drops the key."""
    lines = [f"- id: {component}", "  kind: role", "  eval: evals/role-tester/",
             "  review_by: '2027-04-17'"]
    if owner is not None:
        lines.append(f"  owner: {owner}")
    if models is not None:
        lines.append(f"  models_tested: {models}")
    return "components:\n" + "\n".join(lines) + "\n"


class OwnerAndModelsTest(unittest.TestCase):
    """P5 (D50): each manifest entry has an owner and lists the models of its result files."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.framework = self.root / "framework"
        (self.framework / "adapters" / "h").mkdir(parents=True)
        (self.framework / "adapters" / "h" / "components.yaml").write_text(LIST_OK, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_manifest(self, text: str) -> None:
        (self.root / ".cornerstone").mkdir(exist_ok=True)
        (self.root / ".cornerstone" / "manifest.yaml").write_text(text, encoding="utf-8")

    def write_result(self, component: str, model: str, name: str | None = None) -> None:
        folder = self.root / "evals" / "results"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (name or f"20261018-000000-{component}-{model}.md")).write_text(
            f"# Eval results: {component}\n\nModel: `{model}`. Date: 2026-10-18.\n",
            encoding="utf-8")

    def messages(self) -> list[str]:
        return [finding.message for finding in
                framework_check.check_components(self.root, self.framework)]

    # models_tested
    def test_model_in_result_file_but_not_in_models_tested_fails(self) -> None:
        self.write_result("role.tester", "model-a")
        self.write_manifest(manifest_text(models="[]"))
        messages = self.messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("'role.tester'", messages[0])
        self.assertIn("has a result file for the model model-a", messages[0])
        self.assertIn("'models_tested' does not list it (P5)", messages[0])

    def test_model_listed_in_models_tested_passes(self) -> None:
        self.write_result("role.tester", "model-a")
        self.write_manifest(manifest_text(models="[model-a]"))
        self.assertEqual(self.messages(), [])

    def test_missing_models_tested_key_counts_as_empty(self) -> None:
        self.write_result("role.tester", "model-a")
        self.write_manifest(manifest_text(models=None))
        messages = self.messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("model-a", messages[0])

    def test_models_tested_that_is_not_a_list_counts_as_empty(self) -> None:
        self.write_result("role.tester", "model-a")
        self.write_manifest(manifest_text(models="model-a"))
        messages = self.messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("'models_tested' does not list it", messages[0])

    def test_extra_listed_models_are_fine(self) -> None:
        self.write_result("role.tester", "model-a")
        self.write_manifest(manifest_text(models="[model-a, model-b]"))
        self.assertEqual(self.messages(), [])

    def test_two_result_models_and_one_listed_gives_one_finding_for_the_missing_one(self) -> None:
        self.write_result("role.tester", "model-a")
        self.write_result("role.tester", "model-b")
        self.write_manifest(manifest_text(models="[model-a]"))
        messages = self.messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("model-b", messages[0])
        self.assertNotIn("model-a", messages[0])

    def test_component_without_result_file_may_list_no_models(self) -> None:
        self.write_manifest(manifest_text(models="[]"))
        self.assertEqual(self.messages(), [])

    def test_result_file_of_a_component_not_in_the_manifest_is_ignored(self) -> None:
        self.write_result("role.other", "model-a")
        self.write_manifest(manifest_text(models="[]"))
        self.assertEqual(self.messages(), [])

    def test_result_file_of_another_component_does_not_count_for_this_one(self) -> None:
        self.write_result("role.other", "model-a")
        self.write_manifest(manifest_text(models="[]") +
                            "- id: role.other\n  kind: role\n  eval: evals/o/\n"
                            "  review_by: '2027-04-17'\n  owner: brawblan\n"
                            "  models_tested: []\n")
        messages = self.messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("'role.other'", messages[0])

    # owner
    def test_manifest_entry_without_owner_key_fails(self) -> None:
        self.write_manifest(manifest_text(owner=None))
        messages = self.messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("'role.tester' has no owner (P5)", messages[0])

    def test_manifest_entry_with_empty_or_blank_owner_fails(self) -> None:
        for owner in ('""', "''", "null", "~", "'   '"):
            with self.subTest(owner=owner):
                self.write_manifest(manifest_text(owner=owner))
                messages = self.messages()
                self.assertEqual(len(messages), 1)
                self.assertIn("has no owner (P5)", messages[0])

    def test_check_with_empty_eval_and_an_owner_passes(self) -> None:
        # D43 exception still holds in a manifest.
        self.write_manifest("components:\n- id: check.k6\n  kind: check\n  eval: ''\n"
                            "  owner: brawblan\n  review_by: '2027-04-17'\n"
                            "  models_tested: []\n")
        self.assertEqual(self.messages(), [])

    def test_check_with_empty_eval_and_no_owner_fails_only_for_the_owner(self) -> None:
        self.write_manifest("components:\n- id: check.k6\n  kind: check\n  eval: ''\n"
                            "  review_by: '2027-04-17'\n")
        messages = self.messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("has no owner (P5)", messages[0])

    # adapter lists
    def test_adapter_component_list_is_not_tested_for_owner_or_models(self) -> None:
        self.write_result("role.tester", "model-a")
        # LIST_OK has no owner and no models_tested, and role.tester has a result file.
        self.assertEqual(self.messages(), [])

    def test_component_problems_adapter_list_entry_needs_no_owner_or_models(self) -> None:
        entry = {"id": "role.tester", "kind": "role", "eval": "evals/role-tester/"}
        tested = {"role.tester": ["model-a"]}
        self.assertEqual(framework_check.component_problems(entry, False, tested), [])

    def test_component_problems_manifest_entry_reports_owner_and_models(self) -> None:
        entry = {"id": "role.tester", "kind": "role", "eval": "evals/role-tester/",
                 "review_by": "2027-04-17"}
        problems = framework_check.component_problems(entry, True, {"role.tester": ["m"]})
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("no owner" in problem for problem in problems))
        self.assertTrue(any("model m" in problem for problem in problems))

    def test_component_problems_without_tested_argument_skips_the_models_rule(self) -> None:
        entry = {"id": "role.tester", "kind": "role", "eval": "evals/role-tester/",
                 "review_by": "2027-04-17", "owner": "brawblan"}
        self.assertEqual(framework_check.component_problems(entry, True), [])


class RepoDataTest(unittest.TestCase):
    """The adapter lists and the manifest of this repo pass the rule (issue #65)."""

    def test_this_repo_passes(self) -> None:
        root = Path(__file__).resolve().parents[2]  # stone/tests/<this file> -> repo root
        self.assertEqual(framework_check.check_components(root, root / "framework"), [])

    def test_this_repo_manifest_has_owners_and_lists_the_result_models(self) -> None:
        root = Path(__file__).resolve().parents[2]
        manifest = yaml.safe_load((root / ".cornerstone" / "manifest.yaml")
                                  .read_text(encoding="utf-8"))
        entries = {entry["id"]: entry for entry in manifest["components"]}
        for entry in entries.values():
            self.assertTrue(str(entry.get("owner") or "").strip(), entry["id"])
        tested = results.result_models(root)
        self.assertTrue(tested, "this repo has result files")
        for component, models in tested.items():
            if component not in entries:  # a result of a component that is not in the manifest
                continue
            for model in models:
                self.assertIn(model, entries[component].get("models_tested") or [],
                              f"{component} lists {model}")


if __name__ == "__main__":
    unittest.main()
