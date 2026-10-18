"""Tests for the link rewrite in website/hooks.py. Run: python -m unittest discover -s website/tests"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hooks import rewrite_links  # noqa: E402

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
