"""Golden-file test: `stone render` for the full-project profile.

The test renders full-project with a fixed config and a fixed date into a temporary repo. It
compares each written file byte for byte with its fixture. The compare and the update are in
`golden_helpers.py`. A fixture is in `golden/full-project/` or, if other profiles render the same
bytes, in `golden/_shared/` (D64).
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from golden_helpers import TODAY, golden_differences, tree_files, update_golden, updating
from stone import render

PROFILE = "full-project"
FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
GOLDEN = Path(__file__).resolve().parent / "golden" / PROFILE
CONFIG_PATH = ".cornerstone/config.yaml"
CONFIG = f"""framework_version: 0.8.0
harness: claude-code
model_profile: claude-5
profiles: [{PROFILE}]
branches: {{integration: dev, main: main}}
commands:
  install: pip install .
  test_unit: python -m unittest
  all_checks: make check
paths:
  tests: [tests/, "**/*.test.js"]
  checks: [.github/workflows/, .cornerstone/checks/]
  plans: docs/plans/
owners: {{default: octocat}}
"""


def render_profile(root: Path) -> render.Result:
    (root / ".cornerstone").mkdir(parents=True)
    (root / CONFIG_PATH).write_text(CONFIG, encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()):
        return render.render(root, FRAMEWORK, today=TODAY)


class GoldenFullProjectTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name) / "repo"

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_golden_full_project_matches_the_fixtures(self) -> None:
        result = render_profile(self.root)
        self.assertEqual(result.exit_code, 0)
        files = tree_files(self.root, frozenset({CONFIG_PATH}))
        if updating():
            update_golden(GOLDEN, files)
        self.assertTrue(tree_files(GOLDEN), f"{GOLDEN} has no fixtures. Run the test with "
                        "STONE_UPDATE_GOLDEN=1 to write them.")
        differences = golden_differences(GOLDEN, files)
        self.assertEqual(differences, [], "\n".join(differences))
        fixtures = tree_files(GOLDEN)
        self.assertIn(".cornerstone/manifest.yaml", fixtures)
        self.assertIn(".cornerstone/checks/instruction_size.py", fixtures)
        self.assertNotIn(CONFIG_PATH, fixtures)


if __name__ == "__main__":
    unittest.main()
