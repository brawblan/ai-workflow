"""D84, issue #78 part 1: `stone check` validates the profile override files."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path

from stone import cli, framework_check
from test_render import CONFIG, FRAMEWORK

TODAY = dt.date(2026, 10, 28)
BASE = CONFIG + "modes_allowed: [agent-centric, hybrid]\n"
HEAD = "extends: single-ticket\n"


def waiver(kind: str = "gate: G4", until: str = "2027-01-31", extra: str = "") -> str:
    return (f"waivers:\n  - {kind}\n    reason: why\n    owner: octocat\n"
            f"    until: {until}\n{extra}")


class OverrideTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def repo(self, config: str = BASE, **files: str) -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(config, encoding="utf-8")
        if files:
            (self.root / ".cornerstone" / "profiles").mkdir(exist_ok=True)
        for name, text in files.items():
            (self.root / ".cornerstone" / "profiles" / f"{name.replace('_', '-')}.yaml"
             ).write_text(text, encoding="utf-8")

    def found(self, text: str, config: str = BASE, name: str = "single_ticket") -> list[str]:
        self.repo(config, **{name: text})
        return [f.message for f in framework_check.check_overrides(self.root, FRAMEWORK, TODAY)]

    def has(self, text: str, part: str, config: str = BASE, name: str = "single_ticket") -> None:
        messages = self.found(text, config, name)
        self.assertTrue(any(part in m for m in messages), messages)

    def ok(self, text: str, config: str = BASE) -> None:
        self.assertEqual(self.found(text, config), [])

    # Files and structure

    def test_no_profiles_folder_gives_no_finding(self) -> None:
        self.repo()
        self.assertEqual(framework_check.check_overrides(self.root, FRAMEWORK, TODAY), [])

    def test_full_valid_file_passes(self) -> None:
        self.ok(HEAD + "mode: hybrid\ndrivers:\n  shape: pair\n  verify: checks\n"
                "checks_add: [K8]\nlimits:\n  pr_changed_lines: 250\n"
                + waiver("gate: G4", extra="    scope: patch-versions\n"))

    def test_documented_example_passes(self) -> None:
        # customization.md shows `plan: pair` for single-ticket, which has no plan stage.
        self.ok(HEAD + "mode: hybrid\ndrivers:\n  plan: pair\nchecks_add: [K8]\n"
                "limits:\n  pr_changed_lines: 250\n"
                + waiver("gate: G4", extra="    scope: patch-versions\n"))

    def test_dependency_upgrade_g4_waiver_with_scope_passes(self) -> None:
        config = BASE.replace("[single-ticket]", "[dependency-upgrade]")
        text = ("extends: dependency-upgrade\n"
                + waiver("gate: G4", extra="    scope: patch-versions\n"))
        self.assertEqual(self.found(text, config, "dependency_upgrade"), [])

    def test_yaml_error_gives_one_finding(self) -> None:
        self.assertEqual(len(self.found("extends: [unclosed\n")), 1)

    def test_list_file_gives_one_finding(self) -> None:
        self.assertEqual(len(self.found("- a\n- b\n")), 1)

    def test_extends_missing_or_different(self) -> None:
        self.has("mode: hybrid\n", "'extends' must be 'single-ticket'")
        self.has("extends: bug-triage\n", "'extends' must be 'single-ticket'")

    def test_unknown_key(self) -> None:
        self.has(HEAD + "colour: red\n", "'colour' is not a key")

    def test_profile_not_in_config(self) -> None:
        self.has("extends: bug-triage\n", "not in 'profiles'", name="bug_triage")

    def test_profile_does_not_exist(self) -> None:
        config = BASE.replace("[single-ticket]", "[single-ticket, nope]")
        self.has("extends: nope\n", "does not exist", config, "nope")

    # Mode, drivers, checks_add

    def test_mode_not_allowed(self) -> None:
        self.has(HEAD + "mode: human-centric\n", "not in 'modes_allowed'")

    def test_drivers_not_a_map(self) -> None:
        self.has(HEAD + "drivers: [plan]\n", "'drivers' must be a map")

    def test_driver_stage_not_in_profile(self) -> None:
        self.has(HEAD + "drivers:\n  nostage: agent\n", "not a stage of the profile")

    def test_bad_driver_value(self) -> None:
        self.has(HEAD + "drivers:\n  plan: robot\n", "is not valid")

    def test_checks_driver_outside_verify(self) -> None:
        self.has(HEAD + "drivers:\n  build: checks\n", "is not valid")

    def test_verify_with_agent(self) -> None:
        self.has(HEAD + "drivers:\n  verify: agent\n", "is not valid")

    def test_checks_add_not_a_list(self) -> None:
        self.has(HEAD + "checks_add: K8\n", "'checks_add' must be a list")

    def test_checks_add_unknown_id(self) -> None:
        self.has(HEAD + "checks_add: [K999]\n", "'K999' in 'checks_add'")

    # Limits

    def test_limits_not_a_map(self) -> None:
        self.has(HEAD + "limits: 5\n", "'limits' must be a map")

    def test_unknown_limit_key(self) -> None:
        self.has(HEAD + "limits:\n  files: 3\n", "'limits.files' is not a key")

    def test_bad_pr_changed_lines_values(self) -> None:
        for value in ("abc", "0", "-5", "true", "1.5"):
            with self.subTest(value=value):
                self.has(HEAD + f"limits:\n  pr_changed_lines: {value}\n", "whole number above 0")

    def test_smaller_limit_passes(self) -> None:
        self.ok(HEAD + "limits:\n  pr_changed_lines: 100\n")

    def test_larger_limit_fails_without_waiver(self) -> None:
        self.has(HEAD + "limits:\n  pr_changed_lines: 700\n", "more than the limit 600")

    def test_larger_limit_passes_with_active_waiver(self) -> None:
        self.ok(HEAD + "limits:\n  pr_changed_lines: 700\n" + waiver("limit: pr_changed_lines"))

    def test_larger_limit_fails_when_waiver_ended(self) -> None:
        text = (HEAD + "limits:\n  pr_changed_lines: 700\n"
                + waiver("limit: pr_changed_lines", "2026-10-27"))
        messages = self.found(text)
        self.assertTrue(any("more than the limit" in m for m in messages), messages)
        self.assertTrue(any("ended on 2026-10-27" in m for m in messages), messages)

    def test_base_limit_is_smaller_of_profile_and_repo(self) -> None:
        config = BASE + "limits:\n  pr_changed_lines: 400\n"
        self.has(HEAD + "limits:\n  pr_changed_lines: 500\n", "more than the limit 400", config)
        self.ok(HEAD + "limits:\n  pr_changed_lines: 400\n", config)
        # A repo limit above the profile limit does not raise the base.
        config = BASE + "limits:\n  pr_changed_lines: 900\n"
        self.has(HEAD + "limits:\n  pr_changed_lines: 700\n", "more than the limit 600", config)

    # Waivers

    def test_waivers_not_a_list(self) -> None:
        self.has(HEAD + "waivers: x\n", "'waivers' must be a list")

    def test_waiver_item_not_a_map(self) -> None:
        self.has(HEAD + "waivers: [x]\n", "must be a map")

    def test_waiver_needs_exactly_one_kind(self) -> None:
        body = "    reason: r\n    owner: o\n    until: 2027-01-01\n"
        self.has(HEAD + "waivers:\n  - reason: r\n    owner: o\n    until: 2027-01-01\n",
                 "exactly one of gate, check, or limit")
        self.has(HEAD + "waivers:\n  - gate: G4\n    check: K1\n" + body,
                 "exactly one of gate, check, or limit")

    def test_waiver_unknown_key(self) -> None:
        self.has(HEAD + waiver(extra="    colour: red\n"), "unknown key 'colour'")

    def test_waiver_missing_or_blank_reason_and_owner(self) -> None:
        for key in ("reason", "owner"):
            other = "owner: o" if key == "reason" else "reason: r"
            with self.subTest(key=key, form="missing"):
                self.has(HEAD + f"waivers:\n  - gate: G4\n    {other}\n    until: 2027-01-01\n",
                         f"has no {key}")
            with self.subTest(key=key, form="blank"):
                self.has(HEAD + f"waivers:\n  - gate: G4\n    {other}\n    {key}: '  '\n"
                         "    until: 2027-01-01\n", f"has no {key}")

    def test_waiver_bad_until(self) -> None:
        self.has(HEAD + waiver(until="soon"), "no valid 'until' date")
        self.has(HEAD + "waivers:\n  - gate: G4\n    reason: r\n    owner: o\n",
                 "no valid 'until' date")

    def test_waiver_until_before_today_fails(self) -> None:
        self.has(HEAD + waiver(until="2026-10-27"), "ended on 2026-10-27")

    def test_waiver_until_today_passes(self) -> None:
        self.ok(HEAD + waiver(until="2026-10-28"))

    def test_gate_waivers(self) -> None:
        for gate in ("G3", "G5"):
            with self.subTest(gate=gate):
                self.has(HEAD + waiver(f"gate: {gate}"), f"removes {gate}")
        for gate in ("G1", "G2", "G4"):
            with self.subTest(gate=gate):
                self.ok(HEAD + waiver(f"gate: {gate}"))

    def test_fixed_check_waivers_fail(self) -> None:
        for check in ("K6", "K7", "K14", "K16", "K17"):
            with self.subTest(check=check):
                self.has(HEAD + waiver(f"check: {check}"), f"removes {check}")

    def test_check_waiver_for_check_the_profile_does_not_run(self) -> None:
        self.has(HEAD + waiver("check: K8"), "does not run it")

    def test_check_waiver_for_check_the_profile_runs_passes(self) -> None:
        self.ok(HEAD + waiver("check: K9"))

    def test_limit_waiver_unknown_name(self) -> None:
        self.has(HEAD + waiver("limit: files"), "loosens 'files'")

    # CLI

    def test_stone_check_cli_shows_file_path(self) -> None:
        self.repo(BASE, single_ticket=HEAD + waiver("gate: G3"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["check", "--root", str(self.root), "--framework", str(FRAMEWORK)])
        text = out.getvalue()
        self.assertIn(".cornerstone/profiles/single-ticket.yaml:1:", text)
        self.assertIn("removes G3", text)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
