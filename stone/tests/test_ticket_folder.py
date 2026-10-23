"""Issue #146: '{id}' in paths.plans and paths.reports gives one folder for each ticket."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import framework_check, personas_check, render, specialists, specs
from test_personas_check import PERSONAS, persona
from test_render import CONFIG, FRAMEWORK, TODAY
from test_specialists import put_module
from test_specs import added

PLANS_ID = ".stone/plans/{id}/"
REPORTS_ID = "docs/reports/{id}/"
BAD_VALUES = ("a/{id}/{id}/", "a/{id}/b/", "a/../{id}/", "/abs/{id}/", '"{id}/"', "a/{id}x/")
HOOK = ".cornerstone/hooks/protect-paths.py"


def config_with(plans: str = "docs/plans/", reports: str | None = None,
                profiles: str = "[app-slice, bug-triage]") -> str:
    """Return the render test config, with the plans folder, a reports folder, and profiles."""
    text = CONFIG.replace("plans: docs/plans/", f"plans: {plans}")
    if reports is not None:
        text = text.replace("  plans:", f"  reports: {reports}\n  plans:")
    return text.replace("profiles: [single-ticket]", f"profiles: {profiles}")


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def write(self, path: str, text: str = "x\n") -> Path:
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")
        return full

    def config(self, text: str) -> None:
        self.write(".cornerstone/config.yaml", text)


class FolderProblemTest(unittest.TestCase):
    def test_valid_and_invalid_values(self) -> None:
        for key in ("plans", "reports"):
            for value in (PLANS_ID, "docs/reports/{id}", "a/b/{id}/"):
                with self.subTest(key=key, value=value):
                    self.assertEqual(specs.ticket_folder_problem(key, value), "")
            for value in ("docs/plans/", *(v.strip('"') for v in BAD_VALUES)):
                with self.subTest(key=key, value=value, bad=True):
                    problem = specs.ticket_folder_problem(key, value)
                    self.assertEqual(bool(problem), "{id}" in value, value)
                    if problem:
                        self.assertIn(f"paths.{key}", problem)

    def test_folder_prefix_and_config_problems(self) -> None:
        self.assertEqual(framework_check._folder_prefix(".stone/plans/{id}/"), ".stone/plans")
        self.assertEqual(framework_check.ticket_folder_problems({}), [])
        self.assertEqual(framework_check.ticket_folder_problems(
            {"paths": {"plans": PLANS_ID, "reports": REPORTS_ID}}), [])
        problems = framework_check.ticket_folder_problems(
            {"paths": {"plans": "a/{id}/{id}/", "reports": ["b/{id}/c/"]}})
        self.assertEqual(len(problems), 2)

    def test_protected_overlap(self) -> None:
        cases = ({"plans": ".claude/plans/{id}/"}, {"tests": ["tests/**"], "plans": "tests/{id}/"})
        for paths in cases:
            with self.subTest(paths=paths):
                problems = framework_check.protected_path_problems({"paths": paths})
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("plans", problems[0])
        self.assertEqual(framework_check.protected_path_problems(
            {"paths": {"tests": ["tests/**"], "plans": PLANS_ID}}), [])


class RenderTicketFolderTest(RepoCase):
    def render(self, text: str) -> None:
        self.config(text)
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK, today=TODAY)

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def run_hook(self, path: str, role: str) -> int:
        event = json.dumps({"tool_input": {"file_path": str(self.root / path)}})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root), "STONE_ROLE": role}
        return subprocess.run([sys.executable, HOOK], cwd=self.root, input=event, env=env,
                              capture_output=True, text=True).returncode

    def test_role_text_and_hook_lists(self) -> None:
        self.render(config_with(PLANS_ID, REPORTS_ID))
        base = ".stone/plans/<ticket-id>/<ticket-id>"
        self.assertIn(f"`{base}.decisions.md`", self.read(".claude/agents/implementer.md"))
        for role in ("tester", "reviewer"):
            self.assertIn(f"{base}.spec.md", self.read(f".claude/agents/{role}.md"))
        planner = self.read(".claude/agents/planner.md")
        self.assertIn(f"{base}.md", planner)
        self.assertIn(".stone/plans/*/", planner)
        self.assertNotIn("{id}", planner)
        self.assertIn("docs/reports/<ticket-id>/<ticket-id>.md",
                      self.read(".claude/agents/investigator.md"))
        hook = self.read(HOOK)
        self.assertIn('PLANS = [".stone/plans/*/"]', hook)
        self.assertIn('REPORTS = ["docs/reports/*/"]', hook)

    def test_hook_allows_ticket_folders_only(self) -> None:
        self.render(config_with(PLANS_ID, REPORTS_ID))
        cases = (("planner", ".stone/plans/MEG-1/MEG-1.md", 0),
                 ("planner", ".stone/plans/MEG-2/MEG-2.spec.md", 0),
                 ("planner", ".stone/plans/MEG-1.md", 2), ("planner", ".stone/other/x.md", 2),
                 ("investigator", "docs/reports/MEG-1/MEG-1.md", 0),
                 ("investigator", "docs/reports/MEG-2/a.md", 0),
                 ("investigator", "docs/reports/MEG-1.md", 2),
                 ("investigator", "docs/other/x.md", 2))
        for role, path, code in cases:
            with self.subTest(role=role, path=path):
                self.assertEqual(self.run_hook(path, role), code)

    def test_invalid_values_raise_render_error(self) -> None:
        for key in ("plans", "reports"):
            for value in (*BAD_VALUES[:-1], '["a/{id}/", "b/{id}/"]'):
                with self.subTest(key=key, value=value):
                    text = (config_with(value) if key == "plans"
                            else config_with(reports=value))
                    with self.assertRaises(render.RenderError):
                        self.render(text)

    def test_ignore_patterns_use_the_base_folder(self) -> None:
        config = yaml.safe_load(CONFIG.replace(
            "plans: docs/plans/", f"plans: {PLANS_ID}\n  reports: {REPORTS_ID}"))
        patterns = render.ignore_patterns(config, [])
        self.assertIn(".stone/plans/", patterns)
        self.assertIn("docs/reports/", patterns)
        self.assertFalse([p for p in patterns if "{id}" in p])

    def test_no_id_keeps_the_old_output(self) -> None:
        self.render(config_with())
        planner = self.read(".claude/agents/planner.md")
        self.assertIn("docs/plans/<ticket-id>.md", planner)
        self.assertIn("docs/plans/", planner)
        self.assertNotIn("<ticket-id>/", planner)
        self.assertIn('PLANS = ["docs/plans/"]', self.read(HOOK))
        self.assertEqual(self.run_hook("docs/plans/MEG-1.md", "planner"), 0)
        self.assertIn("docs/reports/<ticket-id>.md", self.read(".claude/agents/investigator.md"))


class SpecsTicketFolderTest(RepoCase):
    def delta(self, plan: str, *sections: str, flat: bool = False) -> None:
        path = f"docs/plans/{plan}.spec.md" if flat else f"docs/plans/{plan}/{plan}.spec.md"
        self.write(path, "\n".join(sections))

    def test_deltas_of_several_tickets_are_read_and_applied(self) -> None:
        self.config("paths:\n  plans: docs/plans/{id}/\n")
        self.delta("A-1", added("cart.R1"))
        self.delta("A-2", added("cart.R2"))
        self.delta("A-3", added("cart.R3"), flat=True)  # a flat file: skipped
        self.assertEqual(sorted(specs.load_deltas(self.root)), ["A-1", "A-2"])
        specs.apply(self.root, "A-1")
        specs.apply(self.root, "A-2")  # sees the spec history of A-1
        text = (self.root / "docs/specs/cart.md").read_text(encoding="utf-8")
        self.assertIn("cart.R1", text)
        self.assertIn("cart.R2", text)
        self.assertNotIn("cart.R3", text)
        self.assertEqual(specs.check(self.root), [])

    def test_missing_delta_names_the_ticket_folder(self) -> None:
        self.config("paths:\n  plans: docs/plans/{id}/\n")
        with self.assertRaises(specs.SpecError) as ctx:
            specs.apply(self.root, "A-9")
        self.assertIn("docs/plans/A-9/A-9.spec.md", str(ctx.exception))

    def test_bad_value_is_a_k19_finding(self) -> None:
        self.config("paths:\n  plans: docs/{id}/plans/\n")
        findings = specs.check(self.root)
        self.assertEqual([f.check for f in findings], ["K19"])

    def test_no_id_reads_flat(self) -> None:
        self.delta("A-1", added("cart.R1"), flat=True)
        self.delta("A-2", added("cart.R2"))  # in a folder: skipped
        self.assertEqual(sorted(specs.load_deltas(self.root)), ["A-1"])
        with self.assertRaises(specs.SpecError) as ctx:
            specs.apply(self.root, "A-9")
        self.assertIn("docs/plans/A-9.spec.md", str(ctx.exception))
        self.assertNotIn("A-9/A-9", str(ctx.exception))


class PersonasTicketFolderTest(RepoCase):
    def test_k18_reads_each_ticket_folder(self) -> None:
        self.config("paths:\n  plans: .stone/plans/{id}/\n")
        self.write(PERSONAS, "# Personas\n\n" + persona())
        self.write(".stone/plans/T-1/T-1.md", "Personas: ghost\n")
        self.write(".stone/plans/T-2/T-2.md", "Personas: phantom\n")
        self.write(".stone/plans/T-3.md", "Personas: flat-ghost\n")  # flat: not read
        findings = personas_check.run(self.root)
        self.assertEqual(sorted(f.path for f in findings),
                         [".stone/plans/T-1/T-1.md", ".stone/plans/T-2/T-2.md"])
        self.assertTrue(all("ghost" in f.message or "phantom" in f.message for f in findings))

    def test_k18_no_id_reads_flat_only(self) -> None:
        self.write(PERSONAS, "# Personas\n\n" + persona())
        self.write("docs/plans/T-1.md", "Personas: ghost\n")
        self.write("docs/plans/T-2/T-2.md", "Personas: phantom\n")
        self.assertEqual([f.path for f in personas_check.run(self.root)], ["docs/plans/T-1.md"])


class SpecialistsTicketFolderTest(RepoCase):
    def test_paths_with_id(self) -> None:
        config = {"paths": {"reports": REPORTS_ID}}
        self.assertEqual(specialists.reports_folder(config), "docs/reports/<ticket-id>/")
        self.assertEqual(specialists.report_path(self.root, config, "MEG-1", "sec"),
                         self.root / "docs/reports/MEG-1/MEG-1.sec.md")

    def test_no_id_keeps_the_flat_path(self) -> None:
        self.assertEqual(specialists.report_path(self.root, {}, "MEG-1", "sec"),
                         self.root / "docs/reports/MEG-1.sec.md")
        self.assertEqual(specialists.reports_folder({}), "docs/reports/")

    def test_document_and_k20_use_the_ticket_folder(self) -> None:
        self.config(config_with(reports=REPORTS_ID, profiles="[single-ticket]")
                    + "specialists:\n  - id: security\n    run: /security-review\n")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK, today=TODAY)
        doc = (self.root / specialists.DOC).read_text(encoding="utf-8")
        self.assertIn("docs/reports/<ticket-id>/<ticket-id>.<id>.md", doc)
        config = yaml.safe_load((self.root / ".cornerstone/config.yaml").read_text())
        put_module(self.root)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        spec = config["specialists"][0]
        self.write("docs/reports/T1/T1.security.md", "Severity: low\n")
        self.assertEqual(specialists.status(self.root, config, "T1", spec), "reviewed")
        (self.root / "docs/reports/T1/T1.security.md").unlink()
        self.write("docs/reports/T1.security.md", "Severity: low\n")  # flat: not found
        self.assertEqual(specialists.status(self.root, config, "T1", spec), "missing")


if __name__ == "__main__":
    unittest.main()
