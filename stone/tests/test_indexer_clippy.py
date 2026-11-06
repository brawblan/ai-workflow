"""The indexer clippy length cap must match the profile function length cap (K9)."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


class IndexerClippyTest(unittest.TestCase):
    def test_threshold_matches_function_lines(self) -> None:
        clippy = tomllib.loads((REPO / "indexer" / "clippy.toml").read_text(encoding="utf-8"))
        config = yaml.safe_load((REPO / ".cornerstone" / "config.yaml").read_text(encoding="utf-8"))
        threshold = clippy["too-many-lines-threshold"]
        cap = config["limits"]["function_lines"]
        self.assertEqual(
            threshold, cap,
            f"indexer/clippy.toml too-many-lines-threshold is {threshold}, but "
            f"limits.function_lines in .cornerstone/config.yaml is {cap}. "
            "Set both to the same number.",
        )

    def test_cargo_toml_enables_too_many_lines(self) -> None:
        data = tomllib.loads((REPO / "indexer" / "Cargo.toml").read_text(encoding="utf-8"))
        level = data.get("lints", {}).get("clippy", {}).get("too_many_lines")
        self.assertIn(
            level, ("warn", "deny"),
            f"indexer/Cargo.toml [lints.clippy] too_many_lines is {level!r}. "
            "Set it to \"warn\" or \"deny\" so clippy enforces the K9 cap.",
        )


if __name__ == "__main__":
    unittest.main()
