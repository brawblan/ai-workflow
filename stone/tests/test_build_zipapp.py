"""Tests for stone/build_zipapp.py (issue #253)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "stone" / "build_zipapp.py"
SRC_STONE = ROOT / "stone" / "src" / "stone"


def build(out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT, check=True,
    )


class ZipappBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.pyz = Path(cls._tmp.name) / "stone.pyz"
        build(cls.pyz)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def names(self) -> list[str]:
        with zipfile.ZipFile(self.pyz) as z:
            return z.namelist()

    def test_ac2_starts_with_shebang(self) -> None:
        self.assertEqual(self.pyz.read_bytes()[:23], b"#!/usr/bin/env python3\n")

    def test_ac2_main_at_root_calls_cli_main(self) -> None:
        with zipfile.ZipFile(self.pyz) as z:
            self.assertIn("__main__.py", z.namelist())
            text = z.read("__main__.py").decode()
        self.assertIn("from stone.cli import main", text)
        self.assertIn("main()", text)

    def test_ac2_holds_stone_and_yaml(self) -> None:
        names = self.names()
        self.assertIn("stone/cli.py", names)
        self.assertIn("yaml/__init__.py", names)

    def test_ac2_file_is_executable(self) -> None:
        self.assertTrue(os.access(self.pyz, os.X_OK))

    def test_ac3_no_compiled_members(self) -> None:
        for name in self.names():
            self.assertFalse(name.endswith((".so", ".pyd", ".dylib", ".pyc")), name)
            self.assertNotIn("__pycache__", name.split("/"), name)

    def test_ac4_version(self) -> None:
        import stone

        result = subprocess.run(
            [sys.executable, str(self.pyz), "--version"],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"stone {stone.__version__}")

    def test_ac4_check_passes_on_this_repo(self) -> None:
        result = subprocess.run(
            [sys.executable, str(self.pyz), "check"],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ac5_fixed_times_and_sorted_names(self) -> None:
        with zipfile.ZipFile(self.pyz) as z:
            infos = z.infolist()
        for info in infos:
            self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0), info.filename)
        names = [i.filename for i in infos]
        self.assertEqual(names[0], "__main__.py")
        self.assertEqual(names[1:], sorted(names[1:]))

    def test_ac5_two_builds_are_identical_despite_mtime_change(self) -> None:
        source = SRC_STONE / "cli.py"
        old = source.stat()
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a" / "stone.pyz"
            second = Path(tmp) / "b" / "stone.pyz"
            build(first)
            try:
                os.utime(source, (old.st_atime + 86400, old.st_mtime + 86400))
                build(second)
            finally:
                os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
            self.assertEqual(first.read_bytes(), second.read_bytes())


class PackagingTest(unittest.TestCase):
    def test_ac9_dependencies_unchanged(self) -> None:
        data = tomllib.loads((ROOT / "stone" / "pyproject.toml").read_text())
        self.assertEqual(data["project"]["dependencies"], ["PyYAML>=6.0"])


if __name__ == "__main__":
    unittest.main()
