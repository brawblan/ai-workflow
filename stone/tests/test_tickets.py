"""Issue #137: tickets as files, the shaper tools, and the hook rule for the shaper."""

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

from stone import framework_check, render
from test_render import CONFIG, FRAMEWORK

FILE = "tickets:\n  source: file\n  path: docs/tickets/{id}.txt\n"
HOOK = ".cornerstone/hooks/protect-paths.py"


class TicketsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def render(self, extra: str = "") -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG + extra, encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK, today=dt.date(2026, 10, 17))

    def text(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def hook(self, path: str, role: str = "shaper") -> int:
        event = {"hook_event_name": "PreToolUse", "tool_name": "Write", "agent_type": role,
                 "tool_input": {"file_path": str(self.root / path)}}
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root)}
        return subprocess.run([sys.executable, HOOK], cwd=self.root, input=json.dumps(event),
                              env=env, capture_output=True, text=True).returncode

    def test_default_shaper_reads_the_issue_and_has_no_file_tool(self) -> None:
        self.render()
        shaper = self.text(".claude/agents/shaper.md")
        self.assertIn("tools: Read, Grep, Glob, Bash\n", shaper)
        self.assertIn("read the ticket with the issue CLI. Do not change files in the repo.", shaper)
        self.assertNotIn("The ticket is the file", self.text(".claude/agents/implementer.md"))
        self.assertEqual(self.hook("docs/tickets/A-1.txt"), 0)  # no file tool in the role file

    def test_file_source_gives_the_shaper_write_and_the_form(self) -> None:
        self.render(FILE)
        shaper = self.text(".claude/agents/shaper.md")
        self.assertIn("tools: Read, Grep, Glob, Bash, Write, Edit\n", shaper)
        self.assertIn("The ticket is the file `docs/tickets/{id}.txt`.", shaper)
        self.assertIn("Write the answers into the Definition of Ready section of the ticket file.",
                      shaper)
        self.assertIn("## Definition of Ready\nProblem:", shaper)
        self.assertIn("Change only the ticket file.", shaper)
        self.assertNotIn("issue CLI", shaper)

    def test_other_roles_read_the_ticket_from_the_file(self) -> None:
        self.render(FILE)
        for role in ("implementer", "tester", "reviewer"):
            self.assertIn("The ticket is the file `docs/tickets/{id}.txt`.",
                          self.text(f".claude/agents/{role}.md"), role)

    def test_hook_lets_the_shaper_change_only_the_ticket_file(self) -> None:
        self.render(FILE)
        self.assertEqual(self.hook("docs/tickets/PROJ-1.txt"), 0)
        for path in ("src/a.py", "tests/test_a.py", "docs/tickets/sub/PROJ-1.txt",
                     "docs/tickets/PROJ-1.md", ".cornerstone/config.yaml"):
            with self.subTest(path=path):
                self.assertEqual(self.hook(path), 2)

    def test_hook_does_not_give_other_roles_the_ticket_file(self) -> None:
        self.render(FILE)
        self.assertEqual(self.hook("docs/tickets/PROJ-1.txt", "tester"), 2)
        self.assertEqual(self.hook("docs/tickets/PROJ-1.txt", "reviewer"), 2)

    def test_ticket_path_in_a_harness_folder_is_valid(self) -> None:
        self.render("tickets:\n  source: file\n  path: .claude/prompts/{id}.txt\n")
        self.assertEqual(self.hook(".claude/prompts/PROJ-1.txt"), 0)
        self.assertEqual(self.hook(".claude/settings.json"), 2)

    def test_check_rejects_bad_sections(self) -> None:
        for extra, message in (
                ("tickets: file\n", "'tickets' must be a map"),
                ("tickets: {source: jira}\n", "'tickets.source' is 'jira'"),
                ("tickets: {source: file}\n", "needs 'tickets.path'"),
                ("tickets: {source: file, path: docs/a.txt}\n", "needs '{id}' once"),
                ("tickets: {source: file, path: 'docs/{id}/{id}.txt'}\n", "needs '{id}' once"),
                ("tickets: {source: file, path: '../x/{id}.txt'}\n", "no '..' and no glob"),
                ("tickets: {source: file, path: 'docs/*/{id}.txt'}\n", "no '..' and no glob"),
                ("tickets: {source: file, path: '/etc/{id}'}\n", "no '..' and no glob"),
                ("tickets: {source: github, path: 'x/{id}'}\n", "only for 'tickets.source: file'"),
                ("tickets: {source: file, path: 'tests/{id}.txt'}\n", "overlaps 'paths.tests'"),
                ("tickets: {source: file, path: '.cornerstone/checks/{id}'}\n",
                 "overlaps 'paths.checks'"),
                ("tickets: {source: file, path: 'x/{id}', size: 1}\n", "'tickets.size' is not a key")):
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(render.RenderError, message):
                    self.render(extra)

    def test_a_valid_file_section_passes_stone_check(self) -> None:
        self.render(FILE)
        self.assertEqual(framework_check.check_config(self.root, FRAMEWORK), [])


if __name__ == "__main__":
    unittest.main()
