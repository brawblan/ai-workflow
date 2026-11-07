"""Tests for the token metrics in the `stone eval` result (#271)."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from stone import cli, eval_metrics, evals
from stone.evals import Run

REPO = Path(__file__).resolve().parents[2]
EVAL_YAML = REPO / "framework" / "adapters" / "claude-code" / "eval.yaml"
PASS = [{"kind": "outcome", "pass": True}, {"kind": "contract", "pass": True}]
FAIL = [{"kind": "outcome", "pass": False}, {"kind": "contract", "pass": True}]


def make_run(scenario: str, variant: str, trial: int = 1, cost: float | None = 0.1,
             checks: list | None = None, **usage: object) -> Run:
    data: dict = dict(usage)
    if cost is not None:
        data["cost_usd"] = cost
    return Run(scenario, variant, trial, checks=PASS if checks is None else checks, usage=data)


def transcript_lines() -> list[str]:
    return [
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "id": "a", "name": "Bash", "input": {}},
            {"type": "tool_use", "id": "b", "name": "Read", "input": {}}]}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "a", "content": "hello"}]}}),
        "not json",
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "b", "content": [
                {"type": "text", "text": "abc"}, {"type": "text", "text": "de"}]}]}}),
        json.dumps({"type": "result", "num_turns": 2}),
    ]


class AdapterTests(unittest.TestCase):
    def test_ac1_output_map_has_cache_paths(self) -> None:
        config = evals.load_run_config(EVAL_YAML)
        self.assertEqual(config["output"]["cache_read_tokens"], "usage.cache_read_input_tokens")
        self.assertEqual(config["output"]["cache_creation_tokens"],
                         "usage.cache_creation_input_tokens")

    def test_ac1_parse_output_reads_cache_tokens(self) -> None:
        config = evals.load_run_config(EVAL_YAML)
        result = {"type": "result", "result": "ok", "total_cost_usd": 0.1234, "num_turns": 3,
                  "usage": {"input_tokens": 5, "output_tokens": 7,
                            "cache_read_input_tokens": 1000,
                            "cache_creation_input_tokens": 200}}
        usage = evals.parse_output(json.dumps(result), config["output"], config["output_where"])
        self.assertEqual(usage["cache_read_tokens"], 1000)
        self.assertEqual(usage["cache_creation_tokens"], 200)
        self.assertEqual(usage["turns"], 3)


class TranscriptTests(unittest.TestCase):
    def test_ac2_counts_calls_and_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.out"
            path.write_text("\n".join(transcript_lines()), encoding="utf-8")
            self.assertEqual(eval_metrics.transcript_stats(path), (2, 10))

    def test_ac2_missing_file_gives_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(eval_metrics.transcript_stats(Path(tmp) / "none.out"))

    def test_ac2_empty_transcript_gives_zero_not_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.out"
            path.write_text("", encoding="utf-8")
            self.assertEqual(eval_metrics.transcript_stats(path), (0, 0))

    def test_ac2_multibyte_counts_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.out"
            path.write_text(json.dumps({"message": {"content": [
                {"type": "tool_result", "content": "é"}]}}), encoding="utf-8")
            self.assertEqual(eval_metrics.transcript_stats(path), (0, 2))


class TableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runs = [
            make_run("s1", "without", 1, 0.2, turns=10, tool_calls=4, tool_bytes=1000,
                     input_tokens=50, cache_read_tokens=9000, output_tokens=300, seconds=5),
            make_run("s1", "with", 1, 0.1, turns=6, tool_calls=2, tool_bytes=400,
                     input_tokens=40, cache_read_tokens=8000, output_tokens=200, seconds=4),
        ]

    def test_ac3_scenario_table_header_and_cells(self) -> None:
        lines = evals.summary("role.x", "m", self.runs).splitlines()
        header = next(line for line in lines if line.startswith("| Scenario"))
        for title in ("Cost", "Turns", "Tool calls", "Tool bytes", "Tokens in", "Cache read",
                      "Tokens out"):
            self.assertIn(f"| {title} ", header)
        row = next(line for line in lines if line.startswith("| s1 | with |"))
        cells = [c.strip() for c in row.strip("|").split("|")]
        head = [c.strip() for c in header.strip("|").split("|")]
        got = dict(zip(head, cells))
        self.assertEqual(got["Cost"], "0.1000")
        self.assertEqual(got["Turns"], "6.0")
        self.assertEqual(got["Tool calls"], "2.0")
        self.assertEqual(got["Tool bytes"], "400")
        self.assertEqual(got["Tokens in"], "40")
        self.assertEqual(got["Cache read"], "8000")
        self.assertEqual(got["Tokens out"], "200")

    def test_ac3_cost_has_four_decimals(self) -> None:
        runs = [make_run("s1", "with", 1, 0.12346)]
        self.assertIn("| 0.1235 |", "\n".join(eval_metrics.scenario_table(runs, evals._rate)))

    def test_ac4_variant_table(self) -> None:
        runs = [make_run("s1", "with", 1, 0.1, turns=4, tool_bytes=100),
                make_run("s2", "with", 1, 0.3, turns=6, tool_bytes=300, checks=FAIL)]
        lines = eval_metrics.variant_table(runs, evals._rate)
        head = [c.strip() for c in lines[0].strip("|").split("|")]
        row = dict(zip(head, [c.strip() for c in lines[2].strip("|").split("|")]))
        self.assertEqual(row["Variant"], "with")
        self.assertEqual(row["Cost mean"], "0.2000")
        # sample sd of (0.1, 0.3) = 0.14142; SE = 0.1
        self.assertEqual(row["Cost SE"], "0.1000")
        self.assertEqual(row["Turns mean"], "5.0")
        self.assertEqual(row["Tool bytes mean"], "200")
        self.assertEqual(row["Pass rate"], "0.50")

    def test_ac4_single_run_standard_error_is_zero(self) -> None:
        self.assertEqual(eval_metrics.mean_and_error([0.5]), (0.5, 0.0))
        self.assertIsNone(eval_metrics.mean_and_error([]))


class DifferenceTests(unittest.TestCase):
    def test_ac5_more_than_two_se(self) -> None:
        runs = [make_run("s", "without", t, c) for t, c in enumerate([0.50, 0.51, 0.49], 1)]
        runs += [make_run("s", "with", t, c) for t, c in enumerate([0.10, 0.11, 0.09], 1)]
        text = evals.summary("c", "m", runs)
        line = next(x for x in text.splitlines() if x.startswith("Cost, with minus without"))
        self.assertIn("-0.4000 USD", line)
        self.assertIn("more than 2 standard errors", line)

    def test_ac5_within_two_se(self) -> None:
        runs = [make_run("s", "without", t, c) for t, c in enumerate([0.1, 0.5, 0.3], 1)]
        runs += [make_run("s", "with", t, c) for t, c in enumerate([0.12, 0.52, 0.32], 1)]
        text = evals.summary("c", "m", runs)
        line = next(x for x in text.splitlines() if x.startswith("Cost, with minus without"))
        self.assertIn("+0.0200 USD", line)
        self.assertIn("within 2 standard errors", line)

    def test_ac5_one_line_for_each_non_base_variant(self) -> None:
        runs = [make_run("s", v, 1, c) for v, c in
                (("without", 0.3), ("with", 0.2), ("other", 0.1))]
        lines = eval_metrics.cost_difference_lines(runs)
        self.assertEqual(len(lines), 2)

    def test_ac5_no_base_gives_no_line(self) -> None:
        runs = [make_run("s", "a", 1, 0.3), make_run("s", "b", 1, 0.2)]
        self.assertEqual(eval_metrics.cost_difference_lines(runs), [])


class OldFileTests(unittest.TestCase):
    OLD = {"scenario": "s", "variant": "with", "trial": 1, "checks": PASS,
           "usage": {"cost_usd": 0.35, "input_tokens": 10, "output_tokens": 5, "turns": 3},
           "error": ""}

    def test_ac6_missing_keys_show_dash(self) -> None:
        text = evals.summary("c", "m", [Run(**self.OLD)])
        row = next(x for x in text.splitlines() if x.startswith("| s | with |"))
        cells = [c.strip() for c in row.strip("|").split("|")]
        head = [c.strip() for c in next(x for x in text.splitlines()
                                        if x.startswith("| Scenario")).strip("|").split("|")]
        got = dict(zip(head, cells))
        for title in ("Tool calls", "Tool bytes", "Cache read"):
            self.assertEqual(got[title], "—")
        self.assertEqual(got["Cost"], "0.3500")
        self.assertEqual(got["Tokens in"], "10")

    def test_ac6_run_with_no_usage_makes_table(self) -> None:
        text = evals.summary("c", "m", [Run("s", "with", 1, checks=[], usage={})])
        self.assertIn("—", text)

    def test_ac6_load_runs_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.jsonl"
            path.write_text(json.dumps(self.OLD) + "\n", encoding="utf-8")
            runs = evals.load_runs(path, Path(tmp))
            self.assertEqual(len(runs), 1)
            self.assertNotIn("tool_calls", runs[0].usage)
            self.assertIn("—", evals.summary("c", "m", runs))

    def test_ac6_load_runs_fills_from_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "t.out").write_text("\n".join(transcript_lines()), encoding="utf-8")
            row = json.loads(json.dumps(self.OLD))
            row["usage"]["transcript"] = "t.out"
            path = Path(tmp) / "runs.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            runs = evals.load_runs(path, Path(tmp))
            self.assertEqual(runs[0].usage["tool_calls"], 2)
            self.assertEqual(runs[0].usage["tool_bytes"], 10)

    def test_ac6_load_runs_transcript_gone_stays_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            row = json.loads(json.dumps(self.OLD))
            row["usage"]["transcript"] = "gone.out"
            path = Path(tmp) / "runs.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            runs = evals.load_runs(path, Path(tmp))
            self.assertNotIn("tool_calls", runs[0].usage)


class SummaryOptionTests(unittest.TestCase):
    def _main(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_ac7_summary_prints_tables(self) -> None:
        runs = [make_run("s", "without", 1, 0.3, turns=5), make_run("s", "with", 1, 0.2, turns=4)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.jsonl"
            path.write_text("".join(json.dumps(r.__dict__) + "\n" for r in runs),
                            encoding="utf-8")
            code, out = self._main("eval", "--summary", str(path), "--root", tmp)
        self.assertEqual(code, 0)
        self.assertIn("| Scenario", out)
        self.assertIn("| Variant", out)
        self.assertIn("Cost, with minus without", out)

    def test_ac7_bad_file_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.jsonl"
            path.write_text("not json\n", encoding="utf-8")
            code, out = self._main("eval", "--summary", str(path), "--root", tmp)
            self.assertEqual(code, 2)
            self.assertIn("cannot read the runs file", out)
            code, _ = self._main("eval", "--summary", str(Path(tmp) / "missing.jsonl"),
                                 "--root", tmp)
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
