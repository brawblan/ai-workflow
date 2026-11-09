"""Golden-file test for `stone render` with the guard off (limit 0) (issue #299, D115).

The compare and the update are in `golden_helpers.py`. A fixture is in `golden/context-guard-off/`
or, if it is equal to the shared copy, in `golden/_shared/` (D64). See `guard_golden_helpers.py`.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from golden_helpers import render_config
from guard_golden_helpers import differences

# Not named GOLDEN: the other golden tests then keep sharing settings.json and the hook (D64).
FIXTURES = Path(__file__).resolve().parent / "golden" / "context-guard-off"
CONFIG = """framework_version: 0.8.0
framework_commit: "0123456789abcdef0123456789abcdef01234567"
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
limits:
  session_context_tokens: 0
"""
HOOK = ".cornerstone/hooks/context-guard.py"
SETTINGS = ".claude/settings.json"


class GoldenContextGuardOffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.files = render_config(CONFIG)

    def test_golden_context_guard_off_files_match(self) -> None:
        messages = differences(FIXTURES, self.files)
        self.assertEqual(messages, [], "\n".join(messages))

    def test_golden_context_guard_off_settings(self) -> None:
        text = self.files[SETTINGS].decode("utf-8")
        self.assertEqual("context-guard" in text, False)
        self.assertEqual(HOOK in self.files, False)
        self.assertNotIn("UserPromptSubmit", json.loads(text).get("hooks", {}))

if __name__ == "__main__":
    unittest.main()
