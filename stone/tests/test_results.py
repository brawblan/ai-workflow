"""Tests for `stone.results`: read the component and the model from the eval result files (D50)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stone import results


class ResultModelsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.folder = self.root / "evals" / "results"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / name).write_text(text, encoding="utf-8")

    def result(self, name: str, component: str, model: str) -> None:
        self.write(name, f"# Eval results: {component}\n\nModel: `{model}`. Date: 2026-10-18.\n\n"
                         "| Scenario | Variant |\n| --- | --- |\n| T1 | with |\n")

    def test_missing_results_folder_gives_an_empty_dict(self) -> None:
        self.assertEqual(results.result_models(self.root), {})

    def test_empty_results_folder_gives_an_empty_dict(self) -> None:
        self.folder.mkdir(parents=True)
        self.assertEqual(results.result_models(self.root), {})

    def test_one_file_gives_its_component_and_model(self) -> None:
        self.result("a.md", "role.tester", "model-a")
        self.assertEqual(results.result_models(self.root), {"role.tester": ["model-a"]})

    def test_models_of_one_component_are_sorted(self) -> None:
        self.result("1.md", "role.tester", "model-z")
        self.result("2.md", "role.tester", "model-a")
        self.result("3.md", "role.tester", "model-m")
        self.assertEqual(results.result_models(self.root),
                         {"role.tester": ["model-a", "model-m", "model-z"]})

    def test_duplicate_models_are_listed_once(self) -> None:
        self.result("1.md", "role.tester", "model-a")
        self.result("2.md", "role.tester", "model-a")
        self.assertEqual(results.result_models(self.root), {"role.tester": ["model-a"]})

    def test_components_are_kept_apart(self) -> None:
        self.result("1.md", "role.tester", "model-a")
        self.result("2.md", "hook.protect-paths", "model-b")
        self.assertEqual(results.result_models(self.root),
                         {"role.tester": ["model-a"], "hook.protect-paths": ["model-b"]})

    def test_file_without_component_line_is_skipped(self) -> None:
        self.write("a.md", "Model: `model-a`. Date: 2026-10-18.\n")
        self.assertEqual(results.result_models(self.root), {})

    def test_file_without_model_is_skipped(self) -> None:
        self.write("a.md", "# Eval results: role.tester\n\nDate: 2026-10-18.\n")
        self.assertEqual(results.result_models(self.root), {})

    def test_file_with_empty_model_is_skipped(self) -> None:
        self.write("a.md", "# Eval results: role.tester\n\nModel: ``. Date: 2026-10-18.\n")
        self.assertEqual(results.result_models(self.root), {})

    def test_a_skipped_file_does_not_hide_a_good_file(self) -> None:
        self.write("a.md", "no header here\n")
        self.result("b.md", "role.tester", "model-a")
        self.assertEqual(results.result_models(self.root), {"role.tester": ["model-a"]})

    def test_file_name_is_not_parsed(self) -> None:
        # The name says another component and model. The content wins.
        self.result("20261018-000000-role.planner-model-x.md", "role.tester", "model-a")
        self.assertEqual(results.result_models(self.root), {"role.tester": ["model-a"]})

    def test_model_and_component_ids_with_dashes_are_read_whole(self) -> None:
        self.result("x.md", "hook.protect-paths", "claude-opus-5-5")
        self.assertEqual(results.result_models(self.root),
                         {"hook.protect-paths": ["claude-opus-5-5"]})

    def test_files_that_are_not_markdown_are_ignored(self) -> None:
        self.write("a.txt", "# Eval results: role.tester\n\nModel: `model-a`.\n")
        self.assertEqual(results.result_models(self.root), {})


if __name__ == "__main__":
    unittest.main()
