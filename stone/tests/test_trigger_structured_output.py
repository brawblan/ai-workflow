"""Issue #166: a trigger role must be able to return `structured_output` with `--agent`.

The trigger workflows run `claude --agent <role> --json-schema ...`. The `tools:` line of the role
file limits the run. If it has no `StructuredOutput`, the run returns no `structured_output`.
The offline tests render real profiles. The live test runs `claude` and needs `STONE_LIVE_CLAUDE=1`.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from stone import render

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
AGENT_TEMPLATES = FRAMEWORK / "adapters" / "claude-code" / "templates" / "agents"
LIVE_ENV = "STONE_LIVE_CLAUDE"
D32_DENIED = {"Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch"}
CONFIG = """framework_version: 0.8.0
harness: claude-code
model_profile: claude-5
profiles: [{profile}]
branches: {{integration: dev, main: main}}
commands:
  install: pip install .
  test_unit: python -m unittest
  all_checks: make check
paths:
  tests: [tests/]
  checks: [.github/workflows/, .cornerstone/checks/]
  plans: docs/plans/
owners: {{default: octocat}}
"""
TRIGGER_PROFILES = ["bug-triage", "dependency-upgrade", "single-ticket", "debugging",
                    "code-audit", "adapter-refresh", "app-slice"]


def render_profile(root: Path, profile: str) -> None:
    (root / ".cornerstone").mkdir(parents=True, exist_ok=True)
    (root / ".cornerstone" / "config.yaml").write_text(CONFIG.format(profile=profile),
                                                       encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()):
        render.render(root, FRAMEWORK, today=dt.date(2026, 10, 18))


def claude_args_of(workflow: Path) -> list[str]:
    """Return the `claude_args` text of each step in the workflow."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("claude_args"), str):
                found.append(node["claude_args"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(yaml.safe_load(workflow.read_text(encoding="utf-8")))
    return found


def tools_line(agent_file: Path) -> str:
    match = re.search(r"^tools: (.*)$", agent_file.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"no tools line in {agent_file}"
    return match.group(1)


def tool_names(line: str) -> list[str]:
    return [name.strip() for name in line.split(",")]


class TriggerStructuredOutputTest(unittest.TestCase):
    def test_every_json_schema_trigger_role_lists_structured_output(self) -> None:
        checked = 0
        for profile in TRIGGER_PROFILES:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                render_profile(root, profile)
                for workflow in sorted((root / ".github" / "workflows").glob("cornerstone-*.yml")):
                    for args in claude_args_of(workflow):
                        if "--json-schema" not in args:
                            continue
                        with self.subTest(profile=profile, workflow=workflow.name):
                            role = shlex.split(args)[shlex.split(args).index("--agent") + 1]
                            agent = root / ".claude" / "agents" / f"{role}.md"
                            self.assertTrue(agent.exists(), f"no role file for {role}")
                            self.assertIn("StructuredOutput", tool_names(tools_line(agent)))
                            checked += 1
        self.assertGreaterEqual(checked, 5)

    def test_json_schema_triggers_keep_the_d32_disallowed_tools(self) -> None:
        checked = 0
        for profile in TRIGGER_PROFILES:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                render_profile(root, profile)
                for workflow in sorted((root / ".github" / "workflows").glob("cornerstone-*.yml")):
                    for args in claude_args_of(workflow):
                        if "--json-schema" not in args:
                            continue
                        with self.subTest(profile=profile, workflow=workflow.name):
                            words = shlex.split(args)
                            denied = set(words[words.index("--disallowedTools") + 1].split(","))
                            self.assertTrue(D32_DENIED <= denied, denied)
                            self.assertNotIn("StructuredOutput", denied)
                            checked += 1
        self.assertGreaterEqual(checked, 5)

    def test_every_role_template_renders_structured_output(self) -> None:
        roles = sorted(path.stem for path in AGENT_TEMPLATES.glob("*.md"))
        self.assertEqual(roles, ["implementer", "investigator", "planner", "reviewer", "shaper",
                                 "tester"])
        for source in ("issue", "file"):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                extra = "tickets:\n  source: file\n  path: docs/tickets/{id}.txt\n"
                render_profile(root, "app-slice")  # app-slice has all six roles but one
                if source == "file":
                    config = root / ".cornerstone" / "config.yaml"
                    config.write_text(config.read_text(encoding="utf-8") + extra, encoding="utf-8")
                    with contextlib.redirect_stderr(io.StringIO()):
                        render.render(root, FRAMEWORK, today=dt.date(2026, 10, 18))
                rendered = {p.stem for p in (root / ".claude" / "agents").glob("*.md")}
                for role in rendered:
                    with self.subTest(source=source, role=role):
                        line = tools_line(root / ".claude" / "agents" / f"{role}.md")
                        self.assertIn("StructuredOutput", tool_names(line))
                self.assertTrue({"shaper", "planner", "implementer", "tester",
                                 "reviewer"} <= rendered)
        with tempfile.TemporaryDirectory() as folder:
            render_profile(Path(folder), "bug-triage")
            line = tools_line(Path(folder) / ".claude" / "agents" / "investigator.md")
            self.assertIn("StructuredOutput", tool_names(line))


@unittest.skipUnless(os.environ.get(LIVE_ENV) == "1" and shutil.which("claude"),
                     f"set {LIVE_ENV}=1 and install claude to run the live test")
class LiveStructuredOutputTest(unittest.TestCase):
    def test_live_shaper_with_agent_returns_structured_output(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            render_profile(root, "single-ticket")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "README.md").write_text("# Demo\n\nA small demo project.\n", encoding="utf-8")
            workflow = next((root / ".github" / "workflows").glob("*-label.yml"))
            args = next(a for a in claude_args_of(workflow) if "--json-schema" in a)
            words = shlex.split(args)
            schema = words[words.index("--json-schema") + 1]
            model = os.environ.get("STONE_LIVE_MODEL", "haiku")
            prompt = "Read README.md. Write a one-line report about it as the report field."
            command = ["claude", "-p", "--agent", "shaper", "--model", model, "--max-turns", "10",
                       "--setting-sources", "project", "--output-format", "json",
                       "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch",
                       "--allowedTools", "Read(./**)", "--json-schema", schema, "--", prompt]
            run = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=300)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            result = json.loads(run.stdout)
            if isinstance(result, list):
                result = next(item for item in result if item.get("type") == "result")
            output = result.get("structured_output")
            self.assertIsInstance(output, dict, run.stdout)
            self.assertIsInstance(output.get("report"), str)
            self.assertTrue(output["report"].strip())
            print(f"\nlive: turns={result.get('num_turns')} report={output['report']!r}")


if __name__ == "__main__":
    unittest.main()
