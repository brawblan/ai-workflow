"""Tests for guidance evals with named variants (EVAL-GUIDANCE-1, D69).

A guidance eval has a `variants` mapping in its scenarios.yaml. These tests use the fake harness of
test_evals.py. No model starts.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any

import yaml

import test_evals as base
from stone import evals

FRAMEWORK = base.FRAMEWORK
GUIDANCE = "guidance.test"
GUIDANCE_DIR = "evals/guid-test"
CLAUDE = {"copy": "variants/a/CLAUDE.md", "to": "CLAUDE.md"}


class VariantCase(base.EvalTestCase):
    """A guidance eval in the temp repo: variants none, a, b."""

    def setUp(self) -> None:
        super().setUp()
        self.write(f"{GUIDANCE_DIR}/variants/a/CLAUDE.md", "text of a\n")
        self.write(f"{GUIDANCE_DIR}/variants/b/CLAUDE.md", "text of b\n")
        self.write(f"{GUIDANCE_DIR}/variants/b/extra.md", "extra of b\n")
        self.write(f"{GUIDANCE_DIR}/fixtures/basic/src/app.py", "VALUE = 1\n")
        self.write(f"{GUIDANCE_DIR}/fixtures/rendered/src/app.py", "VALUE = 1\n")
        self.write(f"{GUIDANCE_DIR}/fixtures/rendered/.cornerstone/config.yaml", base.CONFIG)
        self.write(f"{GUIDANCE_DIR}/fixtures/basic.diff", base.CHANGE_DIFF)
        self.write_guidance_run_config()

    def write_guidance_run_config(self, guidance: bool = True) -> None:
        """The run file gets a `run.guidance` command and an `env.guidance` entry."""
        config = self.run_config()
        if guidance:
            config["run"]["guidance"] = self.fake_cmd("guidance")
            config["env"]["guidance"] = {"FAKE_STATE": str(self.state), "FAKE_G": "g-$role",
                                         "FAKE_MODEL": "$model"}
        self.run_yaml.write_text(yaml.safe_dump(config), encoding="utf-8")

    def data(self, variants: Any = "default", **extra: Any) -> dict[str, Any]:
        if variants == "default":
            variants = {"none": [], "a": [dict(CLAUDE)],
                        "b": [dict(CLAUDE, copy="variants/b/CLAUDE.md"),
                              {"copy": "variants/b/extra.md", "to": "docs/deep/extra.md"}]}
        data: dict[str, Any] = {"component": GUIDANCE, "role": "writer", "task": "Write text.",
                                "scenarios": [self.scenario()]}
        if variants is not None:
            data["variants"] = variants
        data.update(extra)
        return data

    def write_guidance(self, data: dict[str, Any] | None = None) -> None:
        self.write(f"{GUIDANCE_DIR}/scenarios.yaml",
                   yaml.safe_dump(data or self.data(), sort_keys=False))

    def geval(self, *args: str, component: str = GUIDANCE) -> tuple[int, str]:
        argv = ["eval", component, "--root", str(self.root), "--framework", str(FRAMEWORK),
                "--run-config", str(self.run_yaml)]
        out = base.io.StringIO()
        with base.contextlib.redirect_stdout(out), base.contextlib.redirect_stderr(out):
            code = base.cli.main(argv + list(args))
        return code, out.getvalue()

    def loaded(self, data: dict[str, Any]) -> dict[str, Any]:
        self.write_guidance(data)
        return evals.load_scenarios(self.root / GUIDANCE_DIR)

    def assert_invalid(self, data: dict[str, Any], *words: str) -> None:
        with self.assertRaises(evals.EvalError) as caught:
            self.loaded(data)
        for word in words:
            self.assertIn(word, str(caught.exception))


class LoadVariantsTest(VariantCase):
    def test_ac1_valid_variants_load_and_an_empty_list_is_valid(self) -> None:
        data = self.loaded(self.data())
        self.assertEqual(list(data["variants"]), ["none", "a", "b"])
        self.assertEqual(data["variants"]["none"], [])

    def test_ac1_no_variants_key_is_valid(self) -> None:
        self.assertNotIn("variants", self.loaded(self.data(variants=None)))

    def test_ac1_variants_not_a_mapping_or_empty_raises(self) -> None:
        for bad in ({}, [], "none", ["none"], 3):
            with self.subTest(bad=bad):
                self.assert_invalid(self.data(variants=bad), "variants")

    def test_ac1_variant_value_not_a_list_names_the_variant(self) -> None:
        self.assert_invalid(self.data(variants={"none": [], "weird": "CLAUDE.md"}), "weird")
        self.assert_invalid(self.data(variants={"weird": {"copy": "x", "to": "y"}}), "weird")

    def test_ac1_item_without_copy_or_to_names_the_variant(self) -> None:
        self.assert_invalid(self.data(variants={"bad1": [{"to": "CLAUDE.md"}]}), "bad1")
        self.assert_invalid(self.data(variants={"bad2": [{"copy": CLAUDE["copy"]}]}), "bad2")
        self.assert_invalid(self.data(variants={"bad3": ["CLAUDE.md"]}), "bad3")

    def test_ac1_to_absolute_or_with_dotdot_names_the_variant(self) -> None:
        self.assert_invalid(self.data(variants={"abs": [dict(CLAUDE, to="/etc/CLAUDE.md")]}), "abs")
        self.assert_invalid(self.data(variants={"dots": [dict(CLAUDE, to="../CLAUDE.md")]}), "dots")
        self.assert_invalid(self.data(variants={"deep": [dict(CLAUDE, to="a/../../x")]}), "deep")

    def test_ac1_missing_copy_file_names_the_variant(self) -> None:
        self.assert_invalid(self.data(variants={"gone": [dict(CLAUDE, copy="variants/no.md")]}),
                            "gone")

    def test_ac1_check_only_with_bad_variants_exits_2_and_starts_no_run(self) -> None:
        self.write_guidance(self.data(variants={"gone": [dict(CLAUDE, copy="variants/no.md")]}))
        code, out = self.geval("--check-only")
        self.assertEqual(code, 2, out)
        self.assertEqual(self.calls(), [])


class FindComponentTest(VariantCase):
    def find(self, component: str = GUIDANCE, root: Path | None = ...) -> dict[str, Any]:  # type: ignore[assignment]
        return evals.find_component(FRAMEWORK, "claude-code", component,
                                    self.root if root is ... else root)

    def test_ac2_finds_a_guidance_eval_by_component(self) -> None:
        self.write_guidance()
        entry = self.find()
        self.assertEqual(entry["kind"], "guidance")
        self.assertEqual(entry["eval"], "evals/guid-test/")

    def test_ac2_eval_folder_without_variants_is_not_found(self) -> None:
        self.write_guidance(self.data(variants=None))
        with self.assertRaises(evals.EvalError):
            self.find()

    def test_ac2_eval_folder_with_empty_variants_is_not_found(self) -> None:
        self.write_guidance(self.data(variants={}))
        with self.assertRaises(evals.EvalError):
            self.find()

    def test_ac2_adapter_component_with_the_same_id_wins(self) -> None:
        self.write_guidance(self.data(component="role.tester"))
        entry = self.find("role.tester")
        self.assertEqual(entry["kind"], "role")
        self.assertEqual(entry["eval"], "evals/role-tester/")

    def test_ac2_unknown_id_raises(self) -> None:
        self.write_guidance()
        with self.assertRaises(evals.EvalError):
            self.find("guidance.nothing")

    def test_ac2_without_root_a_guidance_id_is_unknown(self) -> None:
        self.write_guidance()
        with self.assertRaises(evals.EvalError):
            self.find(root=None)
        self.assertEqual(self.find("role.tester", root=None)["kind"], "role")

    def test_acB_non_utf8_scenarios_file_is_skipped(self) -> None:
        path = self.root / "evals/binary/scenarios.yaml"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"component: x\n\xff\xfe\x00bad")
        self.write_guidance()
        self.assertEqual(self.find()["eval"], "evals/guid-test/")
        with self.assertRaises(evals.EvalError):
            self.find("guidance.nothing")

    def test_acB_unreadable_scenarios_file_is_skipped(self) -> None:
        path = self.root / "evals/locked/scenarios.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("component: x\n", encoding="utf-8")
        path.chmod(0)
        try:
            self.write_guidance()
            self.assertEqual(self.find()["kind"], "guidance")
        finally:
            path.chmod(0o644)

    def test_acB_two_folders_with_the_same_component_raise_and_name_both(self) -> None:
        self.write_guidance()
        self.write("evals/guid-other/scenarios.yaml",
                   yaml.safe_dump(self.data(), sort_keys=False))
        with self.assertRaises(evals.EvalError) as caught:
            self.find()
        self.assertIn("guid-test", str(caught.exception))
        self.assertIn("guid-other", str(caught.exception))

    def test_acB_second_folder_without_variants_is_no_duplicate(self) -> None:
        self.write_guidance()
        self.write("evals/guid-other/scenarios.yaml",
                   yaml.safe_dump(self.data(variants=None), sort_keys=False))
        self.assertEqual(self.find()["eval"], "evals/guid-test/")

    def test_ac2_broken_yaml_in_another_eval_folder_is_skipped(self) -> None:
        self.write("evals/broken/scenarios.yaml", "a: [unclosed\n")
        self.write_guidance()
        self.assertEqual(self.find()["kind"], "guidance")


class RunVariantsTest(VariantCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_guidance()

    def variants_run(self) -> list[str]:
        return [run["variant"] for run in self.runs()]

    def test_ac3_both_runs_every_variant_in_mapping_order(self) -> None:
        code, out = self.geval("--model", "m")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.variants_run(), ["none", "a", "b"])

    def test_ac3_one_name_runs_only_that_variant(self) -> None:
        code, out = self.geval("--model", "m", "--variant", "a")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.variants_run(), ["a"])

    def test_ac3_trials_repeat_each_variant(self) -> None:
        self.geval("--model", "m", "--trials", "2")
        self.assertEqual(self.variants_run(), ["none", "none", "a", "a", "b", "b"])

    def test_ac3_unknown_name_lists_known_names_and_starts_no_run(self) -> None:
        code, out = self.geval("--model", "m", "--variant", "zzz")
        self.assertNotEqual(code, 0)
        for name in ("none", "a", "b"):
            self.assertIn(name, out)
        self.assertEqual(self.calls(), [])

    def test_ac3_with_and_without_are_not_valid_names(self) -> None:
        for name in ("with", "without"):
            with self.subTest(name=name):
                code, out = self.geval("--model", "m", "--variant", name)
                self.assertNotEqual(code, 0, out)
                self.assertEqual(self.calls(), [])

    def test_ac3_empty_model_raises_before_any_run(self) -> None:
        # The role "writer" has no model in the model profile, and no --model is given.
        code, out = self.geval()
        self.assertNotEqual(code, 0)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.root / ".cornerstone/eval-runs").exists())

    def test_ac3_run_eval_raises_eval_error_for_empty_model(self) -> None:
        with self.assertRaises(evals.EvalError):
            evals.run_eval(self.root, GUIDANCE, framework=FRAMEWORK, run_config=self.run_yaml)

    def test_ac3_run_eval_raises_eval_error_for_unknown_variant(self) -> None:
        with self.assertRaises(evals.EvalError) as caught:
            evals.run_eval(self.root, GUIDANCE, framework=FRAMEWORK, run_config=self.run_yaml,
                           model="m", variant="zzz")
        for name in ("none", "a", "b"):
            self.assertIn(name, str(caught.exception))

    def test_ac3_role_eval_still_takes_with_without_both(self) -> None:
        self.scenarios()
        for variant, expected in (("with", ["with"]), ("without", ["without"]),
                                  ("both", ["with", "without"])):
            with self.subTest(variant=variant):
                self.reset_records()
                code, out = self.eval("--variant", variant)
                self.assertEqual(code, 0, out)
                self.assertEqual(self.variants_run(), expected)

    def test_ac3_role_eval_rejects_a_guidance_variant_name(self) -> None:
        self.scenarios()
        code, out = self.eval("--variant", "none")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.calls(), [])

    def test_ac5_every_variant_uses_the_guidance_command_and_env(self) -> None:
        self.geval("--model", "m")
        calls = self.calls()
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual(call["variant"], "guidance")
            self.assertEqual(call["env"], {"FAKE_G": "g-writer", "FAKE_MODEL": "m"})

    def test_ac5_guidance_env_absent_adds_no_extra_env(self) -> None:
        config = yaml.safe_load(self.run_yaml.read_text(encoding="utf-8"))
        del config["env"]["guidance"]
        self.run_yaml.write_text(yaml.safe_dump(config), encoding="utf-8")
        with base.unittest.mock.patch.dict(base.os.environ, {"FAKE_STATE": str(self.state)}):
            code, out = self.geval("--model", "m", "--variant", "a")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls()[0]["env"], {})

    def test_ac5_no_run_guidance_raises_before_any_run(self) -> None:
        self.write_guidance_run_config(guidance=False)
        with self.assertRaises(evals.EvalError) as caught:
            evals.run_eval(self.root, GUIDANCE, framework=FRAMEWORK, run_config=self.run_yaml,
                           model="m")
        self.assertIn("run.guidance", str(caught.exception))
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.root / ".cornerstone/eval-runs").exists())

    def test_ac5_run_guidance_that_is_not_a_list_is_rejected(self) -> None:
        config = yaml.safe_load(self.run_yaml.read_text(encoding="utf-8"))
        config["run"]["guidance"] = "claude -p"
        self.run_yaml.write_text(yaml.safe_dump(config), encoding="utf-8")
        with self.assertRaises(evals.EvalError) as caught:
            evals.load_run_config(self.run_yaml)
        self.assertIn("guidance", str(caught.exception))

    def test_ac5_run_guidance_is_optional_for_the_loader(self) -> None:
        self.write_guidance_run_config(guidance=False)
        self.assertNotIn("guidance", evals.load_run_config(self.run_yaml)["run"])
        self.write_guidance_run_config()
        self.assertIsInstance(evals.load_run_config(self.run_yaml)["run"]["guidance"], list)

    def test_ac5_role_and_hook_evals_do_not_use_run_guidance(self) -> None:
        self.scenarios()
        self.eval()
        self.assertEqual({c["variant"] for c in self.calls()}, {"with", "without"})

    def test_acC_role_eval_with_variants_raises_and_starts_no_run(self) -> None:
        self.scenarios(variants={"none": [], "a": [dict(CLAUDE)]})
        with self.assertRaises(evals.EvalError):
            evals.run_eval(self.root, base.COMPONENT, framework=FRAMEWORK, run_config=self.run_yaml,
                           model="m")
        self.assertEqual(self.calls(), [])
        code, out = self.eval()
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", out)
        self.assertEqual(self.calls(), [])


class PrepareVariantTest(VariantCase):
    def prepare(self, files: list[dict[str, Any]] | None, variant: str = "a",
                fixture: str = "fixtures/rendered", **extra: Any) -> Path:
        scenario = {"id": "G1", "fixture": fixture, **extra}
        ws = evals.prepare(self.root / GUIDANCE_DIR, scenario, FRAMEWORK, "", variant, files).path
        self.addCleanup(shutil.rmtree, ws.parent, True)
        return ws

    @staticmethod
    def subjects(ws: Path) -> list[str]:
        out = subprocess.run(["git", "log", "--reverse", "--format=%s"], cwd=ws,
                             capture_output=True, text=True, check=True).stdout
        return out.splitlines()

    def test_ac4_files_are_copied_with_parent_folders(self) -> None:
        data = self.data()
        ws = self.prepare(data["variants"]["b"], "b")
        self.assertEqual((ws / "CLAUDE.md").read_text(encoding="utf-8"), "text of b\n")
        self.assertEqual((ws / "docs/deep/extra.md").read_text(encoding="utf-8"), "extra of b\n")

    def test_ac4_guidance_commit_is_after_render_and_before_the_change(self) -> None:
        ws = self.prepare([dict(CLAUDE)], "a", change="fixtures/basic.diff")
        subjects = self.subjects(ws)
        guidance = "chore(eval): the guidance of the variant a"
        self.assertIn(guidance, subjects)
        self.assertEqual(subjects.count(guidance), 1)
        render = next(i for i, s in enumerate(subjects) if "render" in s)
        change = next(i for i, s in enumerate(subjects) if s.startswith("feat: the change"))
        self.assertLess(render, subjects.index(guidance))
        self.assertLess(subjects.index(guidance), change)

    def test_ac4_empty_list_adds_no_commit(self) -> None:
        with_none = self.prepare([], "none")
        no_files = self.prepare(None, "none")
        self.assertFalse(any("guidance" in s for s in self.subjects(with_none)))
        self.assertEqual(len(self.subjects(with_none)), len(self.subjects(no_files)))

    def test_ac4_workspace_is_clean_after_setup(self) -> None:
        ws = self.prepare([dict(CLAUDE)], "a")
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ws, capture_output=True,
                                text=True, check=True).stdout
        self.assertEqual(status, "")

    def test_ac4_guidance_files_are_not_a_change_of_the_run(self) -> None:
        self.write_guidance()
        expect = [{"check": "unchanged", "paths": ["CLAUDE.md", "docs/"]},
                  {"check": "only_changed", "paths": ["src/"]}]
        self.write_guidance(self.data(scenarios=[self.scenario(
            fixture="fixtures/rendered", expect=expect)]))
        self.plan({"with": [{"actions": [["write", "src/new.py", "x = 1\n"]]}]})
        code, out = self.geval("--model", "m", "--variant", "b")
        self.assertEqual(code, 0, out)
        run = self.runs()[0]
        self.assertEqual(self.check_passes(run), [True, True])

    def test_ac4_run_sees_the_variant_files_and_no_other(self) -> None:
        self.write_guidance(self.data(scenarios=[self.scenario(fixture="fixtures/basic")]))
        self.geval("--model", "m")
        files = {run["variant"]: set(call["files"])
                 for run, call in zip(self.runs(), self.calls())}
        self.assertNotIn("CLAUDE.md", files["none"])
        self.assertIn("CLAUDE.md", files["a"])
        self.assertNotIn("docs/deep/extra.md", files["a"])
        self.assertIn("docs/deep/extra.md", files["b"])


class SummaryAndExitTest(VariantCase):
    def runs_of(self, spec: dict[str, list[bool]]) -> list[evals.Run]:
        runs = []
        for variant, results in spec.items():
            for trial, ok in enumerate(results, 1):
                run = evals.Run("W1", variant, trial)
                run.checks = [{"check": "x", "kind": "outcome", "pass": ok, "detail": ""}]
                runs.append(run)
        return runs

    def test_ac6_guidance_summary_has_one_line_per_other_variant(self) -> None:
        text = evals.summary(GUIDANCE, "m", self.runs_of(
            {"none": [False, False], "always": [True, False], "short": [True, True]}))
        self.assertIn("Outcome pass rate, always minus none: +0.50.", text)
        self.assertIn("Outcome pass rate, short minus none: +1.00.", text)
        self.assertNotIn("with minus without", text)

    def test_ac6_rows_are_in_run_order(self) -> None:
        text = evals.summary(GUIDANCE, "m", self.runs_of(
            {"none": [True], "short": [True], "always": [True]}))
        rows = [line for line in text.splitlines() if line.startswith("| W1")]
        self.assertEqual([r.split("|")[2].strip() for r in rows], ["none", "short", "always"])

    def test_ac6_negative_gain_has_a_minus_sign(self) -> None:
        text = evals.summary(GUIDANCE, "m", self.runs_of({"none": [True], "short": [False]}))
        self.assertIn("Outcome pass rate, short minus none: -1.00.", text)

    def test_ac6_with_without_line_is_unchanged(self) -> None:
        text = evals.summary("role.tester", "m", self.runs_of(
            {"with": [True, True], "without": [True, False]}))
        self.assertIn("Outcome pass rate, with minus without: +0.50.", text)

    def test_ac6_no_none_variant_prints_no_gain_line(self) -> None:
        text = evals.summary(GUIDANCE, "m", self.runs_of({"a": [True], "b": [False]}))
        self.assertNotIn("Outcome pass rate", text)

    def test_ac6_cli_variant_has_no_argparse_choices(self) -> None:
        self.write_guidance()
        code, out = self.geval("--model", "m", "--variant", "b")
        self.assertEqual(code, 0, out)

    def fail_check(self) -> dict[str, Any]:
        return self.scenario(expect=[{"check": "file_exists", "path": "nope.txt"}])

    def test_ac6_exit_is_0_when_only_none_fails(self) -> None:
        self.write_guidance(self.data(scenarios=[self.fail_check()]))
        code, out = self.geval("--model", "m", "--variant", "none")
        self.assertEqual(code, 0, out)

    def test_ac6_exit_is_1_when_another_variant_fails(self) -> None:
        self.write_guidance(self.data(scenarios=[self.fail_check()]))
        code, out = self.geval("--model", "m", "--variant", "a")
        self.assertEqual(code, 1, out)

    def test_ac6_exit_is_1_for_both_when_a_non_none_variant_fails(self) -> None:
        self.write_guidance(self.data(scenarios=[self.fail_check()]))
        code, out = self.geval("--model", "m")
        self.assertEqual(code, 1, out)

    def test_ac6_result_file_has_the_gain_lines(self) -> None:
        self.write_guidance()
        self.geval("--model", "m")
        text, rows = self.table()
        self.assertIn("Outcome pass rate, a minus none:", text)
        self.assertIn("Outcome pass rate, b minus none:", text)
        self.assertEqual({key[1] for key in rows}, {"none", "a", "b"})


if __name__ == "__main__":
    unittest.main()
