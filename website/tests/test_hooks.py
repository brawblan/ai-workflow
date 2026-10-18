"""Tests for the link rewrite in website/hooks.py. Run: python -m unittest discover -s website/tests"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hooks import evals_index, rewrite_links  # noqa: E402

ON_SITE = {"framework/principles.md", "docs/guides/README.md", "docs/guides/small-change.md"}


def rewrite(markdown: str, repo_root: str = "/repo") -> str:
    return rewrite_links(markdown, "docs/guides/README.md", "docs/guides/README.md", repo_root,
                         lambda path: path in ON_SITE)


class RewriteLinksTest(unittest.TestCase):
    def test_link_on_the_site_stays(self) -> None:
        text = "[Principles](../../framework/principles.md#p1-checks-decide)"
        self.assertEqual(rewrite(text), text)

    def test_sibling_link_on_the_site_stays(self) -> None:
        text = "[Small change](small-change.md)"
        self.assertEqual(rewrite(text), text)

    def test_file_off_the_site_goes_to_github_blob(self) -> None:
        text = "[install](../../README.md#install-the-plugin-for-claude-code)"
        self.assertEqual(rewrite(text), "[install](https://github.com/brawblan/ai-workflow/blob/main/"
                                        "README.md#install-the-plugin-for-claude-code)")

    def test_folder_off_the_site_goes_to_github_tree(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "plugins" / "workflow").mkdir(parents=True)
            text = "[skills](../../plugins/workflow/)"
            self.assertEqual(rewrite(text, root),
                             "[skills](https://github.com/brawblan/ai-workflow/tree/main/plugins/workflow)")

    def test_external_and_anchor_links_stay(self) -> None:
        for text in ("[a](https://example.com/x.md)", "[b](#pick-a-guide)", "[c](mailto:a@b.c)",
                     "[d](/absolute/path.md)"):
            self.assertEqual(rewrite(text), text)

    def test_link_outside_the_repo_stays(self) -> None:
        text = "[x](../../../outside.md)"
        self.assertEqual(rewrite(text), text)

    def test_mirrored_page_uses_its_repo_path(self) -> None:
        text = "[config](../.cornerstone/config.yaml)"
        result = rewrite_links(text, "stone/README.md", "stone/README.md", "/repo", lambda _: False)
        self.assertEqual(result, "[config](https://github.com/brawblan/ai-workflow/blob/main/"
                                 ".cornerstone/config.yaml)")


if __name__ == "__main__":
    unittest.main()


RESULT = """# Eval results: role.tester

Model: `{model}`. Date: {date}.

| Scenario | Variant |
| --- | --- |
| T1 | with |
"""


class EvalsIndexTest(unittest.TestCase):
    def make(self, root: str, results: dict[str, str]) -> Path:
        evals = Path(root) / "evals"
        (evals / "results").mkdir(parents=True)
        (evals / "role-tester").mkdir()
        (evals / "role-tester" / "scenarios.yaml").write_text("component: role.tester\n")
        for name, text in results.items():
            (evals / "results" / name).write_text(text, encoding="utf-8")
        return evals

    def test_no_results_gives_a_notice(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(evals_index(self.make(root, {})), "No eval results yet.")

    def test_latest_run_table_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            evals = self.make(root, {
                "20261001-000000-role.tester-m1.md": RESULT.format(model="m1", date="2026-10-01"),
                "20261018-000000-role.tester-m2.md": RESULT.format(model="m2", date="2026-10-18"),
            })
            text = evals_index(evals)
        self.assertIn("## role.tester", text)
        self.assertIn("Latest run: 2026-10-18, model `m2`", text)
        self.assertIn("[Scenarios](./role-tester/scenarios.yaml)", text)
        self.assertIn("- 2026-10-01, `m1`: [result file](results/20261001-000000-role.tester-m1.md)",
                      text)
        self.assertEqual(text.count("| T1 | with |"), 1)

    def test_file_that_is_not_a_result_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(evals_index(self.make(root, {"notes.md": "# Notes\n"})),
                             "No eval results yet.")
