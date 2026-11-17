"""Tests for the economy and quality model picks (#305, D120).

The runs are built as `evals.Run` objects. No model starts. The CLI tests write a `runs.jsonl` file
and a model profile file in a temp folder.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import cli, eval_picks, evals, framework_check

REPO = Path(__file__).resolve().parents[2]
FRAMEWORK = REPO / "framework"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "eval_matrix"
COMPONENT = "role.tester"
BASELINE = "base-m"


def runs_of(model: str, scenario: str, passes: list[bool], cost: float | None,
            harness: str = "h", component: str = COMPONENT) -> list[evals.Run]:
    """One run for each item of `passes`. Each run costs `cost`. None means no cost key."""
    usage = {} if cost is None else {"cost_usd": cost}
    return [evals.Run(scenario, "with", index + 1,
                      checks=[{"check": "x", "kind": "outcome", "pass": ok}], usage=dict(usage),
                      component=component, harness=harness, model=model)
            for index, ok in enumerate(passes)]


def flags(passing: int, total: int) -> list[bool]:
    return [True] * passing + [False] * (total - passing)


def by_role(found: list[dict]) -> dict[str, dict]:
    return {entry["role"]: entry for entry in found}


def pick_models(entry: dict) -> tuple[str | None, str | None]:
    return (entry["economy"] and entry["economy"]["model"],
            entry["quality"] and entry["quality"]["model"])


def baseline_runs() -> list[evals.Run]:
    # pass rate 0.8, cost 0.10 a run, so 0.125 for each passing run
    return runs_of(BASELINE, "S1", flags(8, 10), 0.10)


class PickRulesTest(unittest.TestCase):
    def picks(self, runs: list[evals.Run], harness: str = "h") -> dict:
        return by_role(eval_picks.picks(runs, harness, {"tester": BASELINE}))["tester"]

    def test_baseline_matches_bare_model_and_harness_prefix(self) -> None:
        """1: the baseline is the role model, as a bare model or as <harness>:<model>."""
        for harness in ("h", ""):
            entry = self.picks(runs_of(BASELINE, "S1", flags(8, 10), 0.1, harness=harness))
            self.assertEqual(entry["baseline"], BASELINE)
            self.assertEqual(entry["economy"]["model"], f"{harness}:{BASELINE}" if harness else BASELINE)
            self.assertTrue(entry["economy"]["baseline"])
            self.assertEqual(entry["reason"], "")

    def test_baseline_of_another_harness_is_not_the_baseline(self) -> None:
        """1: <other>:<model> is not the baseline of the profile harness h."""
        entry = self.picks(runs_of(BASELINE, "S1", flags(8, 10), 0.1, harness="other"))
        self.assertIsNone(entry["economy"])
        self.assertIsNone(entry["quality"])
        self.assertTrue(entry["reason"])

    def test_role_without_baseline_in_profile_has_reason(self) -> None:
        """1: a role with no role model in the profile has no pick."""
        found = eval_picks.picks(baseline_runs(), "h", {"planner": "x"})
        self.assertIsNone(found[0]["economy"])
        self.assertIn("no role model", found[0]["reason"])

    def test_economy_and_quality_picks_differ(self) -> None:
        """2 and 3: the cheap model is the economy pick. The strong model is the quality pick."""
        runs = (baseline_runs()
                + runs_of("cheap", "S1", flags(7, 10), 0.02)      # 0.0286 per pass, near the baseline
                + runs_of("strong", "S1", flags(10, 10), 0.12)    # 0.12 per pass, rate 1.0
                + runs_of("bad", "S1", flags(2, 10), 0.001))      # cheapest, but far below the baseline
        entry = self.picks(runs)
        self.assertEqual(pick_models(entry), ("h:cheap", "h:strong"))
        self.assertAlmostEqual(entry["economy"]["cost_per_pass"], 0.2 / 7)
        self.assertAlmostEqual(entry["quality"]["pass_rate"], 1.0)
        self.assertFalse(entry["economy"]["baseline"])

    def test_economy_boundary_is_one_standard_error_of_the_difference(self) -> None:
        """2: a pass rate lower by less than hypot(se, se) counts. Lower by more does not."""
        base = eval_picks.Candidate("b", 0.8, 0.1, 1.0, 5, baseline=True)
        limit = 0.8 - (0.1 ** 2 + 0.1 ** 2) ** 0.5
        inside = eval_picks.Candidate("in", limit + 0.01, 0.1, 0.1, 5)
        outside = eval_picks.Candidate("out", limit - 0.01, 0.1, 0.01, 5)
        self.assertEqual(eval_picks.economy([base, inside, outside], base).model, "in")
        self.assertEqual(eval_picks.economy([base, outside], base).model, "b")

    def test_economy_boundary_with_runs(self) -> None:
        """2: the same boundary with real runs. Rate 0.8 vs 0.6, both se 0.1333 and 0.1633."""
        near = runs_of("near", "S1", flags(6, 10), 0.01)   # diff 0.2 < hypot(0.133, 0.163) = 0.21
        far = runs_of("far", "S1", flags(5, 10), 0.001)    # diff 0.3 > hypot(0.133, 0.167) = 0.21
        entry = self.picks(baseline_runs() + near + far)
        self.assertEqual(entry["economy"]["model"], "h:near")

    def test_quality_needs_cost_not_higher_than_baseline(self) -> None:
        """3: a model with a higher pass rate but a higher cost is not the quality pick."""
        entry = self.picks(baseline_runs() + runs_of("pricey", "S1", flags(10, 10), 0.2))
        self.assertEqual(entry["quality"]["model"], f"h:{BASELINE}")

    def test_quality_tie_on_pass_rate_lower_cost_wins(self) -> None:
        """3 and 5: with an equal pass rate, the lower cost wins."""
        entry = self.picks(baseline_runs()
                           + runs_of("a", "S1", flags(10, 10), 0.10)
                           + runs_of("b", "S1", flags(10, 10), 0.08))
        self.assertEqual(entry["quality"]["model"], "h:b")
        self.assertEqual(entry["economy"]["model"], "h:b")

    def test_quality_tie_with_the_baseline_lower_cost_wins(self) -> None:
        """5: a model with the pass rate of the baseline and a lower cost beats the baseline."""
        entry = self.picks(baseline_runs() + runs_of("same", "S1", flags(8, 10), 0.05))
        self.assertEqual(entry["quality"]["model"], "h:same")

    def test_equal_pass_rate_and_equal_cost_pick_is_stable(self) -> None:
        """5: with all equal, the order of the runs does not change the pick."""
        a = runs_of("a", "S1", flags(10, 10), 0.1)
        b = runs_of("b", "S1", flags(10, 10), 0.1)
        first = self.picks(baseline_runs() + a + b)
        second = self.picks(baseline_runs() + b + a)
        self.assertEqual(pick_models(first), pick_models(second))
        self.assertEqual(pick_models(first), ("h:a", "h:a"))

    def test_economy_tie_in_cost_higher_pass_rate_wins(self) -> None:
        """5: equal cost for each passing run, the higher pass rate wins the economy pick."""
        low = runs_of("low", "S1", flags(8, 10), 0.01)       # 0.0125
        high = runs_of("high", "S1", flags(10, 10), 0.0125)  # 0.0125
        entry = self.picks(baseline_runs() + low + high)
        self.assertEqual(entry["economy"]["model"], "h:high")

    def test_no_model_meets_a_rule_pick_is_the_baseline(self) -> None:
        """4: every other model costs more, so both picks are the baseline."""
        entry = self.picks(baseline_runs() + runs_of("dear", "S1", flags(8, 10), 0.5))
        self.assertEqual(pick_models(entry), (f"h:{BASELINE}", f"h:{BASELINE}"))
        self.assertTrue(entry["economy"]["baseline"] and entry["quality"]["baseline"])

    def test_model_with_no_cost_is_never_picked(self) -> None:
        """4: a model with no cost cannot win either rule."""
        entry = self.picks(baseline_runs() + runs_of("free", "S1", flags(10, 10), None))
        self.assertEqual(pick_models(entry), (f"h:{BASELINE}", f"h:{BASELINE}"))

    def test_baseline_without_cost_gives_baseline_quality(self) -> None:
        """4: if the baseline has no cost, no model can be not higher. Quality is the baseline."""
        entry = self.picks(runs_of(BASELINE, "S1", flags(8, 10), None)
                           + runs_of("o", "S1", flags(10, 10), 0.01))
        self.assertEqual(entry["quality"]["model"], f"h:{BASELINE}")

    def test_too_few_trials_model_is_not_picked(self) -> None:
        """6: a model with 2 runs is not picked, even if it would win both rules."""
        runs = baseline_runs() + runs_of("tiny", "S1", [True, True], 0.001)
        entry = self.picks(runs)
        self.assertEqual(pick_models(entry), (f"h:{BASELINE}", f"h:{BASELINE}"))
        self.assertEqual(entry["skipped"], ["h:tiny"])

    def test_three_trials_is_enough(self) -> None:
        """6: exactly 3 runs counts."""
        runs = baseline_runs() + runs_of("three", "S1", [True] * 3, 0.001)
        entry = self.picks(runs)
        self.assertEqual(pick_models(entry), ("h:three", "h:three"))
        self.assertEqual(entry["skipped"], [])

    def test_fewest_runs_of_any_scenario_counts(self) -> None:
        """6: 5 runs of S1 and 2 runs of S2 is 2 trials, so the model is skipped."""
        runs = (runs_of(BASELINE, "S1", flags(4, 5), 0.1) + runs_of(BASELINE, "S2", flags(4, 5), 0.1)
                + runs_of("m", "S1", [True] * 5, 0.001) + runs_of("m", "S2", [True] * 2, 0.001))
        entry = self.picks(runs)
        self.assertEqual(entry["skipped"], ["h:m"])
        self.assertEqual(pick_models(entry), (f"h:{BASELINE}", f"h:{BASELINE}"))

    def test_baseline_with_too_few_trials_has_no_pick_and_a_reason(self) -> None:
        """6: the baseline has 2 runs for a scenario: no pick, and a reason."""
        runs = (runs_of(BASELINE, "S1", [True] * 5, 0.1) + runs_of(BASELINE, "S2", [True] * 2, 0.1)
                + runs_of("other", "S1", [True] * 5, 0.01) + runs_of("other", "S2", [True] * 5, 0.01))
        entry = self.picks(runs)
        self.assertEqual(pick_models(entry), (None, None))
        self.assertIn("2", entry["reason"])
        self.assertIn("3", entry["reason"])

    def test_picks_are_for_each_role(self) -> None:
        """1: each role has its own baseline."""
        runs = (runs_of("a", "S1", flags(8, 10), 0.1, component="role.tester")
                + runs_of("b", "S1", flags(8, 10), 0.1, component="role.planner")
                + runs_of("a", "S1", flags(8, 10), 0.1, component="skill.x"))
        found = by_role(eval_picks.picks(runs, "h", {"tester": "a", "planner": "b"}))
        self.assertEqual(set(found), {"tester", "planner"})
        self.assertEqual(found["planner"]["economy"]["model"], "h:b")


class LoadBaselinesTest(unittest.TestCase):
    def test_reads_harness_and_role_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.yaml"
            path.write_text("harness: h\ndefaults:\n  role_models: {tester: base-m, planner: p}\n")
            self.assertEqual(eval_picks.load_baselines(path), ("h", {"tester": "base-m", "planner": "p"}))

    def test_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for body in (None, "harness: h\n", "- a\n", "defaults: {role_models: {}}\n", ": : :\n[\n"):
                path = Path(tmp) / "p.yaml"
                if body is None:
                    path = Path(tmp) / "missing.yaml"
                else:
                    path.write_text(body)
                with self.assertRaises(eval_picks.PicksError, msg=str(body)):
                    eval_picks.load_baselines(path)


class PicksCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        runs = (baseline_runs() + runs_of("cheap", "S1", flags(7, 10), 0.02)
                + runs_of("strong", "S1", flags(10, 10), 0.12))
        self.runs_file = self.root / "runs.jsonl"
        self.runs_file.write_text("".join(json.dumps(dataclasses.asdict(r)) + "\n" for r in runs))
        self.profile = self.root / "profile.yaml"
        self.profile.write_text("harness: h\ndefaults:\n  role_models: {tester: base-m}\n")

    def run_cli(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["eval", "--root", str(self.root), *argv])
        return code, out.getvalue()

    def matrix(self, *extra: str) -> tuple[int, str]:
        return self.run_cli("--summary", str(self.runs_file), "--by", "model", *extra)

    def test_pick_column_only_with_picks(self) -> None:
        """7: the Pick column and the picks table exist only with --picks."""
        code, plain = self.matrix()
        self.assertEqual(code, 0)
        self.assertNotIn("| Pick", plain)
        self.assertNotIn("Picks:", plain)
        code, with_picks = self.matrix("--picks", str(self.profile))
        self.assertEqual(code, 0)
        header = next(line for line in with_picks.splitlines() if line.startswith("| Component"))
        self.assertTrue(header.rstrip().endswith("| Pick |"))
        self.assertIn("Picks:", with_picks)

    def test_text_output_without_picks_is_the_golden_matrix_output(self) -> None:
        """7: the output without --picks is the old matrix output."""
        golden = FIXTURES / "expected.txt"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["eval", "--root", str(FIXTURES), "--summary", str(FIXTURES / "runs.jsonl"),
                      "--by", "model"])
        self.assertEqual(out.getvalue(), golden.read_text())

    def test_pick_cells_and_table_content(self) -> None:
        """7: rows get the pick words. The picks table names the picks."""
        _, out = self.matrix("--picks", str(self.profile))
        rows = {line.split("|")[2].strip(): line for line in out.splitlines()
                if line.startswith("| role.tester")}
        self.assertTrue(rows["h:cheap"].rstrip().endswith("| economy |"))
        self.assertTrue(rows["h:strong"].rstrip().endswith("| quality |"))
        self.assertTrue(rows["h:base-m"].rstrip().endswith("|"))
        self.assertNotIn("baseline |", rows["h:base-m"])
        table = out.split("Picks:")[1]
        self.assertIn("| tester | base-m | h:cheap (0.70, 0.0286) | h:strong (1.00, 0.1200) |", table)
        # the picks table comes after the matrix table
        self.assertGreater(out.index("Picks:"), out.index("Variants counted"))

    def test_baseline_pick_is_marked_baseline(self) -> None:
        """4 and 7: if the baseline is the pick, its row says economy, quality, baseline."""
        self.runs_file.write_text("".join(json.dumps(dataclasses.asdict(r)) + "\n"
                                          for r in baseline_runs()))
        _, out = self.matrix("--picks", str(self.profile))
        row = next(line for line in out.splitlines() if line.startswith("| role.tester"))
        self.assertTrue(row.rstrip().endswith("| economy, quality, baseline |"), row)

    def test_json_with_picks_has_picks_key(self) -> None:
        """7: --json with --picks has a picks key. Without --picks it has none."""
        code, out = self.matrix("--json")
        self.assertEqual(code, 0)
        self.assertNotIn("picks", json.loads(out))
        code, out = self.matrix("--json", "--picks", str(self.profile))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data["rows"]), 3)
        entry = data["picks"][0]
        self.assertEqual((entry["role"], entry["baseline"]), ("tester", BASELINE))
        self.assertEqual(pick_models(entry), ("h:cheap", "h:strong"))

    def test_picks_without_by_returns_2(self) -> None:
        """8: --picks needs --by model."""
        code, out = self.run_cli("--summary", str(self.runs_file), "--picks", str(self.profile))
        self.assertEqual(code, 2)
        self.assertIn("--by", out)

    def test_picks_without_summary_returns_2(self) -> None:
        """8: --picks needs --summary."""
        code, out = self.run_cli(COMPONENT, "--picks", str(self.profile))
        self.assertEqual(code, 2)
        self.assertIn("--summary", out)

    def test_missing_profile_returns_2_with_message(self) -> None:
        """8: a missing profile file."""
        code, out = self.matrix("--picks", str(self.root / "none.yaml"))
        self.assertEqual(code, 2)
        self.assertIn("stone eval:", out)
        self.assertIn("none.yaml", out)

    def test_bad_profile_returns_2_with_message(self) -> None:
        """8: a profile with no role models, and a profile that is not YAML."""
        for body in ("harness: h\n", "[\n"):
            self.profile.write_text(body)
            code, out = self.matrix("--picks", str(self.profile))
            self.assertEqual(code, 2, body)
            self.assertIn("stone eval:", out)


def valid_pick(model: str = "m") -> dict:
    return {"model": model, "pass_rate": 0.9, "cost_per_pass": 0.05, "trials": 3,
            "eval_version": "1.7.0", "date": dt.date(2026, 11, 1), "review": dt.date(2027, 2, 1)}


def valid_profile() -> dict:
    return {"id": "x", "defaults": {"role_models": {"tester": "base-m", "planner": "p"}},
            "recommendations": {"tester": {"economy": valid_pick("e"), "quality": valid_pick("q")}}}


class ProblemsTest(unittest.TestCase):
    def assertOneProblem(self, data: object, *words: str) -> None:
        found = eval_picks.problems(data)
        self.assertEqual(len(found), 1, found)
        for word in words:
            self.assertIn(word, found[0])

    def mutate(self, **changes: object) -> dict:
        data = copy.deepcopy(valid_profile())
        data["recommendations"]["tester"]["economy"].update(changes)
        return data

    def test_valid_block_has_no_problem(self) -> None:
        self.assertEqual(eval_picks.problems(valid_profile()), [])

    def test_no_block_has_no_problem(self) -> None:
        data = valid_profile()
        del data["recommendations"]
        self.assertEqual(eval_picks.problems(data), [])

    def test_null_cost_is_valid(self) -> None:
        self.assertEqual(eval_picks.problems(self.mutate(cost_per_pass=None)), [])

    def test_unknown_role(self) -> None:
        data = valid_profile()
        data["recommendations"]["ghost"] = data["recommendations"].pop("tester")
        self.assertOneProblem(data, "ghost", "role model")

    def test_missing_pick_key(self) -> None:
        data = valid_profile()
        del data["recommendations"]["tester"]["economy"]["review"]
        self.assertOneProblem(data, "economy", "review")

    def test_missing_kind(self) -> None:
        data = valid_profile()
        del data["recommendations"]["tester"]["quality"]
        self.assertOneProblem(data, "economy", "quality")

    def test_trials_below_three(self) -> None:
        self.assertOneProblem(self.mutate(trials=2), "trials")

    def test_trials_not_whole(self) -> None:
        self.assertOneProblem(self.mutate(trials=3.5), "trials")

    def test_pass_rate_outside_range(self) -> None:
        self.assertOneProblem(self.mutate(pass_rate=1.5), "pass_rate")
        self.assertOneProblem(self.mutate(pass_rate=-0.1), "pass_rate")

    def test_review_not_later_than_date(self) -> None:
        self.assertOneProblem(self.mutate(review=dt.date(2026, 11, 1)), "review", "later")
        self.assertOneProblem(self.mutate(review=dt.date(2026, 1, 1)), "review", "later")

    def test_date_is_not_a_date(self) -> None:
        self.assertOneProblem(self.mutate(date="2026-11-01"), "date")

    def test_negative_cost(self) -> None:
        self.assertOneProblem(self.mutate(cost_per_pass=-1), "cost_per_pass")

    def test_non_mapping_block(self) -> None:
        for block in ([], "text", 3):
            data = valid_profile()
            data["recommendations"] = block
            self.assertOneProblem(data, "recommendations")

    def test_non_mapping_pick(self) -> None:
        data = valid_profile()
        data["recommendations"]["tester"]["economy"] = "m"
        self.assertOneProblem(data, "economy", "mapping")


class CheckModelProfilesTest(unittest.TestCase):
    def folder(self, tmp: str, data: object) -> Path:
        framework = Path(tmp) / "framework"
        models = framework / "adapters" / "h" / "models"
        models.mkdir(parents=True)
        (models / "m.yaml").write_text(yaml.safe_dump(data) if not isinstance(data, str) else data)
        return framework

    def test_valid_profile_gives_no_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            framework = self.folder(tmp, valid_profile())
            self.assertEqual(framework_check.check_model_profiles(Path(tmp), framework), [])

    def test_bad_profile_gives_a_finding(self) -> None:
        data = valid_profile()
        data["recommendations"]["tester"]["economy"]["trials"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            framework = self.folder(tmp, data)
            found = framework_check.check_model_profiles(Path(tmp), framework)
        self.assertEqual(len(found), 1)
        self.assertIn("m.yaml", found[0].path)
        self.assertIn("trials", found[0].message)
        self.assertEqual(found[0].severity, "error")

    def test_unreadable_profile_gives_a_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            framework = self.folder(tmp, "a: [\n")
            found = framework_check.check_model_profiles(Path(tmp), framework)
        self.assertEqual(len(found), 1)

    def test_real_repo_has_no_model_profile_finding(self) -> None:
        found = [f for f in framework_check.run(REPO) if "/models/" in f.path.replace("\\", "/")]
        self.assertEqual(found, [])


class BaselineScenariosTest(unittest.TestCase):
    """The fixes of the review: a model counts only on the scenarios of the baseline."""

    def picks(self, runs: list[evals.Run], harness: str = "h") -> dict:
        return by_role(eval_picks.picks(runs, harness, {"tester": BASELINE}))["tester"]

    def two_scenario_baseline(self) -> list[evals.Run]:
        return (runs_of(BASELINE, "S1", flags(2, 3), 0.1) + runs_of(BASELINE, "S2", flags(2, 3), 0.1))

    def test_model_with_only_some_baseline_scenarios_is_skipped(self) -> None:
        """1: `cheap` ran S1 only, so it is not a pick. It is in skipped."""
        runs = self.two_scenario_baseline() + runs_of("cheap", "S1", [True] * 3, 0.001)
        entry = self.picks(runs)
        self.assertEqual(pick_models(entry), (f"h:{BASELINE}", f"h:{BASELINE}"))
        self.assertEqual(entry["skipped"], ["h:cheap"])

    def test_model_with_two_runs_of_one_scenario_is_skipped(self) -> None:
        """1: 3 runs of S1 and 2 runs of S2 is 2 trials."""
        runs = (self.two_scenario_baseline() + runs_of("m", "S1", [True] * 3, 0.001)
                + runs_of("m", "S2", [True] * 2, 0.001))
        entry = self.picks(runs)
        self.assertEqual(entry["skipped"], ["h:m"])
        self.assertEqual(pick_models(entry), (f"h:{BASELINE}", f"h:{BASELINE}"))

    def test_model_with_three_runs_of_each_scenario_is_picked(self) -> None:
        """1: 3 runs of S1 and of S2 counts."""
        runs = (self.two_scenario_baseline() + runs_of("m", "S1", [True] * 3, 0.001)
                + runs_of("m", "S2", [True] * 3, 0.001))
        entry = self.picks(runs)
        self.assertEqual(pick_models(entry), ("h:m", "h:m"))
        self.assertEqual(entry["skipped"], [])
        self.assertEqual(entry["economy"]["trials"], 3)

    def test_baseline_that_passes_no_run_gives_way_to_a_passing_model(self) -> None:
        """2: the baseline passes 0 of 3. A model `good` that passes 3 of 3 is both picks."""
        runs = runs_of(BASELINE, "S1", [False] * 3, 0.1) + runs_of("good", "S1", [True] * 3, 0.5)
        entry = self.picks(runs)
        self.assertEqual(pick_models(entry), ("h:good", "h:good"))
        self.assertFalse(entry["quality"]["baseline"])

    def test_baseline_with_passes_but_no_rate_stays_the_quality_pick(self) -> None:
        """2: the baseline passes some runs and has no cost. Quality is the baseline."""
        entry = self.picks(runs_of(BASELINE, "S1", flags(2, 3), None)
                           + runs_of("o", "S1", [True] * 3, 0.01))
        self.assertEqual(entry["quality"]["model"], f"h:{BASELINE}")

    def test_quality_with_zero_pass_baseline_picks_highest_rate(self) -> None:
        """2: with a baseline of no cost and no pass, the best pass rate wins, then the cost."""
        base = eval_picks.Candidate("b", 0.0, 0.0, None, 3, baseline=True)
        low = eval_picks.Candidate("low", 0.5, 0.1, 0.1, 3)
        high = eval_picks.Candidate("high", 1.0, 0.0, 9.0, 3)
        self.assertEqual(eval_picks.quality([base, low, high], base).model, "high")


class HarnessFilterTest(unittest.TestCase):
    def picks(self, runs: list[evals.Run]) -> dict:
        return by_role(eval_picks.picks(runs, "h", {"tester": BASELINE}))["tester"]

    def test_run_of_another_harness_is_never_a_pick(self) -> None:
        """3: `other:x` is cheap and perfect, but it is not a candidate."""
        entry = self.picks(baseline_runs() + runs_of("x", "S1", [True] * 3, 0.0001, harness="other"))
        self.assertEqual(pick_models(entry), (f"h:{BASELINE}", f"h:{BASELINE}"))
        self.assertEqual(entry["skipped"], [])

    def test_role_with_only_other_harness_runs_has_no_pick(self) -> None:
        """3: no run of the baseline model, so the reason says it."""
        entry = self.picks(runs_of("x", "S1", [True] * 3, 0.01, harness="other")
                           + runs_of(BASELINE, "S1", [True] * 3, 0.01, harness="other"))
        self.assertEqual(pick_models(entry), (None, None))
        self.assertIn("no run of the baseline model", entry["reason"])

    def test_bare_model_label_is_still_a_candidate(self) -> None:
        """3: an old run has no harness prefix. It can be a pick."""
        runs = (baseline_runs() + runs_of("old", "S1", [True] * 3, 0.001, harness=""))
        entry = self.picks(runs)
        self.assertEqual(pick_models(entry), ("old", "old"))

    def test_in_harness(self) -> None:
        self.assertTrue(eval_picks._in_harness("h:m", "h"))
        self.assertTrue(eval_picks._in_harness("m", "h"))
        self.assertFalse(eval_picks._in_harness("other:m", "h"))


class BadProfileDataTest(unittest.TestCase):
    def load(self, text: str) -> object:
        return yaml.safe_load(text)

    def test_timestamp_review_gives_a_finding(self) -> None:
        """4: YAML loads a timestamp as a datetime. That is not a date."""
        text = yaml.safe_dump(valid_profile()).replace("2027-02-01", "2027-05-01T00:00:00", 1)
        data = self.load(text)
        self.assertIsInstance(data["recommendations"]["tester"]["economy"]["review"], dt.datetime)
        found = eval_picks.problems(data)
        self.assertEqual(len(found), 1, found)
        self.assertIn("review", found[0])

    def test_defaults_not_a_mapping_gives_findings(self) -> None:
        """4: `defaults` as a list: the role is unknown."""
        data = self.load("defaults: [a, b]\nrecommendations:\n  tester: {}\n")
        found = eval_picks.problems(data)
        self.assertEqual(len(found), 1)
        self.assertIn("tester", found[0])
        self.assertIn("role model", found[0])

    def test_role_models_a_list_gives_findings(self) -> None:
        """4: `role_models: [x]` is not a mapping."""
        data = self.load("defaults: {role_models: [x]}\nrecommendations:\n  tester: {}\n")
        found = eval_picks.problems(data)
        self.assertEqual(len(found), 1)
        self.assertIn("role model", found[0])

    def test_check_model_profiles_gives_a_finding_not_a_traceback(self) -> None:
        for text in ("defaults: [a]\nrecommendations:\n  tester: {}\n",
                     "defaults: {role_models: [x]}\nrecommendations:\n  tester: {}\n"):
            with tempfile.TemporaryDirectory() as tmp:
                framework = Path(tmp) / "framework"
                models = framework / "adapters" / "h" / "models"
                models.mkdir(parents=True)
                (models / "m.yaml").write_text(text)
                found = framework_check.check_model_profiles(Path(tmp), framework)
            self.assertEqual(len(found), 1, text)
            self.assertIn("m.yaml", found[0].path)

    def test_check_model_profiles_timestamp_gives_a_finding(self) -> None:
        text = yaml.safe_dump(valid_profile()).replace("2027-02-01", "2027-05-01T00:00:00", 1)
        with tempfile.TemporaryDirectory() as tmp:
            framework = Path(tmp) / "framework"
            models = framework / "adapters" / "h" / "models"
            models.mkdir(parents=True)
            (models / "m.yaml").write_text(text)
            found = framework_check.check_model_profiles(Path(tmp), framework)
        self.assertEqual(len(found), 1)
        self.assertIn("review", found[0].message)

    def test_load_baselines_defaults_not_a_mapping_raises_picks_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.yaml"
            for text in ("defaults: [a]\n", "defaults: {role_models: [x]}\n"):
                path.write_text(text)
                with self.assertRaises(eval_picks.PicksError):
                    eval_picks.load_baselines(path)


class CountsTest(unittest.TestCase):
    def runs(self) -> list[evals.Run]:
        base = [dataclasses.replace(r, variant="without") for r in runs_of("m", "S1", [True] * 9, 0.1)]
        return (base + runs_of("m", "S1", [True] * 5, 0.1) + runs_of("m", "S2", [True] * 3, 0.1)
                + runs_of("n", "S1", [True] * 4, 0.1))

    def test_scenario_counts_leave_out_the_base_variant(self) -> None:
        """5: the 9 runs of `without` do not count."""
        counts = eval_picks.scenario_counts(self.runs())
        self.assertEqual(counts[(COMPONENT, "h:m")], {"S1": 5, "S2": 3})
        self.assertEqual(counts[(COMPONENT, "h:n")], {"S1": 4})

    def test_trial_counts_is_the_fewest_runs_of_one_scenario(self) -> None:
        """5: the old meaning stays."""
        self.assertEqual(eval_picks.trial_counts(self.runs()),
                         {(COMPONENT, "h:m"): 3, (COMPONENT, "h:n"): 4})

    def test_base_variant_only_has_no_counts(self) -> None:
        base = [dataclasses.replace(r, variant="without") for r in runs_of("m", "S1", [True] * 3, 0.1)]
        self.assertEqual(eval_picks.scenario_counts(base), {})
        self.assertEqual(eval_picks.trial_counts(base), {})


if __name__ == "__main__":
    unittest.main()
