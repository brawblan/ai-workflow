"""The home page version line must match the stone version."""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

import stone

REPO = Path(__file__).resolve().parents[2]
FILES = ("README.md", "website/content/index.md")
PATTERN = re.compile(r"^Version (\d+\.\d+\.\d+)\. ")


def _versions(name: str) -> list[str]:
    text = (REPO / name).read_text(encoding="utf-8")
    found = []
    for line in text.splitlines():
        match = PATTERN.match(line)
        if match:
            found.append(match.group(1))
    return found


def _hint(name: str) -> str:
    return (
        f"{name}: update the 'Version X.Y.Z.' line "
        "(step 3 of the release checklist in framework/versioning.md)."
    )


class VersionTextTest(unittest.TestCase):
    def test_one_version_line_per_file(self) -> None:
        for name in FILES:
            with self.subTest(file=name):
                found = _versions(name)
                self.assertEqual(len(found), 1, f"{_hint(name)} Found {found}.")

    def test_matches_package_version(self) -> None:
        for name in FILES:
            with self.subTest(file=name):
                found = _versions(name)
                self.assertEqual(
                    found, [stone.__version__],
                    f"{_hint(name)} stone.__version__ is {stone.__version__}.",
                )

    def test_matches_pyproject_version(self) -> None:
        data = tomllib.loads((REPO / "stone" / "pyproject.toml").read_text(encoding="utf-8"))
        version = data["project"]["version"]
        for name in FILES:
            with self.subTest(file=name):
                self.assertEqual(
                    _versions(name), [version],
                    f"{_hint(name)} pyproject.toml version is {version}.",
                )


def _cargo_hint(version: str, other: str) -> str:
    return (
        f"indexer/Cargo.toml [package] version is {version}, but {other}. "
        "Set both to the same version "
        "(step 3 of the release checklist in framework/versioning.md)."
    )


def _cargo_version() -> str:
    data = tomllib.loads((REPO / "indexer" / "Cargo.toml").read_text(encoding="utf-8"))
    return data["package"]["version"]


class IndexerVersionTest(unittest.TestCase):
    def test_cargo_version_matches_package_version(self) -> None:
        version = _cargo_version()
        self.assertEqual(
            version, stone.__version__,
            _cargo_hint(version, f"stone.__version__ is {stone.__version__}"),
        )

    def test_cargo_version_matches_pyproject_version(self) -> None:
        data = tomllib.loads((REPO / "stone" / "pyproject.toml").read_text(encoding="utf-8"))
        expected = data["project"]["version"]
        version = _cargo_version()
        self.assertEqual(
            version, expected,
            _cargo_hint(version, f"pyproject.toml version is {expected}"),
        )


if __name__ == "__main__":
    unittest.main()
