"""Tests for the `models_tested` and `owner` fields that `stone render` writes (D50)."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import framework_check, render

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
TODAY = dt.date(2026, 10, 17)
CONFIG = """framework_version: 0.1.0
harness: claude-code
model_profile: claude-5
profiles: [single-ticket]
branches: {integration: dev, main: main}
commands:
  install: pip install .
  test_unit: python -m unittest
  all_checks: make check
paths:
  tests: [tests/]
  checks: [.github/workflows/, .cornerstone/checks/]
  plans: docs/plans/
owners: {default: octocat}
"""


class RenderModelsTestedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG, encoding="utf-8")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def render(self, today: dt.date = TODAY) -> render.Result:
        with contextlib.redirect_stderr(io.StringIO()):
            return render.render(self.root, FRAMEWORK, today=today)

    def manifest_path(self) -> Path:
        return self.root / render.MANIFEST

    def entries(self) -> dict[str, dict]:
        data = yaml.safe_load(self.manifest_path().read_text(encoding="utf-8"))
        return {entry["id"]: entry for entry in data["components"]}

    def edit_manifest(self, component: str, **fields: object) -> None:
        data = yaml.safe_load(self.manifest_path().read_text(encoding="utf-8"))
        for entry in data["components"]:
            if entry["id"] == component:
                entry.update(fields)
        self.manifest_path().write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def write_result(self, component: str, model: str, name: str) -> None:
        folder = self.root / "evals" / "results"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(
            f"# Eval results: {component}\n\nModel: `{model}`. Date: 2026-10-18.\n",
            encoding="utf-8")

    def check_messages(self) -> list[str]:
        return [finding.message for finding in
                framework_check.check_components(self.root, FRAMEWORK)]

    def test_models_tested_is_written_from_the_result_files(self) -> None:
        self.write_result("role.tester", "model-b", "r1.md")
        self.write_result("role.tester", "model-a", "r2.md")
        self.write_result("hook.protect-paths", "model-c", "r3.md")
        self.render()
        entries = self.entries()
        self.assertEqual(entries["role.tester"]["models_tested"], ["model-a", "model-b"])
        self.assertEqual(entries["hook.protect-paths"]["models_tested"], ["model-c"])

    def test_component_without_result_file_has_an_empty_models_tested(self) -> None:
        self.write_result("role.tester", "model-a", "r1.md")
        self.render()
        self.assertEqual(self.entries()["role.reviewer"]["models_tested"], [])

    def test_no_results_folder_gives_empty_lists(self) -> None:
        self.render()
        for entry in self.entries().values():
            self.assertEqual(entry["models_tested"], [], entry["id"])

    def test_stale_hand_written_list_is_replaced_by_the_result_files(self) -> None:
        self.render()
        self.edit_manifest("role.tester", models_tested=["hand-written", "stale"])
        self.write_result("role.tester", "model-a", "r1.md")
        self.render()
        self.assertEqual(self.entries()["role.tester"]["models_tested"], ["model-a"])

    def test_hand_written_list_without_result_file_is_cleared(self) -> None:
        self.render()
        self.edit_manifest("role.tester", models_tested=["hand-written"])
        self.render()
        self.assertEqual(self.entries()["role.tester"]["models_tested"], [])

    def test_a_new_result_file_adds_its_model_on_the_next_render(self) -> None:
        self.write_result("role.tester", "model-a", "r1.md")
        self.render()
        self.write_result("role.tester", "model-b", "r2.md")
        self.render()
        self.assertEqual(self.entries()["role.tester"]["models_tested"], ["model-a", "model-b"])

    def test_second_render_changes_nothing(self) -> None:
        self.write_result("role.tester", "model-a", "r1.md")
        self.render()
        before = self.manifest_path().read_text(encoding="utf-8")
        result = self.render(today=TODAY + dt.timedelta(days=30))
        self.assertEqual(result.wrote, [])
        self.assertEqual(self.manifest_path().read_text(encoding="utf-8"), before)

    def test_existing_owner_is_kept(self) -> None:
        self.render()
        self.edit_manifest("role.tester", owner="alice")
        self.render()
        self.assertEqual(self.entries()["role.tester"]["owner"], "alice")

    def test_empty_owner_in_the_old_manifest_is_filled_from_owners_default(self) -> None:
        self.render()
        for empty in ("", None):
            with self.subTest(owner=empty):
                self.edit_manifest("role.tester", owner=empty)
                self.render()
                self.assertEqual(self.entries()["role.tester"]["owner"], "octocat")

    def test_new_entry_gets_owners_default(self) -> None:
        self.render()
        for entry in self.entries().values():
            self.assertEqual(entry["owner"], "octocat", entry["id"])

    def test_check_has_one_finding_before_render_and_none_after(self) -> None:
        self.render()
        self.write_result("role.tester", "model-a", "r1.md")
        before = self.check_messages()
        self.assertEqual(len(before), 1)
        self.assertIn("'role.tester'", before[0])
        self.assertIn("model-a", before[0])
        self.render()
        self.assertEqual(self.check_messages(), [])


if __name__ == "__main__":
    unittest.main()
