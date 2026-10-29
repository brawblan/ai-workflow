"""Tests for `stone render` with profile override files (D85, issue #78 part 2).

Each test renders into a temporary repo with the real framework in this repo and a fixed date.
The rules come from D84, D85, and the "Profile override" section of customization.md.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from stone import overrides, render

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
TODAY = dt.date(2026, 10, 18)
WORKFLOW = ".github/workflows/cornerstone-checks.yml"
K7 = ".cornerstone/checks/change_size.py"
BASE_COMMANDS = {"install": "pip install .", "test_unit": "python -m unittest",
                 "all_checks": "make check"}
K8_STEP = "K8 architecture fitness"
K10_STEP = "K10 mutation score"


def config_text(profiles: list[str], commands: dict[str, Any] | None = None,
                limits: dict[str, Any] | None = None) -> str:
    data: dict[str, Any] = {
        "framework_version": "0.8.0", "harness": "claude-code", "model_profile": "claude-5",
        "profiles": profiles, "branches": {"integration": "dev", "main": "main"},
        "commands": {**BASE_COMMANDS, **(commands or {})},
        "paths": {"tests": ["tests/"], "checks": [".github/workflows/", ".cornerstone/checks/"],
                  "plans": "docs/plans/"},
        "owners": {"default": "octocat"},
    }
    if limits is not None:
        data["limits"] = limits
    return yaml.safe_dump(data, sort_keys=False)


def waiver(**kind: str) -> dict[str, Any]:
    return {**kind, "reason": "A test reason", "owner": "octocat", "until": "2026-12-31"}


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / "repo"
        (self.root / ".cornerstone").mkdir(parents=True)

    def configure(self, profiles: list[str], commands: dict[str, Any] | None = None,
                  limits: dict[str, Any] | None = None) -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(
            config_text(profiles, commands, limits), encoding="utf-8")

    def override(self, profile: str, **data: Any) -> Path:
        folder = self.root / ".cornerstone" / "profiles"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{profile}.yaml"
        path.write_text(yaml.safe_dump({"extends": profile, **data}, sort_keys=False),
                        encoding="utf-8")
        return path

    def render(self, today: dt.date = TODAY) -> render.Result:
        with contextlib.redirect_stderr(io.StringIO()):
            return render.render(self.root, FRAMEWORK, today=today)

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def files(self) -> dict[str, bytes]:
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in sorted(self.root.rglob("*"))
                if p.is_file() and p.relative_to(self.root).parts[:2] != (".cornerstone", "profiles")}

    def step_names(self) -> list[str]:
        steps = yaml.safe_load(self.read(WORKFLOW))["jobs"]["checks"]["steps"]
        return [step.get("name", "") for step in steps]

    def limits(self) -> dict[str, int]:
        return json.loads(re.search(r"^LIMITS = (.*)$", self.read(K7), re.M).group(1))


class NoOverrideTest(Base):
    def test_empty_profiles_folder_changes_nothing(self) -> None:
        self.configure(["single-ticket"])
        self.render()
        plain = self.files()
        (self.root / ".cornerstone" / "profiles").mkdir()
        self.render()
        self.assertEqual(self.files(), plain)

    def test_no_folder_is_the_same_as_before_for_two_renders(self) -> None:
        self.configure(["single-ticket", "app-slice"], {"architecture": "lint-imports"})
        self.render()
        first = self.files()
        self.render()
        self.assertEqual(self.files(), first)

    def test_override_that_changes_nothing_gives_the_same_files(self) -> None:
        self.configure(["single-ticket"])
        self.render()
        plain = self.files()
        self.override("single-ticket")
        self.render()
        self.assertEqual(self.files(), plain)


class ChecksAddTest(Base):
    def test_checks_add_k8_adds_the_step(self) -> None:
        self.configure(["single-ticket"], {"architecture": "lint-imports"})
        self.render()
        self.assertNotIn(K8_STEP, self.step_names())
        self.override("single-ticket", checks_add=["K8"])
        self.render()
        self.assertIn(K8_STEP, self.step_names())

    def test_checks_add_k8_step_uses_the_repo_command(self) -> None:
        self.configure(["single-ticket"], {"architecture": "lint-imports"})
        self.override("single-ticket", checks_add=["K8"])
        self.render()
        self.assertIn("lint-imports", self.read(WORKFLOW))

    def test_checks_add_without_the_command_adds_no_step(self) -> None:
        self.configure(["single-ticket"])
        self.override("single-ticket", checks_add=["K8"])
        self.render()
        self.assertNotIn(K8_STEP, self.step_names())

    def test_checks_add_does_not_change_other_profile(self) -> None:
        self.configure(["single-ticket", "bug-triage"], {"architecture": "lint-imports"})
        self.render()
        plain = self.limits()
        self.override("bug-triage", checks_add=["K8"])
        self.render()
        self.assertEqual(self.limits(), plain)

    def test_unknown_check_in_checks_add_raises(self) -> None:
        self.configure(["single-ticket"])
        self.override("single-ticket", checks_add=["K99"])
        with self.assertRaises(render.RenderError):
            self.render()


class CheckWaiverTest(Base):
    def setUp(self) -> None:
        super().setUp()
        self.configure(["app-slice"], {"architecture": "lint-imports"})

    def test_app_slice_has_the_k8_step_without_an_override(self) -> None:
        self.render()
        self.assertIn(K8_STEP, self.step_names())

    def test_active_check_waiver_removes_the_k8_step(self) -> None:
        self.override("app-slice", waivers=[waiver(check="K8")])
        self.render()
        self.assertNotIn(K8_STEP, self.step_names())

    def test_waiver_removes_only_the_named_check(self) -> None:
        self.render()
        before = self.step_names()
        self.override("app-slice", waivers=[waiver(check="K8")])
        self.render()
        self.assertEqual([n for n in before if n != K8_STEP], self.step_names())

    def test_waiver_is_active_on_the_until_date(self) -> None:
        self.override("app-slice", waivers=[waiver(check="K8")])
        self.render(today=dt.date(2026, 12, 31))
        self.assertNotIn(K8_STEP, self.step_names())

    def test_ended_waiver_raises_and_writes_nothing(self) -> None:
        self.override("app-slice", waivers=[waiver(check="K8")])
        with self.assertRaises(render.RenderError) as caught:
            self.render(today=dt.date(2027, 1, 1))
        self.assertIn("app-slice.yaml", str(caught.exception))
        self.assertEqual(self.files(), {".cornerstone/config.yaml":
                                        (self.root / ".cornerstone/config.yaml").read_bytes()})

    def test_ended_waiver_does_not_replace_a_good_render(self) -> None:
        self.render()
        before = self.files()
        self.override("app-slice", waivers=[waiver(check="K8")])
        with self.assertRaises(render.RenderError):
            self.render(today=dt.date(2027, 1, 1))
        self.assertEqual(self.files(), before)

    def test_waiver_for_a_fixed_check_raises(self) -> None:
        self.override("app-slice", waivers=[waiver(check="K7")])
        with self.assertRaises(render.RenderError):
            self.render()

    def test_waiver_for_a_check_the_profile_does_not_run_raises(self) -> None:
        self.configure(["single-ticket"])
        self.override("single-ticket", waivers=[waiver(check="K8")])
        with self.assertRaises(render.RenderError):
            self.render()


class LimitTest(Base):
    def test_smaller_limit_is_used_without_a_waiver(self) -> None:
        self.configure(["single-ticket"])
        self.override("single-ticket", limits={"pr_changed_lines": 200})
        self.render()
        self.assertEqual(self.limits(), {"single-ticket": 200})

    def test_no_override_uses_the_profile_limit(self) -> None:
        self.configure(["single-ticket"])
        self.render()
        self.assertEqual(self.limits(), {"single-ticket": 600})

    def test_override_below_a_smaller_repo_limit_wins(self) -> None:
        self.configure(["single-ticket"], limits={"pr_changed_lines": 300})
        self.override("single-ticket", limits={"pr_changed_lines": 100})
        self.render()
        self.assertEqual(self.limits(), {"single-ticket": 100})

    def test_override_equal_to_the_repo_limit_needs_no_waiver(self) -> None:
        self.configure(["single-ticket"], limits={"pr_changed_lines": 300})
        self.override("single-ticket", limits={"pr_changed_lines": 300})
        self.render()
        self.assertEqual(self.limits(), {"single-ticket": 300})

    def test_override_above_the_repo_limit_without_waiver_raises(self) -> None:
        # D84: the base is the smaller of the profile and the repo limit, so 400 > 300 needs a waiver.
        self.configure(["single-ticket"], limits={"pr_changed_lines": 300})
        path = self.override("single-ticket", limits={"pr_changed_lines": 400})
        with self.assertRaises(render.RenderError) as caught:
            self.render()
        self.assertIn(path.name, str(caught.exception))

    def test_override_above_the_repo_limit_with_waiver_wins(self) -> None:
        self.configure(["single-ticket"], limits={"pr_changed_lines": 300})
        self.override("single-ticket", limits={"pr_changed_lines": 400},
                      waivers=[waiver(limit="pr_changed_lines")])
        self.render()
        self.assertEqual(self.limits(), {"single-ticket": 400})

    def test_larger_limit_with_active_waiver(self) -> None:
        self.configure(["single-ticket"])
        self.override("single-ticket", limits={"pr_changed_lines": 900},
                      waivers=[waiver(limit="pr_changed_lines")])
        self.render()
        self.assertEqual(self.limits(), {"single-ticket": 900})

    def test_larger_limit_wins_over_the_repo_config_limit(self) -> None:
        self.configure(["single-ticket"], limits={"pr_changed_lines": 500})
        self.override("single-ticket", limits={"pr_changed_lines": 900},
                      waivers=[waiver(limit="pr_changed_lines")])
        self.render()
        self.assertEqual(self.limits(), {"single-ticket": 900})

    def test_larger_limit_without_waiver_raises_and_names_the_file(self) -> None:
        self.configure(["single-ticket"])
        path = self.override("single-ticket", limits={"pr_changed_lines": 900})
        with self.assertRaises(render.RenderError) as caught:
            self.render()
        self.assertIn(path.name, str(caught.exception))
        self.assertFalse((self.root / K7).exists())

    def test_larger_limit_after_the_waiver_ended_raises(self) -> None:
        self.configure(["single-ticket"])
        self.override("single-ticket", limits={"pr_changed_lines": 900},
                      waivers=[waiver(limit="pr_changed_lines")])
        with self.assertRaises(render.RenderError):
            self.render(today=dt.date(2027, 1, 1))

    def test_limit_applies_only_to_its_profile(self) -> None:
        self.configure(["single-ticket", "app-slice"])
        self.override("single-ticket", limits={"pr_changed_lines": 200})
        self.render()
        self.assertEqual(self.limits()["single-ticket"], 200)
        self.assertEqual(self.limits()["app-slice"], 600)


class MismatchTest(Base):
    def test_override_for_a_profile_not_in_config_raises(self) -> None:
        self.configure(["single-ticket"])
        self.override("app-slice", checks_add=["K8"])
        with self.assertRaises(render.RenderError):
            self.render()

    def test_override_for_an_unknown_profile_raises(self) -> None:
        self.configure(["single-ticket"])
        self.override("no-such-profile")
        with self.assertRaises(render.RenderError):
            self.render()

    def test_broken_yaml_raises(self) -> None:
        self.configure(["single-ticket"])
        folder = self.root / ".cornerstone" / "profiles"
        folder.mkdir()
        (folder / "single-ticket.yaml").write_text("extends: [unclosed\n", encoding="utf-8")
        with self.assertRaises(render.RenderError):
            self.render()


class RecordOnlyTest(Base):
    def test_gate_waiver_mode_and_drivers_change_no_file(self) -> None:
        self.configure(["single-ticket"])
        config = yaml.safe_load(self.read(".cornerstone/config.yaml"))
        config["modes_allowed"] = ["agent-centric", "hybrid"]
        (self.root / ".cornerstone" / "config.yaml").write_text(
            yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        plain_config = self.read(".cornerstone/config.yaml")
        self.render()
        plain = self.files()
        self.override("single-ticket", mode="hybrid", drivers={"build": "pair"},
                      waivers=[waiver(gate="G4")])
        self.render()
        self.assertEqual(self.files(), plain)
        self.assertEqual(self.read(".cornerstone/config.yaml"), plain_config)


class ApplyTest(unittest.TestCase):
    PROFILE = {"id": "p", "checks": ["K1", "K2", "K8"], "limits": {"pr_changed_lines": 600}}

    def make(self, **data: Any) -> overrides.Override:
        return overrides.Override(Path("p.yaml"), "p", {"extends": "p", **data})

    def test_order_is_kept_and_additions_come_last(self) -> None:
        result = overrides.apply(self.PROFILE, self.make(checks_add=["K10", "K4"]), TODAY)
        self.assertEqual(result["checks"], ["K1", "K2", "K8", "K10", "K4"])

    def test_duplicates_are_removed(self) -> None:
        result = overrides.apply(self.PROFILE, self.make(checks_add=["K2", "K4", "K4"]), TODAY)
        self.assertEqual(result["checks"], ["K1", "K2", "K8", "K4"])

    def test_active_waiver_removes_the_check(self) -> None:
        result = overrides.apply(self.PROFILE, self.make(waivers=[waiver(check="K2")]), TODAY)
        self.assertEqual(result["checks"], ["K1", "K8"])

    def test_waived_check_is_not_added_back_by_checks_add(self) -> None:
        result = overrides.apply(
            self.PROFILE, self.make(checks_add=["K2"], waivers=[waiver(check="K2")]), TODAY)
        self.assertNotIn("K2", result["checks"])

    def test_ended_waiver_does_not_remove_the_check(self) -> None:
        result = overrides.apply(self.PROFILE, self.make(waivers=[waiver(check="K2")]),
                                 dt.date(2027, 1, 1))
        self.assertEqual(result["checks"], ["K1", "K2", "K8"])

    def test_gate_waiver_removes_no_check(self) -> None:
        result = overrides.apply(self.PROFILE, self.make(waivers=[waiver(gate="G4")]), TODAY)
        self.assertEqual(result["checks"], ["K1", "K2", "K8"])

    def test_limit_is_set_as_limit_override(self) -> None:
        result = overrides.apply(self.PROFILE, self.make(limits={"pr_changed_lines": 250}), TODAY)
        self.assertEqual(result["limit_override"], 250)

    def test_no_limit_sets_no_limit_override(self) -> None:
        self.assertNotIn("limit_override", overrides.apply(self.PROFILE, self.make(), TODAY))

    def test_input_profile_is_not_changed(self) -> None:
        profile = {"id": "p", "checks": ["K1"]}
        overrides.apply(profile, self.make(checks_add=["K8"], limits={"pr_changed_lines": 5}), TODAY)
        self.assertEqual(profile, {"id": "p", "checks": ["K1"]})

    def test_empty_override_keeps_the_profile(self) -> None:
        result = overrides.apply(self.PROFILE, self.make(), TODAY)
        self.assertEqual(result["checks"], self.PROFILE["checks"])


if __name__ == "__main__":
    unittest.main()
