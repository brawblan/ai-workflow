"""Tests for the reader path of `stone usage` with the OpenCode adapter (issue #328, D122)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stone import cli, eval_rates, usage

REPO = Path(__file__).resolve().parents[2]
FRAMEWORK = REPO / "framework"
ADAPTER = FRAMEWORK / "adapters" / "opencode"
SQL = (Path(__file__).parent / "fixtures" / "usage_reader" / "sessions.sql").read_text("utf-8")

PEAK = "ses_e18faf89effeNwcjlvdItb1p4d"
OFFPEAK = "ses_offpeak0deepseek0copy"
GLM = "ses_e18de5fdbffeLeAFgM4yAC747Y"
CHILD = "ses_child0of0glm0session"
BEAM = "ses_e18de4476fferOvlWQvZ6eM2bq"


def load_parser():
    spec = importlib.util.spec_from_file_location("oc_parser_under_test",
                                                  ADAPTER / "parsers" / "opencode.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*args: str, home: str | None = None) -> tuple[int, str]:
    out = io.StringIO()
    env = {"HOME": home} if home else {}
    with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
        code = cli.main(["usage", "--root", str(REPO), "--harness", "opencode",
                         "--framework", str(FRAMEWORK), *args])
    return code, out.getvalue()


class ReaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = self.dir / "opencode.db"
        con = sqlite3.connect(self.db)
        con.executescript(SQL)
        con.close()

    def data(self, *args: str) -> dict:
        code, text = run(str(self.db), "--json", *args)
        self.assertEqual(code, 0, text)
        return json.loads(text)

    def row(self, name: str, *args: str) -> dict:
        return next(r for r in self.data(*args)["sessions"] if r["session"] == name)


class AdapterFilesTest(unittest.TestCase):
    def test_usage_yaml_loads_with_reader_and_rates(self) -> None:
        fmt = usage.load_format(FRAMEWORK, "opencode")
        self.assertTrue((ADAPTER / fmt["reader"]["parser"]).is_file())
        self.assertTrue(fmt["reader"]["databases"])
        self.assertTrue((ADAPTER / fmt["rates"]).is_file())
        self.assertIn("models", eval_rates.load(ADAPTER / fmt["rates"]))

    def test_adapter_doc_names_usage_yaml(self) -> None:
        line = next(x for x in (FRAMEWORK / "adapters" / "opencode.md").read_text("utf-8")
                    .splitlines() if x.startswith("| Token report"))
        self.assertIn("opencode/usage.yaml", line)
        self.assertNotIn("No `usage.yaml`", line)


class RowsTest(ReaderTestCase):
    def test_peak_session_tokens(self) -> None:
        r = self.row(PEAK)
        self.assertEqual((r["input"], r["output"], r["thinking"]), (5262 + 82, 39 + 9 + 12, 12))
        self.assertEqual((r["cache_read"], r["cache_write"]["5m"], r["calls"]), (1792 + 7040, 0, 2))
        self.assertEqual((r["kind"], r["model"]), ("main", "opencode-go/deepseek-v4.1-flash"))

    def test_glm_and_subagent_rows(self) -> None:
        for name, kind in ((GLM, "main"), (CHILD, "subagent")):
            r = self.row(name)
            self.assertEqual(r["kind"], kind)
            self.assertEqual((r["input"], r["output"], r["thinking"]),
                             (5705 + 2678, 12 + 15 + 24, 24))
            self.assertEqual((r["cache_read"], r["calls"]), (5440, 2))
            self.assertEqual(r["model"], "opencode-go/glm-5.3-flash")

    def test_beam_free_row_tokens(self) -> None:
        r = self.row(BEAM)
        self.assertEqual((r["input"], r["output"], r["thinking"]), (4113 + 93, 14 + 33 + 3 + 22, 55))
        self.assertEqual(r["cache_read"], 1728 + 5824)

    def test_six_sessions(self) -> None:
        self.assertEqual(len(self.data()["sessions"]), 6)


class CostTest(ReaderTestCase):
    def test_peak_and_off_peak_cost(self) -> None:
        peak = (0.30 * 5344 + 1.20 * 60 + 0.006 * 8832) / 1e6
        off = (0.15 * 5344 + 0.60 * 60 + 0.003 * 8832) / 1e6
        a, b = self.row(PEAK), self.row(OFFPEAK)
        self.assertAlmostEqual(a["cost"], peak, places=6)
        self.assertAlmostEqual(b["cost"], off, places=6)
        self.assertAlmostEqual(b["cost"] * 2, a["cost"], places=6)
        self.assertEqual((a["peak_calls"], b["peak_calls"]), (2, 0))

    def test_glm_cost_has_no_peak(self) -> None:
        r = self.row(GLM)
        self.assertAlmostEqual(r["cost"], (0.15 * 8383 + 0.50 * 51 + 0.03 * 5440) / 1e6, places=6)
        self.assertEqual((r["peak_calls"], r["unrated_calls"]), (0, 0))

    def test_unrated_session(self) -> None:
        r = self.row(BEAM)
        self.assertIsNone(r["cost"])
        self.assertEqual(r["unrated_calls"], 2)
        _, text = run(str(self.db))
        line = next(x for x in text.splitlines() if BEAM in x)
        self.assertIn("—", line)

    def test_totals_and_shares(self) -> None:
        result = self.data()
        self.assertEqual(result["unit"], "usd")
        rows = result["sessions"]
        self.assertAlmostEqual(result["totals"]["cost"],
                               sum(r["cost"] for r in rows if r["cost"] is not None), places=5)
        self.assertEqual(result["totals"]["calls"], 11)
        self.assertAlmostEqual(sum(result["totals"]["shares"].values()), 1.0, places=2)
        self.assertAlmostEqual(sum(r["share"] for r in rows), 1.0, places=2)

    def test_text_columns(self) -> None:
        code, text = run(str(self.db))
        self.assertEqual(code, 0)
        self.assertIn("Input", text)
        self.assertIn("Cost (USD)", text)
        self.assertRegex(text, r"\$0\.00\d\d")
        self.assertRegex(text, re.escape("$0.0017"))


class FilterTest(ReaderTestCase):
    def test_since_filter(self) -> None:
        self.assertEqual(len(self.data("--since", "2000-01-01")["sessions"]), 6)
        self.assertEqual(self.data("--since", "2099-01-01")["sessions"], [])

    def test_parser_root_filter(self) -> None:
        parser = load_parser()
        self.assertEqual(len(parser.sessions(self.db, Path("/work/project"))), 6)
        self.assertEqual(len(parser.sessions(self.db, None)), 6)
        self.assertEqual(parser.sessions(self.db, Path("/elsewhere")), [])
        self.assertEqual(parser.sessions(self.db, Path("/work/proj")), [])


class ErrorTest(ReaderTestCase):
    def test_missing_default_database(self) -> None:
        code, text = run("--json", home=str(self.dir))
        self.assertEqual(code, 2)
        self.assertIn("stone usage:", text)
        self.assertIn("opencode.db", text)

    def test_path_not_a_file(self) -> None:
        code, text = run(str(self.dir))
        self.assertEqual(code, 2)
        self.assertIn("stone usage:", text)

    def test_database_without_tables(self) -> None:
        empty = self.dir / "empty.db"
        sqlite3.connect(empty).execute("CREATE TABLE other (x)").connection.close()
        code, text = run(str(empty))
        self.assertEqual(code, 2)
        self.assertIn("schema", text.lower())


class WeightedPathTest(unittest.TestCase):
    def test_claude_code_json_has_no_unit(self) -> None:
        out = io.StringIO()
        sample = REPO / "stone" / "tests" / "fixtures" / "usage" / "project" / "sess1.jsonl"
        with contextlib.redirect_stdout(out):
            code = cli.main(["usage", "--root", str(REPO), "--harness", "claude-code",
                             "--json", str(sample)])
        self.assertEqual(code, 0)
        self.assertNotIn("unit", json.loads(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
