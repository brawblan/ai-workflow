"""The change checks of the evals leave out the files of the code index (issue #305)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from stone import evals


def git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True,
                   env={**evals.os.environ, **evals.GIT_ENV})


class ChangedIndexFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        git(self.path, "init", "-q")
        (self.path / "a.txt").write_text("a\n")
        git(self.path, "add", ".")
        git(self.path, "commit", "-q", "-m", "setup")
        self.ws = evals.Workspace(self.path, evals._git(self.path, "rev-parse", "HEAD"))

    def make(self, *names: str) -> None:
        for name in names:
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n")

    def test_index_files_are_not_a_change(self) -> None:
        self.make(".cornerstone/index.db", ".cornerstone/index.db-shm",
                  ".cornerstone/index.db-wal")
        self.assertEqual(evals._changed(self.ws), [])

    def test_only_changed_passes_with_index_files(self) -> None:
        self.make(".cornerstone/index.db", "docs/reports/BUG-1.md")
        item = {"check": "only_changed", "paths": ["docs/reports/"]}
        self.assertTrue(evals._only_changed(self.ws, item, self.path)[0])

    def test_other_cornerstone_files_stay_a_change(self) -> None:
        self.make(".cornerstone/index.db", ".cornerstone/other.txt")
        self.assertEqual(evals._changed(self.ws), [".cornerstone/other.txt"])

    def test_a_real_change_still_fails_only_changed(self) -> None:
        self.make(".cornerstone/index.db", "src/x.py")
        item = {"check": "only_changed", "paths": ["docs/reports/"]}
        passed, detail = evals._only_changed(self.ws, item, self.path)
        self.assertFalse(passed)
        self.assertEqual(detail, "src/x.py")


if __name__ == "__main__":
    unittest.main()
