"""Tests for the context guard hook (issue #299, D115): the rendered hook, the key, and the settings."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import framework_check, render

TESTS = Path(__file__).resolve().parent
FRAMEWORK = TESTS.parents[1] / "framework"
TODAY = dt.date(2026, 11, 9)
CONFIG = """framework_version: 0.1.0
harness: claude-code
model_profile: claude-5
profiles: [single-ticket]
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
HOOK = ".cornerstone/hooks/context-guard.py"
SETTINGS = ".claude/settings.json"
MANIFEST = ".cornerstone/manifest.yaml"
LIMIT = 150000


def config_text(value: object = "absent") -> str:
    data = yaml.safe_load(CONFIG)
    if value != "absent":
        data["limits"] = {"session_context_tokens": value}
    return yaml.safe_dump(data, sort_keys=False)


def usage_line(tokens: int, sidechain: bool = False) -> str:
    """One assistant line. The context is the sum of the three input counters."""
    return json.dumps({"type": "assistant", "isSidechain": sidechain,
                       "message": {"usage": {"input_tokens": 10, "output_tokens": 999,
                                             "cache_read_input_tokens": tokens - 30,
                                             "cache_creation_input_tokens": 20}}})


class GuardBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "repo"
        self.scratch = self.tmp / "scratch"
        self.scratch.mkdir()
        self.session = 0

    def go(self, value: object = "absent") -> render.Result:
        (self.root / ".cornerstone").mkdir(parents=True, exist_ok=True)
        (self.root / ".cornerstone" / "config.yaml").write_text(config_text(value), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            return render.render(self.root, FRAMEWORK, today=TODAY)

    def settings(self) -> dict:
        return json.loads((self.root / SETTINGS).read_text(encoding="utf-8"))

    def components(self) -> list[str]:
        manifest = yaml.safe_load((self.root / MANIFEST).read_text(encoding="utf-8"))
        return [c["id"] for c in manifest["components"]]


class HookRunTest(GuardBase):
    def setUp(self) -> None:
        super().setUp()
        self.go()

    def transcript(self, *lines: str) -> str:
        path = self.tmp / "transcript.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def run_hook(self, stdin: str, session: str = "s1") -> tuple[int, str]:
        env = dict(os.environ, TMPDIR=str(self.scratch), TEMP=str(self.scratch), TMP=str(self.scratch))
        done = subprocess.run([sys.executable, str(self.root / HOOK)], input=stdin, text=True,
                              capture_output=True, env=env, timeout=30)
        return done.returncode, done.stdout

    def prompt(self, path: object, session: str = "s1") -> tuple[int, str]:
        return self.run_hook(json.dumps({"hook_event_name": "UserPromptSubmit",
                                         "session_id": session, "transcript_path": path}), session)

    def bash(self, command: str) -> tuple[int, str]:
        return self.run_hook(json.dumps({"hook_event_name": "PostToolUse", "session_id": "s1",
                                         "tool_name": "Bash", "tool_input": {"command": command}}))

    def context(self, out: str) -> str:
        data = json.loads(out)
        self.assertEqual(len(out.strip().splitlines()), 1)
        return data["hookSpecificOutput"]

    def test_under_the_limit_gives_no_output(self) -> None:
        code, out = self.prompt(self.transcript(usage_line(LIMIT - 1000)))
        self.assertEqual((code, out), (0, ""))

    def test_exactly_at_the_limit_gives_no_output(self) -> None:
        self.assertEqual(self.prompt(self.transcript(usage_line(LIMIT))), (0, ""))

    def test_over_the_limit_gives_one_message_with_the_size(self) -> None:
        code, out = self.prompt(self.transcript(usage_line(100), usage_line(160000)))
        self.assertEqual(code, 0)
        hook = self.context(out)
        self.assertEqual(hook["hookEventName"], "UserPromptSubmit")
        self.assertIn("160000", hook["additionalContext"])
        self.assertIn("compact", hook["additionalContext"])

    def test_same_band_again_gives_no_output_and_next_band_gives_a_message(self) -> None:
        self.assertNotEqual(self.prompt(self.transcript(usage_line(160000)))[1], "")
        self.assertEqual(self.prompt(self.transcript(usage_line(170000))), (0, ""))
        self.assertEqual(self.prompt(self.transcript(usage_line(199999))), (0, ""))
        code, out = self.prompt(self.transcript(usage_line(205000)))
        self.assertIn("205000", self.context(out)["additionalContext"])
        self.assertEqual(self.prompt(self.transcript(usage_line(210000))), (0, ""))

    def test_a_drop_under_the_limit_restarts_the_bands(self) -> None:
        self.assertNotEqual(self.prompt(self.transcript(usage_line(160000)))[1], "")
        self.assertEqual(self.prompt(self.transcript(usage_line(40000))), (0, ""))
        code, out = self.prompt(self.transcript(usage_line(160000)))
        self.assertEqual(code, 0)
        self.assertIn("160000", self.context(out)["additionalContext"])

    def test_under_the_limit_with_no_state_file_gives_no_output(self) -> None:
        self.assertEqual(self.prompt(self.transcript(usage_line(40000))), (0, ""))

    def test_another_session_has_its_own_band(self) -> None:
        path = self.transcript(usage_line(160000))
        self.assertNotEqual(self.prompt(path, "a")[1], "")
        self.assertNotEqual(self.prompt(path, "b")[1], "")

    def test_a_sidechain_line_is_ignored(self) -> None:
        under = self.transcript(usage_line(1000), usage_line(300000, sidechain=True))
        self.assertEqual(self.prompt(under), (0, ""))
        over = self.transcript(usage_line(170000), usage_line(1000, sidechain=True))
        self.assertIn("170000", self.context(self.prompt(over)[1])["additionalContext"])

    def test_a_line_without_usage_and_a_partial_line_are_skipped(self) -> None:
        path = self.transcript('{"partial": ', usage_line(170000), '{"type": "user"}', "not json")
        self.assertIn("170000", self.context(self.prompt(path)[1])["additionalContext"])

    def test_pr_create_gives_one_message(self) -> None:
        code, out = self.bash("gh pr create --base dev --title x")
        self.assertEqual(code, 0)
        hook = self.context(out)
        self.assertEqual(hook["hookEventName"], "PostToolUse")
        self.assertIn("new session", hook["additionalContext"])

    def test_other_bash_commands_give_no_output(self) -> None:
        for command in ("git status", "gh pr view 3", "gh pr list", "echo hi"):
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), (0, ""))

    def test_missing_transcript_exits_0_with_no_output(self) -> None:
        self.assertEqual(self.prompt(str(self.tmp / "none.jsonl")), (0, ""))
        self.assertEqual(self.prompt(None), (0, ""))

    def test_unreadable_transcript_exits_0_with_no_output(self) -> None:
        self.assertEqual(self.prompt(str(self.tmp)), (0, ""))  # a folder
        binary = self.tmp / "bin.jsonl"
        binary.write_bytes(os.urandom(2000))
        self.assertEqual(self.prompt(str(binary)), (0, ""))
        if os.name == "posix" and os.geteuid() != 0:
            locked = self.tmp / "locked.jsonl"
            locked.write_text(usage_line(170000) + "\n", encoding="utf-8")
            locked.chmod(0)
            self.assertEqual(self.prompt(str(locked)), (0, ""))

    def test_bad_stdin_exits_0_with_no_output(self) -> None:
        for text in ("", "not json", "[1, 2]", "null", '{"hook_event_name": "Other"}'):
            with self.subTest(stdin=text):
                self.assertEqual(self.run_hook(text), (0, ""))

    def test_a_large_transcript_is_read_from_its_end(self) -> None:
        lines = [usage_line(1000)] * 30000 + [usage_line(170000)]
        self.assertIn("170000", self.context(self.prompt(self.transcript(*lines))[1])["additionalContext"])


class ConfigTest(GuardBase):
    def guard_entries(self, data: dict) -> list[str]:
        return [h["command"] for group in sum(data.get("hooks", {}).values(), [])
                for h in group["hooks"] if "context-guard" in h["command"]]

    def test_default_renders_the_hook_the_settings_and_the_component(self) -> None:
        self.go()
        self.assertTrue((self.root / HOOK).is_file())
        self.assertIn("LIMIT = 150000", (self.root / HOOK).read_text(encoding="utf-8"))
        data = self.settings()
        self.assertEqual(len(self.guard_entries(data)), 2)
        self.assertIn("UserPromptSubmit", data["hooks"])
        self.assertIn("PostToolUse", data["hooks"])
        self.assertIn("hook.context-guard", self.components())

    def test_zero_turns_the_guard_off(self) -> None:
        self.go(0)
        self.assertFalse((self.root / HOOK).exists())
        self.assertEqual(self.guard_entries(self.settings()), [])
        self.assertNotIn("context-guard", (self.root / SETTINGS).read_text(encoding="utf-8"))
        self.assertNotIn("hook.context-guard", self.components())

    def test_a_custom_limit_is_in_the_script(self) -> None:
        self.go(100000)
        self.assertIn("LIMIT = 100000", (self.root / HOOK).read_text(encoding="utf-8"))

    def test_a_limit_above_the_default_or_not_valid_is_refused(self) -> None:
        for value in (200000, 150001, -1, "x", True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(render.RenderError):
                    self.go(value)
                (self.root / ".cornerstone" / "config.yaml").write_text(config_text(value), encoding="utf-8")
                findings = framework_check.check_config(self.root, FRAMEWORK)
                self.assertTrue(any("session_context_tokens" in str(f) for f in findings), findings)

    def test_the_default_and_the_edge_values_pass_check(self) -> None:
        for value in ("absent", 0, 1, 150000):
            with self.subTest(value=value):
                self.go(value)
                findings = framework_check.check_config(self.root, FRAMEWORK)
                self.assertFalse(any("session_context_tokens" in str(f) for f in findings), findings)

    def test_rerender_to_zero_removes_the_guard_and_keeps_a_hand_entry(self) -> None:
        self.go()
        data = self.settings()
        mine = {"hooks": [{"type": "command", "command": "echo mine"}]}
        data["hooks"]["UserPromptSubmit"].append(mine)
        (self.root / SETTINGS).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.go(0)
        data = self.settings()
        self.assertEqual(self.guard_entries(data), [])
        self.assertIn(mine, data["hooks"]["UserPromptSubmit"])
        self.assertNotIn("context-guard", json.dumps(data))

    def test_rerender_with_the_same_value_changes_nothing(self) -> None:
        self.go()
        before = (self.root / SETTINGS).read_text(encoding="utf-8")
        result = self.go()
        self.assertIn(SETTINGS, result.skipped)
        self.assertEqual((self.root / SETTINGS).read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
