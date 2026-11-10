"""Tests for `stone render` with the full OpenCode adapter (issue #326).

The tests use the real adapter files in `framework/adapters/opencode/`. A temporary copy of the
framework is used where a test changes a template.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import render

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
ADAPTER = FRAMEWORK / "adapters" / "opencode"
ROLES = ["shaper", "planner", "implementer", "tester", "reviewer", "investigator"]
DENY_ALL = {"action": "*", "resource": "*", "effect": "deny"}
BASE = """framework_version: 1.8.0
harness: opencode
model_profile: opencode-default
profiles: [single-ticket, spike, full-project]
branches: {integration: dev, main: main}
commands: {install: "true", test_unit: "true", all_checks: "true"}
paths:
  tests: [tests/]
  checks: [.cornerstone/checks/]
  plans: docs/plans/
owners: {default: octocat}
"""

_spec = importlib.util.spec_from_file_location("opencode_values", ADAPTER / "values.py")
values = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(values)


def edits(rules: list[dict], effect: str | None = None) -> list[tuple[str, str]]:
    """Return (resource, effect) for each edit rule, optionally only one effect."""
    return [(r["resource"], r["effect"]) for r in rules
            if r["action"] == "edit" and effect in (None, r["effect"])]


class OpenCodeRenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "repo"
        (self.root / ".cornerstone").mkdir(parents=True)

    def config(self, text: str = BASE) -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")

    def render(self, framework: Path = FRAMEWORK, config: str | None = None):
        if config is not None:
            self.config(config)
        with contextlib.redirect_stderr(io.StringIO()):
            return render.render(self.root, framework)

    def rules(self, role: str) -> list[dict]:
        text = (self.root / ".opencode" / "agents" / f"{role}.md").read_text(encoding="utf-8")
        return yaml.safe_load(text.split("---\n", 2)[1])["permissions"]

    def front(self, role: str) -> dict:
        text = (self.root / ".opencode" / "agents" / f"{role}.md").read_text(encoding="utf-8")
        return yaml.safe_load(text.split("---\n", 2)[1])

    # An unknown permission action
    def test_render_refuses_an_unknown_permission_action_and_writes_nothing(self) -> None:
        framework = self.base / "fw"
        shutil.copytree(FRAMEWORK, framework, ignore=shutil.ignore_patterns("__pycache__"))
        template = framework / "adapters" / "opencode" / "templates" / "agents" / "reviewer.md"
        text = template.read_text(encoding="utf-8")
        self.assertIn("action: shell", text)
        template.write_text(text.replace("action: shell", "action: bash", 1), encoding="utf-8")
        self.config()
        with self.assertRaises(render.RenderError) as caught:
            self.render(framework)
        self.assertIn("bash", str(caught.exception))
        self.assertFalse((self.root / ".opencode").exists())
        self.assertFalse((self.root / "opencode.json").exists())
        self.assertFalse((self.root / ".cornerstone" / "manifest.yaml").exists())

    def test_render_accepts_each_listed_permission_action(self) -> None:
        registry = yaml.safe_load((ADAPTER / "components.yaml").read_text(encoding="utf-8"))
        self.assertEqual(registry["status"], "full")
        self.config()
        result = self.render()
        self.assertEqual(result.exit_code, 0)
        used = {rule["action"] for role in ROLES for rule in self.rules(role)}
        self.assertLessEqual(used, set(registry["permission_actions"]))

    # Each role file
    def test_each_role_file_denies_all_first_and_has_model_and_steps(self) -> None:
        self.config()
        self.render()
        profile = yaml.safe_load(
            (ADAPTER / "models" / "opencode-default.yaml").read_text(encoding="utf-8"))
        for role in ROLES:
            with self.subTest(role=role):
                front = self.front(role)
                self.assertEqual(front["permissions"][0], DENY_ALL)
                self.assertEqual(front["steps"], 60)
                self.assertEqual(front["model"], profile["defaults"]["role_models"][role])

    def test_no_role_file_keeps_a_placeholder(self) -> None:
        self.config()
        self.render()
        for role in ROLES:
            text = (self.root / ".opencode" / "agents" / f"{role}.md").read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\$[a-z_]+_(edit_rules|permissions)", role)

    def test_implementer_denies_edit_of_protected_paths(self) -> None:
        self.config(BASE + "protect_instruction_files: true\n")
        self.render()
        rules = self.rules("implementer")
        resources = {resource for resource, effect in edits(rules, "deny")}
        for path in ("tests", "tests/*", ".cornerstone/checks", ".cornerstone/checks/*",
                     "docs/specs", "docs/specs/*", ".opencode", ".opencode/*", "opencode.json",
                     ".cornerstone", ".cornerstone/*"):
            self.assertIn(path, resources)
        # The last rules are denies: the implementer's edit allow (from the template) comes first.
        extra = [r for r in rules if r["resource"] != "*" and r["action"] == "edit"]
        self.assertTrue(extra and all(r["effect"] == "deny" for r in extra))

    def test_tester_denies_all_then_allows_tests_then_denies_harness(self) -> None:
        self.config()
        self.render()
        tail = edits(self.rules("tester"))[1:]  # after the template's `edit *` allow
        self.assertEqual(tail[0], ("*", "deny"))
        allow = [i for i, (_, effect) in enumerate(tail) if effect == "allow"]
        self.assertEqual([tail[i][0] for i in allow], ["tests", "tests/*"])
        deny_after = [r for r, _ in tail[allow[-1] + 1:]]
        for path in (".opencode", ".opencode/*", "opencode.json", ".cornerstone", ".cornerstone/*"):
            self.assertIn(path, deny_after)
        self.assertTrue(all(effect == "deny" for _, effect in tail[allow[-1] + 1:]))

    def test_tester_does_not_get_edit_allow_outside_the_test_paths(self) -> None:
        self.config()
        self.render()
        tail = edits(self.rules("tester"))[1:]
        self.assertEqual({r for r, e in tail if e == "allow"}, {"tests", "tests/*"})

    def test_planner_allows_only_the_plans_path(self) -> None:
        self.config()
        self.render()
        tail = edits(self.rules("planner"))[1:]
        self.assertEqual(tail[0], ("*", "deny"))
        self.assertEqual([r for r, e in tail if e == "allow"], ["docs/plans", "docs/plans/*"])

    def test_investigator_allows_only_the_reports_path(self) -> None:
        self.config()
        self.render()
        tail = edits(self.rules("investigator"))[1:]
        self.assertEqual(tail[0], ("*", "deny"))
        self.assertEqual([r for r, e in tail if e == "allow"],
                         ["docs/reports", "docs/reports/*"])

    def test_reviewer_has_no_edit_rule(self) -> None:
        self.config()
        self.render()
        self.assertEqual(edits(self.rules("reviewer")), [])

    def test_shaper_edit_rule_is_only_for_a_file_ticket_source(self) -> None:
        self.config()
        self.render()
        self.assertEqual(edits(self.rules("shaper")), [])
        self.root = self.base / "repo2"
        (self.root / ".cornerstone").mkdir(parents=True)
        self.render(config=BASE + "tickets: {source: file, path: 'tickets/{id}.md'}\n")
        rules = self.rules("shaper")
        self.assertEqual(rules[0], DENY_ALL)
        self.assertEqual(edits(rules), [("tickets/*.md", "allow")])

    def test_instruction_files_are_denied_only_when_protected(self) -> None:
        self.config(BASE + "protect_instruction_files: false\n")
        self.render()
        for role in ("implementer", "tester", "planner", "investigator"):
            self.assertFalse([r for r in self.rules(role) if "AGENTS" in r["resource"].upper()],
                             role)
        config = (self.root / "opencode.json").read_text(encoding="utf-8")
        self.assertNotIn("AGENTS", config.upper())
        self.root = self.base / "repo2"
        (self.root / ".cornerstone").mkdir(parents=True)
        self.render(config=BASE + "protect_instruction_files: true\n")
        self.assertIn("AGENTS.md", {r["resource"] for r in self.rules("implementer")})

    # Path conversion in values.py
    def test_path_conversion_directory_and_ticket_id(self) -> None:
        self.assertEqual(values.resources(["tests/"]), ["tests", "tests/*"])
        self.assertEqual(values.variants("tickets/{id}.md"), ["tickets/*.md"])
        self.assertEqual(values.resources(["docs/plans/"]), ["docs/plans", "docs/plans/*"])

    def test_path_conversion_case_classes_and_any_folder(self) -> None:
        pattern = "**/[Aa][Gg][Ee][Nn][Tt][Ss].[Mm][Dd]"
        forms = values.variants(pattern)
        for form in ("AGENTS.md", "*/AGENTS.md", "agents.md", "*/agents.md",
                     "AGENTS.MD", "agents.MD"):
            self.assertIn(form, forms)
        self.assertEqual(len(forms), len(set(forms)))
        self.assertEqual(sorted(values.case_forms("[Aa][Bb]")), ["AB", "ab"])  # one word
        self.assertEqual(sorted(values.case_forms("[Aa].[Bb]")), ["A.B", "A.b", "a.B", "a.b"])
        self.assertEqual(set(values.case_forms("[Aa]x")), {"Ax", "ax"})

    def test_path_conversion_gives_no_agents_rule_when_not_protected(self) -> None:
        off = values.values({"protect_instruction_files": False})
        on = values.values({"protect_instruction_files": True})
        for key in ("implementer_edit_rules", "config_permissions_json"):
            self.assertNotIn("AGENTS", off[key])
            self.assertIn("AGENTS.md", on[key])

    # The project config
    def test_opencode_json_has_the_project_permissions(self) -> None:
        self.config()
        self.render()
        data = json.loads((self.root / "opencode.json").read_text(encoding="utf-8"))
        rules = data["permissions"]
        self.assertIn({"action": "external_directory", "resource": "*", "effect": "deny"}, rules)
        denied = {resource for resource, _ in edits(rules, "deny")}
        self.assertLessEqual({".opencode", ".opencode/*", "opencode.json", ".cornerstone",
                              ".cornerstone/*"}, denied)

    def test_opencode_json_merge_keeps_user_keys_and_permissions(self) -> None:
        mine = {"permissions": [{"action": "read", "resource": "*", "effect": "allow"}],
                "theme": "dark"}
        (self.root / "opencode.json").write_text(json.dumps(mine, indent=2) + "\n",
                                                 encoding="utf-8")
        self.config()
        self.render()
        data = json.loads((self.root / "opencode.json").read_text(encoding="utf-8"))
        self.assertEqual(data["theme"], "dark")
        self.assertIn(mine["permissions"][0], data["permissions"])
        self.assertIn(("opencode.json", "deny"), edits(data["permissions"]))

    def test_opencode_json_second_render_skips_it(self) -> None:
        self.config()
        first = self.render()
        self.assertIn("opencode.json", first.wrote)
        before = (self.root / "opencode.json").read_text(encoding="utf-8")
        second = self.render()
        self.assertIn("opencode.json", second.skipped)
        self.assertEqual(second.wrote, [])
        self.assertEqual(second.exit_code, 0)
        self.assertEqual((self.root / "opencode.json").read_text(encoding="utf-8"), before)

    def test_opencode_json_that_is_not_json_is_refused(self) -> None:
        (self.root / "opencode.json").write_text("{nope", encoding="utf-8")
        self.config()
        with self.assertRaises(render.RenderError):
            self.render()

    # Drift
    def test_changed_role_file_is_drift_with_exit_code_2(self) -> None:
        self.config()
        self.render()
        path = self.root / ".opencode" / "agents" / "tester.md"
        path.write_text("my edit\n", encoding="utf-8")
        result = self.render()
        self.assertEqual(result.drift, [".opencode/agents/tester.md"])
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(path.read_text(encoding="utf-8"), "my edit\n")

    def test_second_render_with_no_change_is_clean(self) -> None:
        self.config()
        self.render()
        result = self.render()
        self.assertEqual(result.drift, [])
        self.assertEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
