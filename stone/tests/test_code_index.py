"""Tests for the `code_index` key (issue #285, D111): the rule, the permission, and the build hook."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import yaml

from stone import code_index, render, upgrade

TESTS = Path(__file__).resolve().parent
FRAMEWORK = TESTS.parents[1] / "framework"
SHARED = TESTS / "golden" / "_shared"
TODAY = dt.date(2026, 10, 17)
CONFIG = """framework_version: 0.1.0
harness: claude-code
model_profile: claude-5
profiles: [single-ticket, full-project, code-audit]
branches: {integration: dev, main: main}
commands:
  install: pip install .
  test_unit: python -m unittest
  all_checks: make check
paths:
  tests: [tests/]
  checks: [.github/workflows/, .cornerstone/checks/]
  plans: docs/plans/
owners: {default: octocat}
"""
AGENTS = ".claude/agents/"
READERS = ["planner", "implementer", "tester", "reviewer", "investigator"]
SETTINGS = ".claude/settings.json"
CFG = ".cornerstone/config.yaml"
MANIFEST = ".cornerstone/manifest.yaml"
GUARD = "If `{}` is on PATH"
CUSTOM = {"command": "graphify",
          "rule": "- If `graphify` is on PATH, ask `graphify query` before you search code.\n"
                  "- Read only the lines that it gives.",
          "build": "graphify update --quiet"}


def config_text(value: object = "absent") -> str:
    data = yaml.safe_load(CONFIG)
    if value != "absent":
        data["code_index"] = value
    return yaml.safe_dump(data, sort_keys=False)


def render_to(root: Path, value: object = "absent") -> dict[str, str]:
    (root / ".cornerstone").mkdir(exist_ok=True)
    (root / ".cornerstone" / "config.yaml").write_text(config_text(value), encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()):
        render.render(root, FRAMEWORK, today=TODAY)
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(root.rglob("*")) if p.is_file()}


class RenderedBase(unittest.TestCase):
    def rendered(self, value: object = "absent") -> dict[str, str]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return render_to(Path(tmp.name), value)

    def settings(self, files: dict[str, str]) -> dict:
        return json.loads(files[SETTINGS])

    def session_command(self, files: dict[str, str]) -> str:
        return self.settings(files)["hooks"]["SessionStart"][0]["hooks"][0]["command"]


class DefaultRenderTest(RenderedBase):
    def test_ac1_absent_and_stone_index_render_the_same(self) -> None:
        absent, named = self.rendered(), self.rendered("stone-index")
        self.assertEqual(absent.pop(CFG) + "code_index: stone-index\n", named.pop(CFG))
        self.assertEqual(absent, named)

    def test_ac3_default_role_files_equal_the_shared_golden_files(self) -> None:
        files = self.rendered()
        for role in READERS + ["shaper"]:
            golden = (SHARED / AGENTS / f"{role}.md").read_text(encoding="utf-8")
            self.assertEqual(files[f"{AGENTS}{role}.md"], golden, role)

    def test_ac4_ac5_default_settings_equal_the_golden_file(self) -> None:
        self.assertEqual(self.rendered()[SETTINGS], (SHARED / SETTINGS).read_text(encoding="utf-8"))

    def test_ac3_readers_have_the_rule_and_the_shaper_does_not(self) -> None:
        files = self.rendered()
        for role in READERS:
            text = files[f"{AGENTS}{role}.md"]
            self.assertIn("## Code index", text, role)
            self.assertIn(code_index.DEFAULT["rule"], text, role)
            self.assertIn(GUARD.format("stone-index"), text, role)
        self.assertNotIn("Code index", files[f"{AGENTS}shaper.md"])
        self.assertNotIn("stone-index", files[f"{AGENTS}shaper.md"])

    def test_ac4_permission_allows_the_command(self) -> None:
        allow = self.settings(self.rendered())["permissions"]["allow"]
        self.assertIn("Bash(stone-index *)", allow)

    def test_ac5_session_start_runs_the_default_build(self) -> None:
        command = self.session_command(self.rendered())
        self.assertIn("stone-index build", command)
        self.assertIn("command -v stone-index", command)


class CustomRenderTest(RenderedBase):
    def test_ac1_custom_map_with_build(self) -> None:
        files = self.rendered(CUSTOM)
        for role in READERS:
            text = files[f"{AGENTS}{role}.md"]
            self.assertIn("## Code index", text)
            self.assertIn(CUSTOM["rule"], text)
            self.assertNotIn("stone-index", text)
        self.assertNotIn("Code index", files[f"{AGENTS}shaper.md"])
        self.assertIn("Bash(graphify *)", self.settings(files)["permissions"]["allow"])
        self.assertNotIn("Bash(stone-index *)", self.settings(files)["permissions"]["allow"])
        command = self.session_command(files)
        self.assertIn("graphify update --quiet", command)
        self.assertIn("command -v graphify", command)
        self.assertNotIn("stone-index", command)

    def test_ac1_custom_map_without_build_uses_command_build(self) -> None:
        value = {"command": "graphify", "rule": CUSTOM["rule"]}
        command = self.session_command(self.rendered(value))
        self.assertIn("graphify build", command)

    def test_ac1_build_with_options_stays_valid_json(self) -> None:
        value = {"command": "my-index", "rule": GUARD.format("my-index") + " x",
                 "build": "my-index update --out=.cache/idx"}
        files = self.rendered(value)
        self.assertIn("my-index update --out=.cache/idx", self.session_command(files))


class OptOutTest(RenderedBase):
    def test_ac6_none_differs_from_default_only_in_the_expected_files(self) -> None:
        default, none = self.rendered(), self.rendered("none")
        self.assertEqual(set(default), set(none))
        changed = {path for path in default if default[path] != none[path]}
        expected = {f"{AGENTS}{role}.md" for role in READERS} | {SETTINGS}
        # The config holds the key, and the manifest holds the hash of each generated file.
        self.assertEqual(changed - {CFG, MANIFEST}, expected)

    def test_ac6_none_has_no_rule_permission_or_hook(self) -> None:
        files = self.rendered("none")
        for role in READERS + ["shaper"]:
            text = files[f"{AGENTS}{role}.md"]
            self.assertNotIn("Code index", text)
            self.assertNotIn("stone-index", text)
        data = self.settings(files)
        self.assertNotIn("SessionStart", data["hooks"])
        self.assertNotIn("permissions", data)
        self.assertNotIn("stone-index", files[SETTINGS])

    def test_ac6_none_settings_equal_the_protect_paths_fragment(self) -> None:
        golden = json.loads((SHARED / SETTINGS).read_text(encoding="utf-8"))
        old = {"hooks": {"PreToolUse": golden["hooks"]["PreToolUse"]}}
        self.assertEqual(self.settings(self.rendered("none")), old)

    def test_ac6_none_role_files_equal_the_default_without_the_section(self) -> None:
        default, none = self.rendered(), self.rendered("none")
        for role in READERS:
            section = f"## Code index\n\n{code_index.DEFAULT['rule']}\n"
            path = f"{AGENTS}{role}.md"
            self.assertIn(section, default[path])
            self.assertEqual(default[path].replace(section + "\n", ""), none[path], role)


class BadFormTest(unittest.TestCase):
    def bad(self, value: object) -> None:
        found = code_index.problems({"code_index": value})
        self.assertTrue(found, f"no problem for {value!r}")

    def test_ac2_good_forms_have_no_problem(self) -> None:
        for value in ("stone-index", "none", CUSTOM, {"command": "x", "rule": GUARD.format("x")}):
            self.assertEqual(code_index.problems({"code_index": value}), [], value)
        self.assertEqual(code_index.problems({}), [])

    def test_ac2_bad_string_and_types(self) -> None:
        for value in ("graphify", "None", "", [], ["stone-index"], 3, True, None):
            self.bad(value)

    def test_ac2_map_missing_command_or_rule(self) -> None:
        self.bad({"rule": GUARD.format("x")})
        self.bad({"command": "x"})
        self.bad({})

    def test_ac2_unknown_key(self) -> None:
        self.bad(dict(CUSTOM, extra="y"))

    def test_ac2_command_with_space_or_shell_character(self) -> None:
        for command in ("my tool", "a;b", "a$b", "a|b", "a&b", "$(x)", "a`b`", "a>b", "", "-x", 5):
            self.bad({"command": command, "rule": f"- {GUARD.format(command)} x"})

    def test_ac2_rule_with_four_lines(self) -> None:
        rule = GUARD.format("x") + " a\nb\nc\nd"
        self.bad({"command": "x", "rule": rule})

    def test_ac2_rule_with_three_lines_is_valid(self) -> None:
        rule = GUARD.format("x") + " a\nb\nc"
        self.assertEqual(code_index.problems({"code_index": {"command": "x", "rule": rule}}), [])

    def test_ac2_empty_rule(self) -> None:
        for rule in ("", "  \n ", None, ["x"]):
            self.bad({"command": "x", "rule": rule})

    def test_ac2_rule_without_the_guard(self) -> None:
        self.bad({"command": "x", "rule": "- Use x before you search."})
        self.bad({"command": "x", "rule": "- If `y` is on PATH, use y."})

    def test_ac2_build_with_newline(self) -> None:
        self.bad(dict(CUSTOM, build="graphify a\nrm -rf x"))
        self.bad(dict(CUSTOM, build=["graphify"]))

    def test_ac2_build_with_shell_syntax_or_odd_spacing(self) -> None:
        for build in ('a "b"', "a #b", "a & b", "a && b", "a | b", "a; b", "a  b", "a\nb",
                      "a $b", "a `b`", "a 'b'", "a > b"):
            self.bad(dict(CUSTOM, build=build))

    def test_ac2_build_of_plain_words_passes(self) -> None:
        for build in ("graphify update", "my-index update --out=.cache/idx", "x"):
            self.assertEqual(code_index.problems({"code_index": dict(CUSTOM, build=build)}), [],
                             build)

    def test_ac2_render_fails_on_a_bad_value(self) -> None:
        for value in ("graphify", ["x"], {"command": "a b", "rule": "x"}):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(render.RenderError):
                    render_to(Path(tmp), value)

    def test_ac2_stone_check_reports_a_bad_value(self) -> None:
        from stone import framework_check
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".cornerstone").mkdir()
            (root / ".cornerstone" / "config.yaml").write_text(config_text("graphify"),
                                                              encoding="utf-8")
            findings = framework_check.check_config(root, FRAMEWORK)
        self.assertTrue(any("code_index" in f.message for f in findings), findings)


class HookRunTest(RenderedBase):
    def hook(self, value: object = "absent") -> str:
        return self.session_command(self.rendered(value))

    def run_hook(self, command: str, path: str, cwd: str) -> tuple[subprocess.CompletedProcess, float]:
        env = {"PATH": path, "CLAUDE_PROJECT_DIR": cwd}
        start = time.monotonic()
        done = subprocess.run(["sh", "-c", command], env=env, capture_output=True, text=True,
                              timeout=20)
        return done, time.monotonic() - start

    def test_ac5_hook_does_nothing_without_the_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            done, _ = self.run_hook(self.hook(), "/usr/bin:/bin", tmp)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout + done.stderr, "")

    def fake(self, folder: str, name: str, body: str) -> None:
        path = Path(folder) / name
        path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def test_ac5_hook_returns_fast_when_the_build_is_slow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as bin_dir:
            self.fake(bin_dir, "stone-index", "sleep 2")
            done, seconds = self.run_hook(self.hook(), f"{bin_dir}:/usr/bin:/bin", tmp)
        self.assertEqual(done.returncode, 0)
        self.assertLess(seconds, 1.0)

    def test_ac5_hook_exits_zero_when_the_build_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as bin_dir:
            self.fake(bin_dir, "stone-index", "echo boom; exit 3")
            done, _ = self.run_hook(self.hook(), f"{bin_dir}:/usr/bin:/bin", tmp)
            self.assertEqual(done.returncode, 0)
            self.assertEqual(done.stdout + done.stderr, "")

    def test_ac5_hook_runs_the_build_in_the_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as bin_dir:
            self.fake(bin_dir, "stone-index", f"echo ran > {tmp}/mark")
            self.run_hook(self.hook(), f"{bin_dir}:/usr/bin:/bin", tmp)
            for _ in range(30):
                if (Path(tmp) / "mark").exists():
                    break
                time.sleep(0.1)
            self.assertTrue((Path(tmp) / "mark").exists())

    def test_ac5_custom_hook_uses_the_custom_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as bin_dir:
            self.fake(bin_dir, "graphify", f"echo \"$@\" > {tmp}/mark")
            done, _ = self.run_hook(self.hook(CUSTOM), f"{bin_dir}:/usr/bin:/bin", tmp)
            self.assertEqual(done.returncode, 0)
            for _ in range(30):
                if (Path(tmp) / "mark").exists():
                    break
                time.sleep(0.1)
            self.assertEqual((Path(tmp) / "mark").read_text().strip(), "update --quiet")


class UpgradeEntryTest(unittest.TestCase):
    def entry(self) -> dict:
        found = [v for v in upgrade.load(FRAMEWORK) if str(v["version"]) == "1.6.0"]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_ac7_upgrades_has_a_minor_entry_for_1_6_0(self) -> None:
        entry = self.entry()
        self.assertEqual(entry["kind"], "minor")
        self.assertIn("code_index", [item["key"] for item in entry["config"]["added"]])

    def test_ac7_entry_lists_the_changed_generated_files(self) -> None:
        paths = {item["path"] for item in self.entry()["files"]}
        expected = {f"{AGENTS}{role}.md" for role in READERS} | {SETTINGS}
        self.assertTrue(expected <= paths, expected - paths)

    def test_ac7_upgrades_file_is_valid(self) -> None:
        self.assertEqual(upgrade.problems(FRAMEWORK), [])


if __name__ == "__main__":
    unittest.main()
