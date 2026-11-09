"""Tests for `stone usage` (issue #297). Fixtures are synthetic: stone/tests/fixtures/usage/."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from stone import cli, framework_check, usage

REPO = Path(__file__).resolve().parents[2]
FRAMEWORK = REPO / "framework"
FIXTURES = Path(__file__).parent / "fixtures" / "usage"
PROJECT = FIXTURES / "project"
MAIN = PROJECT / "sess1.jsonl"
SUB = PROJECT / "sess1" / "subagents" / "agent-a.jsonl"


def run(*args: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(["usage", "--root", str(REPO), "--harness", "claude-code", *args])
    return code, out.getvalue()


def data(*args: str) -> dict:
    code, text = run("--json", *args)
    assert code == 0, text
    return json.loads(text)


def row(result: dict, name: str) -> dict:
    return next(r for r in result["sessions"] if r["session"] == name)


class PathTest(unittest.TestCase):
    def test_file_path_reads_one_transcript(self) -> None:
        result = data(str(MAIN))
        self.assertEqual([r["session"] for r in result["sessions"]], ["sess1"])
        self.assertEqual(result["sessions"][0]["kind"], "main")

    def test_folder_path_includes_subagents(self) -> None:
        result = data(str(PROJECT))
        kinds = {r["session"]: r["kind"] for r in result["sessions"]}
        self.assertEqual(kinds, {"sess1": "main", "sess1/agent-a": "subagent"})

    def test_subagent_file_alone_has_kind_subagent(self) -> None:
        self.assertEqual(data(str(SUB))["sessions"][0]["kind"], "subagent")

    def test_default_folders_use_adapter_patterns(self) -> None:
        fmt = {"folders": [str(PROJECT.parent) + "/pro*", str(PROJECT.parent) + "/none*"]}
        self.assertEqual(usage.default_folders(Path("/x"), fmt), [PROJECT])

    def test_default_folders_key_and_home(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / "repo.v1"
            root.mkdir()
            key = str(root.resolve()).replace("/", "-").replace(".", "-")
            for name in (key, key + "-wt"):
                shutil.copytree(PROJECT, Path(home) / ".claude" / "projects" / name)
            fmt = usage.load_format(FRAMEWORK, "claude-code")
            with mock.patch.dict(os.environ, {"HOME": home}):
                found = usage.default_folders(root, fmt)
            self.assertEqual([p.name for p in found], [key, key + "-wt"])

    def test_no_path_reads_default_folders(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            root = Path(home) / "repo"
            root.mkdir()
            key = str(root.resolve()).replace("/", "-").replace(".", "-")
            shutil.copytree(PROJECT, Path(home) / ".claude" / "projects" / key)
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"HOME": home}), contextlib.redirect_stdout(out):
                code = cli.main(["usage", "--root", str(root), "--framework", str(FRAMEWORK),
                                 "--harness", "claude-code", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(out.getvalue())["sessions"]), 2)

    def test_no_path_and_no_folders_gives_empty_report(self) -> None:
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}):
            result = json.loads(run_with_root(home))
        self.assertEqual(result["sessions"], [])
        self.assertEqual(result["totals"]["calls"], 0)


def run_with_root(home: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(["usage", "--root", home, "--framework", str(FRAMEWORK),
                  "--harness", "claude-code", "--json"])
    return out.getvalue()


class SinceTest(unittest.TestCase):
    def test_since_keeps_calls_on_or_after_the_date(self) -> None:
        result = data(str(PROJECT), "--since", "2026-03-02")
        self.assertEqual([r["session"] for r in result["sessions"]], ["sess1"])
        self.assertEqual(result["sessions"][0]["calls"], 2)

    def test_since_first_day_keeps_everything(self) -> None:
        self.assertEqual(data(str(PROJECT), "--since", "2026-03-01")["totals"]["calls"], 7)

    def test_since_after_all_calls_is_empty(self) -> None:
        self.assertEqual(data(str(PROJECT), "--since", "2026-04-01")["sessions"], [])

    def test_since_bad_date_is_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run("--since", "not-a-date", str(PROJECT))


class ColumnsTest(unittest.TestCase):
    def test_text_has_all_columns(self) -> None:
        _, text = run(str(PROJECT))
        header = text.splitlines()[0]
        for name in ("Session", "Kind", "Model", "Effort", "Calls", "Cache read",
                     "Cache write 5m/1h", "Output (think)", "Context", "Rebuilds", "Share"):
            self.assertIn(name, header)

    def test_json_main_row_values(self) -> None:
        main = row(data(str(PROJECT)), "sess1")
        self.assertEqual(main["model"], "model-a")
        self.assertEqual(main["effort"], "high")
        self.assertEqual(main["cache_read"], 3000)
        self.assertEqual(main["cache_write"], {"5m": 90600, "1h": 80000})
        self.assertEqual(main["output"], 195)
        self.assertEqual(main["thinking"], 40)
        self.assertEqual(main["context"], 50001)

    def test_cache_write_total_without_split_counts_as_5m(self) -> None:
        # call r4 has only cache_creation_input_tokens = 100
        result = data(str(MAIN))
        self.assertEqual(result["sessions"][0]["cache_write"]["5m"], 500 + 40000 + 50000 + 100)

    def test_shares_of_sessions_add_up(self) -> None:
        total = sum(r["share"] for r in data(str(PROJECT))["sessions"])
        self.assertAlmostEqual(total, 1.0, places=3)

    def test_cost_uses_adapter_weights(self) -> None:
        # subagent: 20 input, 500 read, 20 output -> 20 + 50 + 100 = 170
        self.assertEqual(row(data(str(PROJECT)), "sess1/agent-a")["cost"], 170.0)

    def test_missing_effort_shows_dash(self) -> None:
        self.assertEqual(row(data(str(PROJECT)), "sess1/agent-a")["effort"], "-")


class DuplicateTest(unittest.TestCase):
    def test_same_request_id_counts_once(self) -> None:
        # the file has 7 assistant lines with usage-like data; r1 appears twice
        self.assertEqual(data(str(MAIN))["sessions"][0]["calls"], 6)

    def test_last_record_of_a_call_wins(self) -> None:
        # r1 has output 60 then 120; the total output is 120+50+10+5+5+5
        self.assertEqual(data(str(MAIN))["sessions"][0]["output"], 195)


class NoRequestIdTest(unittest.TestCase):
    def test_records_without_request_id_get_line_ids_and_count_once_per_line(self) -> None:
        record = json.loads(SUB.read_text().splitlines()[0])
        del record["requestId"]
        spec = usage.load_format(FRAMEWORK, "claude-code")["transcript"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            path.write_text((json.dumps(record) + "\n") * 2)
            self.assertEqual(len(usage.read_transcript(path, spec)), 2)


class RebuildTest(unittest.TestCase):
    def test_default_counts_idle_gap_with_large_write(self) -> None:
        # r3 (gap 29 min, write 50k) and r5 (gap 22 h, 1h write 40k)
        self.assertEqual(row(data(str(PROJECT)), "sess1")["rebuilds"], 2)

    def test_small_write_after_gap_is_not_a_rebuild(self) -> None:
        # r4: gap 30 min but write 100: not counted at the default limit
        result = data(str(MAIN), "--rebuild-tokens", "60000")
        self.assertEqual(result["sessions"][0]["rebuilds"], 0)

    def test_large_write_inside_cache_length_is_not_a_rebuild(self) -> None:
        # r2: write 40k after a 60 s gap; r6: 1h write 40k after 30 min with a 1h cache
        self.assertEqual(row(data(str(MAIN), "--rebuild-tokens", "45000"), "sess1")["rebuilds"], 1)

    def test_rebuild_tokens_lowers_the_limit(self) -> None:
        result = data(str(MAIN), "--rebuild-tokens", "50")
        self.assertEqual(result["sessions"][0]["rebuilds"], 3)   # r3, r4, r5
        self.assertEqual(result["rebuild_tokens"], 50)

    def test_limit_is_strictly_above(self) -> None:
        # r3 writes exactly 50000: not above 50000. r5 writes 40000, so none count.
        self.assertEqual(data(str(MAIN), "--rebuild-tokens", "50000")["sessions"][0]["rebuilds"], 0)

    def test_default_limit_is_30000(self) -> None:
        self.assertEqual(data(str(MAIN))["rebuild_tokens"], 30000)


class NeutralTest(unittest.TestCase):
    def test_usage_module_names_no_harness(self) -> None:
        source = (REPO / "stone" / "src" / "stone" / "usage.py").read_text(encoding="utf-8")
        pattern = re.compile(r"\b(" + "|".join(framework_check.VENDOR_NAMES) + r")\b", re.I)
        self.assertEqual(pattern.findall(source), [])

    def test_code_is_neutral_check_passes(self) -> None:
        self.assertEqual(framework_check.check_neutral_code(REPO / "stone" / "src" / "stone"), [])

    def test_weights_come_from_the_adapter_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fw = Path(tmp)
            (fw / "adapters" / "demo").mkdir(parents=True)
            fmt = usage.load_format(FRAMEWORK, "claude-code")
            fmt["weights"] = {k: 1 for k in fmt["weights"]}
            import yaml
            (fw / "adapters" / "demo" / "usage.yaml").write_text(yaml.safe_dump(fmt))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["usage", "--root", str(REPO), "--framework", str(fw), "--harness",
                          "demo", "--json", str(PROJECT / "sess1" / "subagents")])
            # weights all 1: 20 + 500 + 20 = 540
            self.assertEqual(json.loads(out.getvalue())["sessions"][0]["cost"], 540.0)

    def test_unit_note_is_in_text_and_json(self) -> None:
        _, text = run(str(PROJECT))
        self.assertEqual(text.splitlines()[-1],
                         "Cost is in relative units that follow the price ratios. It is not money.")
        self.assertIn("not money", data(str(PROJECT))["unit_note"])


class JsonTest(unittest.TestCase):
    def test_json_is_valid_and_has_the_report_keys(self) -> None:
        result = data(str(PROJECT))
        self.assertEqual(set(result), {"unit_note", "rebuild_tokens", "sessions", "totals"})
        self.assertEqual(result["totals"]["calls"], 7)

    def test_json_matches_text_data(self) -> None:
        result = data(str(PROJECT))
        _, text = run(str(PROJECT))
        self.assertEqual(text, usage.render_text(result))


class TotalsTest(unittest.TestCase):
    def test_totals_line_has_the_four_shares(self) -> None:
        _, text = run(str(PROJECT))
        line = next(l for l in text.splitlines() if l.startswith("Totals:"))
        self.assertEqual(line, "Totals: 7 calls. Share of cost: cache read 0.1%, "
                               "cache write 99.5%, output 0.4%, input 0.0%.")

    def test_json_totals_shares(self) -> None:
        shares = data(str(PROJECT))["totals"]["shares"]
        self.assertEqual(set(shares), {"cache_read", "cache_write", "output", "input"})
        self.assertAlmostEqual(sum(shares.values()), 1.0, places=3)


class BadInputTest(unittest.TestCase):
    def test_bad_line_and_no_usage_record_are_skipped(self) -> None:
        # the fixture has one bad line, one user record, one assistant record with no usage
        code, _ = run(str(MAIN))
        self.assertEqual(code, 0)
        self.assertEqual(data(str(MAIN))["totals"]["calls"], 6)

    def test_file_with_only_bad_lines_gives_empty_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.jsonl"
            path.write_text("{oops\n\n[1, 2]\n\"text\"\n", encoding="utf-8")
            code, text = run("--json", str(path))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)["sessions"], [])

    def test_empty_report_text_still_has_totals_and_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.jsonl"
            path.write_text("", encoding="utf-8")
            code, text = run(str(path))
        self.assertEqual(code, 0)
        self.assertIn("Totals: 0 calls", text)


class GoldenTest(unittest.TestCase):
    def test_text_golden(self) -> None:
        _, text = run(str(PROJECT))
        self.assertEqual(text, (FIXTURES / "expected.txt").read_text(encoding="utf-8"))

    def test_json_golden(self) -> None:
        _, text = run("--json", str(PROJECT))
        self.assertEqual(text, (FIXTURES / "expected.json").read_text(encoding="utf-8"))


class ExitCodeTest(unittest.TestCase):
    def test_missing_path_exits_2(self) -> None:
        code, text = run("/no/such/transcript-folder")
        self.assertEqual(code, 2)
        self.assertIn("no file or folder", text)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads any file")
    def test_unreadable_file_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            shutil.copy(MAIN, path)
            path.chmod(0)
            try:
                spec = usage.load_format(FRAMEWORK, "claude-code")["transcript"]
                with self.assertRaises(usage.UsageError):
                    usage.read_transcript(path, spec)
                code, _ = run(str(path))
            finally:
                path.chmod(0o600)
        self.assertEqual(code, 2)

    def test_missing_harness_adapter_exits_2(self) -> None:
        code, text = run("--harness", "no-such-harness", str(PROJECT))
        self.assertEqual(code, 2)
        self.assertIn("no-such-harness", text)

    def test_no_harness_given_and_no_config_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["usage", "--root", tmp, "--framework", str(FRAMEWORK),
                                 str(PROJECT)])
        self.assertEqual(code, 2)
        self.assertIn("--harness", out.getvalue())

    def test_harness_read_from_repo_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".cornerstone").mkdir()
            (Path(tmp) / ".cornerstone" / "config.yaml").write_text("harness: claude-code\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["usage", "--root", tmp, "--framework", str(FRAMEWORK),
                                 str(PROJECT)])
        self.assertEqual(code, 0)

    def test_since_helper_accepts_date_object(self) -> None:
        sessions = usage.load_sessions([MAIN], usage.load_format(FRAMEWORK, "claude-code")
                                       ["transcript"], date(2026, 3, 2))
        self.assertEqual(len(sessions[0].calls), 2)


if __name__ == "__main__":
    unittest.main()
