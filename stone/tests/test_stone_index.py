"""AC6 of #258: `stone index` runs `stone-index` from PATH and returns its exit code."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stone import cli

FAKE = f"""#!{sys.executable}
import json, os, sys
with open(os.environ["FAKE_OUT"], "w") as f:
    json.dump(sys.argv[1:], f)
sys.exit(int(os.environ.get("FAKE_CODE", "0")))
"""


@unittest.skipIf(os.name == "nt", "the fake binary is a POSIX script")
class StoneIndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.out = self.tmp / "args.json"

    def install_fake(self):
        exe = self.bin / "stone-index"
        exe.write_text(FAKE)
        exe.chmod(0o755)

    def run_index(self, args, code=0, path=None):
        env = {"PATH": path if path is not None else str(self.bin),
               "FAKE_OUT": str(self.out), "FAKE_CODE": str(code)}
        err = io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stderr(err):
            rc = cli.main(["index", *args])
        return rc, err.getvalue()

    def received(self):
        return json.loads(self.out.read_text())

    def test_arguments_reach_the_binary_unchanged(self):
        self.install_fake()
        args = ["--version", "--help", "--", "a b", "find", "-x", ""]
        rc, _ = self.run_index(args)
        self.assertEqual(rc, 0)
        self.assertEqual(self.received(), args)

    def test_no_arguments_runs_the_binary_with_none(self):
        self.install_fake()
        rc, _ = self.run_index([])
        self.assertEqual(rc, 0)
        self.assertEqual(self.received(), [])

    def test_exit_code_of_the_binary_comes_back(self):
        self.install_fake()
        for code in (0, 1, 2, 7):
            with self.subTest(code=code):
                rc, _ = self.run_index(["x"], code=code)
                self.assertEqual(rc, code)

    def test_missing_binary_exits_2_and_prints_install_commands(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        rc, err = self.run_index(["find"], path=str(empty))
        self.assertEqual(rc, 2)
        for text in ("uv tool install", "pipx install", "cargo install"):
            self.assertIn(text, err)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
