"""Tests for the eval token rates and the peak warning (issue #315). No real clock is used."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from stone import eval_metrics, eval_rates, evals, framework_check

UTC = dt.timezone.utc
REAL = Path(__file__).resolve().parents[2] / "framework" / "adapters" / "opencode" / "rates.yaml"
DEEP = "opencode-go/deepseek-v4.1-flash"
GLM = "opencode-go/glm-5.3-flash"
MON = dt.datetime(2026, 11, 9, tzinfo=UTC)  # a Monday
SAT = dt.datetime(2026, 11, 14, tzinfo=UTC)  # a Saturday


def at(day: dt.datetime, hour: int, minute: int = 0) -> dt.datetime:
    return day.replace(hour=hour, minute=minute)


def rates_data() -> dict:
    return yaml.safe_load(REAL.read_text(encoding="utf-8"))


USAGE = {"input_tokens": 1_000_000, "output_tokens": 500_000, "reasoning_tokens": 500_000,
         "cache_read_tokens": 2_000_000, "cache_write_tokens": 1_000_000}
# Off-peak: 1*0.15 + (0.5+0.5)*0.60 + 2*0.003 + 1*0 = 0.756. Peak: 0.30 + 1.20 + 0.012 = 1.512.


def run(variant: str = "with", **usage) -> evals.Run:
    return evals.Run("s1", variant, 1, [], dict(usage))


class RatesFile(unittest.TestCase):
    def test_real_file_is_valid_and_has_three_models(self) -> None:
        data = rates_data()
        self.assertEqual([], eval_rates.problems(data))
        self.assertEqual({GLM, DEEP, "opencode-go/kimi-k3.1-pro"}, set(data["models"]))
        self.assertEqual(dt.date(2026, 11, 9), data["read"])

    def test_the_adapter_names_the_rates_file(self) -> None:
        folder = REAL.parent.parent
        self.assertEqual("rates.yaml", evals.load_run_config(folder / "opencode" / "eval.yaml")["rates"])


class Period(unittest.TestCase):
    def period(self, moment: dt.datetime) -> str:
        return eval_rates.estimate({}, rates_data()["models"][DEEP], moment)[1]

    def test_peak_weekday_morning(self) -> None:
        self.assertEqual("peak", self.period(at(MON, 2, 30)))
        self.assertEqual("peak", self.period(at(MON, 7)))

    def test_window_edge(self) -> None:
        self.assertEqual("peak", self.period(at(MON, 3, 59)))
        self.assertEqual("off-peak", self.period(at(MON, 4, 0)))
        self.assertEqual("off-peak", self.period(at(MON, 0, 59)))
        self.assertEqual("peak", self.period(at(MON, 1, 0)))

    def test_weekend_is_off_peak(self) -> None:
        self.assertEqual("off-peak", self.period(at(SAT, 2)))
        self.assertEqual("off-peak", self.period(at(SAT, 7)))

    def test_off_peak_weekday(self) -> None:
        self.assertEqual("off-peak", self.period(at(MON, 15)))

    def test_model_without_peak_is_always_off_peak(self) -> None:
        entry = rates_data()["models"][GLM]
        self.assertEqual("off-peak", eval_rates.estimate({}, entry, at(MON, 2))[1])


class Cost(unittest.TestCase):
    def test_off_peak_cost_matches_the_hand_calculation(self) -> None:
        cost, period = eval_rates.estimate(USAGE, rates_data()["models"][DEEP], at(MON, 15))
        self.assertAlmostEqual(0.756, cost, places=9)
        self.assertEqual("off-peak", period)

    def test_peak_cost_matches_the_hand_calculation(self) -> None:
        cost, period = eval_rates.estimate(USAGE, rates_data()["models"][DEEP], at(MON, 2))
        self.assertAlmostEqual(1.512, cost, places=9)
        self.assertEqual("peak", period)

    def test_reasoning_tokens_use_the_output_rate(self) -> None:
        cost, _ = eval_rates.estimate({"reasoning_tokens": 1_000_000},
                                      rates_data()["models"][GLM], at(MON, 15))
        self.assertAlmostEqual(0.50, cost, places=9)

    def test_apply_sets_cost_source_and_period_when_cost_is_zero(self) -> None:
        usage = {**USAGE, "cost_usd": 0}
        eval_rates.apply(usage, rates_data(), DEEP, at(MON, 2))
        self.assertAlmostEqual(1.512, usage["cost_usd"], places=9)
        self.assertEqual("rates", usage["cost_source"])
        self.assertEqual("peak", usage["rate_period"])

    def test_apply_sets_cost_when_the_harness_gives_none(self) -> None:
        usage = dict(USAGE)
        eval_rates.apply(usage, rates_data(), DEEP, at(SAT, 2))
        self.assertAlmostEqual(0.756, usage["cost_usd"], places=9)
        self.assertEqual("off-peak", usage["rate_period"])

    def test_harness_cost_above_zero_stays(self) -> None:
        usage = {**USAGE, "cost_usd": 0.42}
        eval_rates.apply(usage, rates_data(), DEEP, at(MON, 2))
        self.assertEqual(0.42, usage["cost_usd"])
        self.assertEqual("harness", usage["cost_source"])
        self.assertNotIn("rate_period", usage)

    def test_unknown_model_with_cost_zero_loses_the_cost(self) -> None:
        usage = {**USAGE, "cost_usd": 0}
        eval_rates.apply(usage, rates_data(), "other/model", at(MON, 2))
        self.assertNotIn("cost_usd", usage)
        self.assertNotIn("cost_source", usage)


class MissingCostCells(unittest.TestCase):
    def test_tables_and_difference_show_a_dash(self) -> None:
        usage = {"cost_usd": 0, "turns": 3}
        eval_rates.apply(usage, rates_data(), "other/model", at(MON, 2))
        runs = [run("with", **usage), run("with", **usage), run("without", **usage),
                run("without", **usage)]
        text = evals.summary("role.x", "other/model", runs, "opencode")
        self.assertNotIn("0.0000", text)
        self.assertIn(eval_metrics.MISSING, text)
        self.assertIn("Cost, with minus without: —", text)
        variant_rows = [l for l in text.splitlines() if l.startswith("| with |")]
        self.assertTrue(variant_rows)
        self.assertEqual(["—", "—"], [c.strip() for c in variant_rows[-1].split("|")[3:5]])

    def test_estimated_cost_shows_a_number(self) -> None:
        usage = dict(USAGE)
        eval_rates.apply(usage, rates_data(), DEEP, at(MON, 15))
        text = evals.summary("role.x", DEEP, [run("with", **usage)], "opencode")
        self.assertIn("0.7560", text)


class Warning(unittest.TestCase):
    def targets(self, *models: str) -> list:
        return [SimpleNamespace(model=m, rates=rates_data()) for m in models]

    def test_warning_in_a_window_names_model_factor_and_end(self) -> None:
        lines = evals.peak_warnings(self.targets(DEEP), at(MON, 2, 30))
        self.assertEqual(1, len(lines))
        self.assertIn(DEEP, lines[0])
        self.assertIn("2 times", lines[0])
        self.assertIn("04:00 UTC", lines[0])

    def test_end_hour_of_the_second_window(self) -> None:
        lines = evals.peak_warnings(self.targets(DEEP), at(MON, 7))
        self.assertIn("10:00 UTC", lines[0])

    def test_no_warning_outside_a_window(self) -> None:
        self.assertEqual([], evals.peak_warnings(self.targets(DEEP), at(MON, 4)))
        self.assertEqual([], evals.peak_warnings(self.targets(DEEP), at(SAT, 2)))
        self.assertEqual([], evals.peak_warnings(self.targets(DEEP), at(MON, 15)))

    def test_no_warning_for_models_without_peak_or_rates(self) -> None:
        self.assertEqual([], evals.peak_warnings(self.targets(GLM, "other/model"), at(MON, 2)))
        self.assertEqual([], evals.peak_warnings([SimpleNamespace(model=DEEP, rates=None)],
                                                 at(MON, 2)))

    def test_one_warning_for_each_model(self) -> None:
        self.assertEqual(1, len(evals.peak_warnings(self.targets(DEEP, DEEP, GLM), at(MON, 2))))


class ResultNote(unittest.TestCase):
    def test_note_is_one_line_with_the_read_date(self) -> None:
        usage = dict(USAGE)
        eval_rates.apply(usage, rates_data(), DEEP, at(MON, 2))
        text = eval_rates.note(rates_data(), [run(**usage)], "framework/adapters/opencode/rates.yaml")
        self.assertNotIn("\n", text)
        self.assertIn("estimate", text)
        self.assertIn("2026-11-09", text)
        self.assertIn("rates.yaml", text)

    def test_no_note_when_the_harness_gave_the_cost(self) -> None:
        self.assertEqual("", eval_rates.note(rates_data(), [run(cost_usd=1.0, cost_source="harness")], "f"))

    def test_result_file_holds_the_note(self) -> None:
        usage = dict(USAGE)
        eval_rates.apply(usage, rates_data(), DEEP, at(MON, 15))
        target = SimpleNamespace(label=DEEP, model=DEEP, harness="opencode", rates=rates_data(),
                                 rates_file="framework/adapters/opencode/rates.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            path = evals._write_result(Path(tmp), "stamp", "role.x", target, [run(**usage)])
            text = Path(path).read_text(encoding="utf-8")
        self.assertIn("estimate", text)
        self.assertIn("2026-11-09", text)


class BadRatesFile(unittest.TestCase):
    def check(self, mutate) -> list[str]:
        data = rates_data()
        mutate(data)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = root / "framework" / "adapters" / "x"
            adapter.mkdir(parents=True)
            (adapter / "eval.yaml").write_text("rates: rates.yaml\n", encoding="utf-8")
            (adapter / "rates.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
            return [f.message for f in framework_check.check_eval_rates(root, root / "framework")]

    def test_good_file_has_no_finding(self) -> None:
        self.assertEqual([], self.check(lambda d: None))

    def test_bad_hour(self) -> None:
        found = self.check(lambda d: d["models"][DEEP]["peak"]["windows"][0].update(hours=[1, 24]))
        self.assertTrue(any("hours" in m for m in found), found)

    def test_bad_weekday(self) -> None:
        found = self.check(lambda d: d["models"][DEEP]["peak"]["windows"][0].update(weekdays=["funday"]))
        self.assertTrue(any("weekdays" in m for m in found), found)

    def test_negative_rate(self) -> None:
        found = self.check(lambda d: d["models"][GLM]["rates"].update(input=-0.1))
        self.assertTrue(any("input" in m for m in found), found)

    def test_bad_read_date(self) -> None:
        found = self.check(lambda d: d.update(read="yesterday"))
        self.assertTrue(any("read" in m for m in found), found)

    def test_load_raises_on_a_bad_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "rates.yaml"
            file.write_text("source: http://x\nread: 2026-11-09\nmodels: {}\n", encoding="utf-8")
            with self.assertRaises(eval_rates.RatesError):
                eval_rates.load(file)

    def test_real_file_passes_stone_check(self) -> None:
        root = Path(__file__).resolve().parents[2]
        self.assertEqual([], framework_check.check_eval_rates(root, root / "framework"))


class RatesKeyType(unittest.TestCase):
    def test_non_string_rates_key_is_rejected(self) -> None:
        for value in ("[a]", "{a: b}", "42", "''"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "eval.yaml"
                path.write_text(f"run:\n  with: [x]\n  without: [x]\nrates: {value}\n",
                                encoding="utf-8")
                with self.assertRaises(evals.EvalError) as caught:
                    evals.load_run_config(path)
                self.assertIn("rates", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
