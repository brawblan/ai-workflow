"""Issue #224: the configs and the script of the Prettier check for the generated files."""

import contextlib
import datetime as dt
import io
import os
import tempfile
import unittest
from pathlib import Path

from stone import render
from test_render import FRAMEWORK

FORMAT = Path(__file__).resolve().parent / "format"
SCRIPT = FORMAT / "check_render_format.sh"


class FormatConfigsTest(unittest.TestCase):
    def test_script_exists_and_is_executable(self) -> None:
        self.assertTrue(SCRIPT.is_file())
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertIn("set -euo pipefail", SCRIPT.read_text(encoding="utf-8"))

    def test_the_two_configs_exist(self) -> None:
        names = sorted(path.name for path in FORMAT.glob("*.yaml"))
        self.assertEqual(names, ["all-options.yaml", "all-profiles.yaml"])

    def test_each_config_renders_without_error(self) -> None:
        for config in sorted(FORMAT.glob("*.yaml")):
            with self.subTest(config=config.name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / ".cornerstone").mkdir()
                (root / ".cornerstone" / "config.yaml").write_text(
                    config.read_text(encoding="utf-8"), encoding="utf-8")
                with contextlib.redirect_stderr(io.StringIO()):
                    result = render.render(root, FRAMEWORK, today=dt.date(2026, 10, 30))
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.drift, [])
                self.assertTrue((root / render.MANIFEST).is_file())


if __name__ == "__main__":
    unittest.main()
