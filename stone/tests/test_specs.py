"""Tests for spec deltas and `stone spec apply`. Each test builds a small repo in a temp folder."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from stone import cli, specs
from stone.markdown import split_frontmatter

PLANS = "docs/plans"
SPECS = "docs/specs"


def added(req_id: str, title: str = "A title", text: str = "The user MUST do it.") -> str:
    return (f"## ADDED {req_id}: {title}\n\n{text}\n\n### Scenario: it works\n"
            "- WHEN the user does it\n- THEN it is done\n")


def modified(req_id: str, title: str = "A new title", text: str = "The new text.") -> str:
    return (f"## MODIFIED {req_id}: {title}\n\n{text}\n\n### Scenario: it still works\n"
            "- WHEN the user does it\n- THEN it is done again\n")


def removed(req_id: str, title: str = "Old", reason: str = "Not used.") -> str:
    return f"## REMOVED {req_id}: {title}\n\n{reason}\n"


class SpecApplyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self) -> None:
        self.folder.cleanup()

    # Helpers

    def write(self, path: str, text: str) -> Path:
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")
        return full

    def delta(self, plan: str, *sections: str, front: str | None = None,
              folder: str = PLANS) -> Path:
        head = f"---\n{front}\n---\n\n" if front is not None else ""
        return self.write(f"{folder}/{plan}.spec.md", head + "\n".join(sections))

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def meta(self, path: str) -> dict:
        return split_frontmatter(self.read(path))[0]

    def snapshot(self) -> dict[str, str]:
        return {p.relative_to(self.root).as_posix(): p.read_text(encoding="utf-8")
                for p in self.root.rglob("*") if p.is_file()}

    def run_cli(self, plan: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["spec", "apply", plan, "--root", str(self.root)])
        return code, out.getvalue()

    def apply(self, plan: str) -> list[str]:
        return specs.apply(self.root, plan)

    def assert_refused(self, plan: str, fragment: str | None = None) -> str:
        """Apply must raise SpecError, write no file, and the CLI must return 1."""
        before = self.snapshot()
        with self.assertRaises(specs.SpecError) as caught:
            self.apply(plan)
        self.assertEqual(self.snapshot(), before, "apply wrote a file on an error")
        code, output = self.run_cli(plan)
        self.assertEqual(code, 1)
        self.assertIn(str(caught.exception), output)
        self.assertEqual(self.snapshot(), before, "the CLI wrote a file on an error")
        if fragment is not None:
            self.assertIn(fragment, str(caught.exception))
        return str(caught.exception)

    def requirement_headings(self, capability: str) -> list[str]:
        return [line for line in self.read(f"{SPECS}/{capability}.md").splitlines()
                if line.startswith("## ")]

    # AC1: read the delta, write one spec for each capability, sort by number, config paths

    def test_ac1_apply_writes_one_spec_for_each_capability(self) -> None:
        self.delta("p1", added("export.R1", "Export a report"), added("login.R1", "Log in"))
        changed = self.apply("p1")
        self.assertEqual(sorted(changed), [f"{PLANS}/p1.spec.md", f"{SPECS}/export.md",
                                           f"{SPECS}/login.md"])
        self.assertEqual(self.requirement_headings("export"), ["## export.R1: Export a report"])
        self.assertEqual(self.requirement_headings("login"), ["## login.R1: Log in"])
        export = self.read(f"{SPECS}/export.md")
        self.assertIn("The user MUST do it.", export)
        self.assertIn("### Scenario: it works", export)
        self.assertNotIn("login.R1", export)

    def test_ac1_requirements_are_sorted_by_number_not_by_text(self) -> None:
        self.delta("p1", added("export.R10", "Ten"), added("export.R2", "Two"),
                   added("export.R1", "One"))
        self.apply("p1")
        self.assertEqual(self.requirement_headings("export"),
                         ["## export.R1: One", "## export.R2: Two", "## export.R10: Ten"])

    def test_ac1_sort_holds_across_deltas(self) -> None:
        self.delta("p1", added("export.R3", "Three"))
        self.apply("p1")
        self.delta("p2", added("export.R1", "One"))
        self.apply("p2")
        self.assertEqual(self.requirement_headings("export"),
                         ["## export.R1: One", "## export.R3: Three"])

    def test_ac1_config_paths_change_the_folders(self) -> None:
        self.write(".cornerstone/config.yaml",
                   "paths:\n  plans: work/plans/\n  specs: product/specs/\n")
        self.delta("p1", added("export.R1"), folder="work/plans")
        changed = self.apply("p1")
        self.assertEqual(sorted(changed), ["product/specs/export.md", "work/plans/p1.spec.md"])
        self.assertTrue((self.root / "product/specs/export.md").is_file())
        self.assertFalse((self.root / SPECS).exists())

    def test_ac1_config_without_paths_uses_defaults(self) -> None:
        self.write(".cornerstone/config.yaml", "framework_version: 0.1.0\n")
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.assertTrue((self.root / SPECS / "export.md").is_file())

    def test_ac1_delta_in_the_default_folder_is_not_read_when_config_moves_plans(self) -> None:
        self.write(".cornerstone/config.yaml", "paths:\n  plans: work/plans/\n")
        self.delta("p1", added("export.R1"))
        self.assert_refused("p1", "p1")

    # AC2: apply_order

    def test_ac2_first_delta_gets_order_1_and_next_gets_max_plus_1(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.assertEqual(self.meta(f"{PLANS}/p1.spec.md")["apply_order"], 1)
        self.delta("p2", added("export.R2"))
        self.apply("p2")
        self.assertEqual(self.meta(f"{PLANS}/p2.spec.md")["apply_order"], 2)

    def test_ac2_next_order_is_one_more_than_the_highest_not_the_count(self) -> None:
        self.delta("p1", added("export.R1"), front="apply_order: 7")
        self.write(f"{SPECS}/export.md", self._replay_text())
        self.delta("p2", added("export.R2"))
        self.apply("p2")
        self.assertEqual(self.meta(f"{PLANS}/p2.spec.md")["apply_order"], 8)

    def test_ac2_other_frontmatter_keys_and_body_stay(self) -> None:
        body = added("export.R1")
        path = self.delta("p1", body, front="plan: p1\nowner: octocat\ntags: [a, b]")
        self.apply("p1")
        meta = self.meta(f"{PLANS}/p1.spec.md")
        self.assertEqual(meta, {"apply_order": 1, "plan": "p1", "owner": "octocat",
                                "tags": ["a", "b"]})
        self.assertTrue(path.read_text(encoding="utf-8").endswith(body))

    def test_ac2_delta_without_frontmatter_gets_frontmatter(self) -> None:
        body = added("export.R1")
        path = self.delta("p1", body)
        self.apply("p1")
        self.assertEqual(self.meta(f"{PLANS}/p1.spec.md"), {"apply_order": 1})
        self.assertTrue(path.read_text(encoding="utf-8").endswith(body))

    # AC3: errors, and no file is written

    def test_ac3_missing_delta(self) -> None:
        self.assert_refused("nothing")

    def test_ac3_already_applied_delta(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.assert_refused("p1", "applied")

    def test_ac3_bad_heading(self) -> None:
        self.delta("p1", added("export.R1"), "## CHANGED export.R2: Bad op\n\n"
                   "### Scenario: s\n- WHEN a\n- THEN b\n")
        self.assert_refused("p1")

    def test_ac3_heading_without_title(self) -> None:
        self.delta("p1", "## ADDED export.R1\n\n### Scenario: s\n- WHEN a\n- THEN b\n")
        self.assert_refused("p1")

    def test_ac3_bad_requirement_ids(self) -> None:
        for bad in ("export.R0", "export.r1", "Export.R1", "export.R01", "export", "export.R1a"):
            with self.subTest(bad=bad):
                self.delta("p1", added(bad))
                self.assert_refused("p1")

    def test_ac3_same_id_two_times(self) -> None:
        self.delta("p1", added("export.R1"), modified("export.R1"))
        self.assert_refused("p1", "export.R1")

    def test_ac3_added_without_scenario(self) -> None:
        self.delta("p1", "## ADDED export.R1: No scenario\n\nThe user MUST do it.\n")
        self.assert_refused("p1", "export.R1")

    def test_ac3_modified_without_scenario(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.delta("p2", "## MODIFIED export.R1: No scenario\n\nNew text.\n")
        self.assert_refused("p2", "export.R1")

    def test_ac3_removed_without_scenario_is_valid(self) -> None:
        self.delta("p1", added("export.R1"), added("export.R2"))
        self.apply("p1")
        self.delta("p2", "## REMOVED export.R1: Old\n")
        self.apply("p2")
        self.assertEqual(self.requirement_headings("export"), ["## export.R2: A title"])

    def test_ac3_delta_with_no_change(self) -> None:
        self.delta("p1", "# Only a title\n\nSome text.\n", front="plan: p1")
        self.assert_refused("p1")

    def test_ac3_empty_delta(self) -> None:
        self.write(f"{PLANS}/p1.spec.md", "")
        self.assert_refused("p1")

    def test_ac3_bad_apply_order_values(self) -> None:
        for bad in ("0", "-1", "two", "1.5", "true"):
            with self.subTest(bad=bad):
                self.delta("p1", added("export.R1"), front=f"apply_order: {bad}")
                self.assert_refused("p1")

    def test_ac3_format_error_in_another_delta_stops_apply(self) -> None:
        self.delta("good", added("export.R1"))
        self.delta("other", "## ADDED bad id: Title\n\n### Scenario: s\n- WHEN a\n- THEN b\n")
        self.assert_refused("good", "other.spec.md")

    def test_ac3_bad_apply_order_in_another_delta_stops_apply(self) -> None:
        self.delta("good", added("export.R1"))
        self.delta("other", added("login.R1"), front="apply_order: 0")
        self.assert_refused("good", "other.spec.md")

    def test_ac3_added_names_an_existing_requirement(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.delta("p2", added("export.R1", "Again"))
        self.assert_refused("p2", "export.R1")

    def test_ac3_modified_names_a_missing_requirement(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.delta("p2", modified("export.R2"))
        self.assert_refused("p2", "export.R2")

    def test_ac3_removed_names_a_missing_requirement(self) -> None:
        self.delta("p1", removed("export.R1"))
        self.assert_refused("p1", "export.R1")

    def test_ac3_conflict_in_a_later_change_writes_nothing(self) -> None:
        self.delta("p1", added("export.R1"), added("login.R1"), modified("export.R9"))
        self.assert_refused("p1", "export.R9")

    def test_rule1_removed_number_is_not_used_again(self) -> None:
        # workflow-model.md, Specs, rule 1: "a removed number is not used again".
        self.delta("p1", added("export.R1"), added("export.R2"))
        self.apply("p1")
        self.delta("p2", removed("export.R1"))
        self.apply("p2")
        self.delta("p3", added("export.R1", "Reused"))
        self.assert_refused("p3", "export.R1")

    def test_rule2_scenario_without_when_and_then_is_refused(self) -> None:
        # workflow-model.md, Specs, rule 2: "at least one `### Scenario:` with WHEN and THEN".
        self.delta("p1", "## ADDED export.R1: Title\n\nText.\n\n### Scenario: empty\n")
        self.assert_refused("p1", "export.R1")

    # AC4: replay and drift

    def test_ac4_modified_replaces_the_full_text(self) -> None:
        self.delta("p1", added("export.R1", "Old title", "Old text."))
        self.apply("p1")
        self.delta("p2", modified("export.R1", "New title", "New text."))
        self.apply("p2")
        text = self.read(f"{SPECS}/export.md")
        self.assertEqual(self.requirement_headings("export"), ["## export.R1: New title"])
        self.assertIn("New text.", text)
        self.assertNotIn("Old text.", text)
        self.assertNotIn("### Scenario: it works", text)

    def test_ac4_replay_uses_apply_order_not_plan_id(self) -> None:
        # "z" is applied first. If the replay sorted by plan ID, "a" would modify a missing R1.
        self.delta("z", added("export.R1"))
        self.apply("z")
        self.delta("a", modified("export.R1"))
        self.apply("a")
        self.delta("m", added("export.R2"))
        self.apply("m")
        self.assertEqual(self.meta(f"{PLANS}/m.spec.md")["apply_order"], 3)

    def test_ac4_tie_in_apply_order_stops_apply(self) -> None:
        # Part 2 changed this rule: a tie is an error, and `stone spec sync` repairs it.
        self.delta("a", added("export.R1", "From a"), front="apply_order: 1")
        self.delta("b", modified("export.R1", "From b"), front="apply_order: 1")
        self.write(f"{SPECS}/export.md", self._replay_text())
        self.delta("c", added("export.R2"))
        message = self.assert_refused("c", "stone spec sync")
        self.assertIn("a.spec.md", message)
        self.assertIn("b.spec.md", message)

    def test_ac4_spec_equals_replay_from_an_empty_folder(self) -> None:
        self.delta("p1", added("export.R1"), added("export.R2"))
        self.apply("p1")
        self.delta("p2", modified("export.R2"), removed("export.R1"), added("export.R3"))
        self.apply("p2")
        self.delta("p3", added("login.R1"))
        self.apply("p3")
        on_disk = {p.name: p.read_text(encoding="utf-8")
                   for p in (self.root / SPECS).glob("*.md")}
        self.assertEqual(on_disk, specs.render_specs(
            specs.replay(specs.applied(specs.load_deltas(self.root)))))

    def test_ac4_drift_from_a_hand_edit(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.write(f"{SPECS}/export.md", self.read(f"{SPECS}/export.md") + "\nA hand edit.\n")
        self.delta("p2", added("export.R2"))
        self.assert_refused("p2", "export.md")

    def test_ac4_drift_from_an_extra_file(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.write(f"{SPECS}/extra.md", "# extra\n")
        self.delta("p2", added("export.R2"))
        self.assert_refused("p2", "extra.md")

    def test_ac4_drift_from_a_missing_file(self) -> None:
        self.delta("p1", added("export.R1"), added("login.R1"))
        self.apply("p1")
        (self.root / SPECS / "login.md").unlink()
        self.delta("p2", added("export.R2"))
        self.assert_refused("p2", "login.md")

    def test_ac4_drift_from_a_deleted_applied_delta(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        (self.root / PLANS / "p1.spec.md").unlink()
        self.delta("p2", added("login.R1"))
        self.assert_refused("p2", "export.md")

    def test_ac4_extra_file_before_any_apply_is_drift(self) -> None:
        self.write(f"{SPECS}/manual.md", "# manual\n")
        self.delta("p1", added("export.R1"))
        self.assert_refused("p1", "manual.md")

    # AC5: removing the last requirement deletes the spec

    def test_ac5_removing_the_last_requirement_deletes_the_spec(self) -> None:
        self.delta("p1", added("export.R1"), added("login.R1"))
        self.apply("p1")
        self.delta("p2", removed("export.R1"))
        changed = self.apply("p2")
        self.assertFalse((self.root / SPECS / "export.md").exists())
        self.assertTrue((self.root / SPECS / "login.md").exists())
        self.assertIn(f"{SPECS}/export.md", changed)
        # The state after the delete is the replay, so a next apply finds no drift.
        self.delta("p3", added("login.R2"))
        self.apply("p3")

    def test_ac5_spec_stays_while_one_requirement_is_left(self) -> None:
        self.delta("p1", added("export.R1"), added("export.R2"))
        self.apply("p1")
        self.delta("p2", removed("export.R1"))
        self.apply("p2")
        self.assertEqual(self.requirement_headings("export"), ["## export.R2: A title"])

    # AC6: a `## ` line in a code block is part of the body

    def test_ac6_heading_in_code_block_is_body(self) -> None:
        text = ("The user MUST see this example:\n\n```markdown\n## Not a change\n"
                "## ADDED other.R1: Not a change\n```")
        self.delta("p1", added("export.R1", "With code", text))
        self.apply("p1")
        spec = self.read(f"{SPECS}/export.md")
        self.assertIn("## Not a change", spec)
        self.assertIn("## ADDED other.R1: Not a change", spec)
        self.assertFalse((self.root / SPECS / "other.md").exists())
        self.assertEqual(self.requirement_headings("export")[0], "## export.R1: With code")

    def test_ac6_heading_after_code_block_is_a_new_change(self) -> None:
        text = "Example:\n\n```\n## inside\n```"
        self.delta("p1", added("export.R1", "One", text), added("export.R2", "Two"))
        self.apply("p1")
        spec = self.read(f"{SPECS}/export.md")
        self.assertIn("## export.R2: Two", spec)
        self.assertIn("## inside", spec)

    # AC7: CLI

    def test_ac7_cli_success_returns_0_and_lists_changed_files(self) -> None:
        self.delta("p1", added("export.R1"), added("login.R1"))
        code, output = self.run_cli("p1")
        self.assertEqual(code, 0)
        for path in (f"{PLANS}/p1.spec.md", f"{SPECS}/export.md", f"{SPECS}/login.md"):
            self.assertIn(path, output)

    def test_ac7_cli_lists_a_deleted_spec(self) -> None:
        self.delta("p1", added("export.R1"), added("login.R1"))
        self.apply("p1")
        self.delta("p2", removed("export.R1"))
        code, output = self.run_cli("p2")
        self.assertEqual(code, 0)
        self.assertIn(f"{SPECS}/export.md", output)

    def test_ac7_cli_does_not_list_unchanged_specs(self) -> None:
        self.delta("p1", added("export.R1"), added("login.R1"))
        self.apply("p1")
        self.delta("p2", added("export.R2"))
        code, output = self.run_cli("p2")
        self.assertEqual(code, 0)
        self.assertNotIn("login.md", output)

    def test_ac7_cli_failure_returns_1_with_the_message(self) -> None:
        code, output = self.run_cli("missing")
        self.assertEqual(code, 1)
        self.assertIn("missing", output)

    # Edge 1: each scenario needs a WHEN line and a THEN line

    def requirement(self, *scenarios: str, req_id: str = "export.R1") -> str:
        return f"## ADDED {req_id}: Title\n\nThe user MUST do it.\n\n" + "\n".join(scenarios)

    def test_edge1_scenario_with_when_but_no_then_is_refused(self) -> None:
        self.delta("p1", self.requirement("### Scenario: half\n- WHEN the user does it\n"))
        self.assert_refused("p1", "export.R1")

    def test_edge1_scenario_with_then_but_no_when_is_refused(self) -> None:
        self.delta("p1", self.requirement("### Scenario: half\n- THEN it is done\n"))
        self.assert_refused("p1", "export.R1")

    def test_edge1_good_scenario_then_empty_scenario_is_refused(self) -> None:
        self.delta("p1", self.requirement("### Scenario: good\n- WHEN a\n- THEN b\n",
                                          "### Scenario: empty\n"))
        self.assert_refused("p1", "export.R1")

    def test_edge1_good_scenario_then_half_scenario_is_refused(self) -> None:
        self.delta("p1", self.requirement("### Scenario: good\n- WHEN a\n- THEN b\n",
                                          "### Scenario: half\n- WHEN c\n"))
        self.assert_refused("p1", "export.R1")

    def test_edge1_modified_with_a_half_scenario_is_refused(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.delta("p2", "## MODIFIED export.R1: New\n\nNew text.\n\n"
                         "### Scenario: half\n- WHEN a\n")
        self.assert_refused("p2", "export.R1")

    def test_edge1_two_good_scenarios_are_accepted(self) -> None:
        self.delta("p1", self.requirement("### Scenario: one\n- WHEN a\n- THEN b\n",
                                          "### Scenario: two\n- WHEN c\n- THEN d\n"))
        self.apply("p1")
        self.assertEqual(self.requirement_headings("export"), ["## export.R1: Title"])

    # Edge 2: a code fence hides scenarios and `## ` lines

    def test_edge2_scenario_in_a_backtick_fence_does_not_count(self) -> None:
        self.delta("p1", self.requirement(
            "Example:\n\n```markdown\n### Scenario: fake\n- WHEN a\n- THEN b\n```\n"))
        self.assert_refused("p1", "export.R1")

    def test_edge2_scenario_in_a_tilde_fence_does_not_count(self) -> None:
        self.delta("p1", self.requirement(
            "Example:\n\n~~~markdown\n### Scenario: fake\n- WHEN a\n- THEN b\n~~~\n"))
        self.assert_refused("p1", "export.R1")

    def test_edge2_half_scenario_in_a_fence_does_not_refuse_a_good_requirement(self) -> None:
        self.delta("p1", self.requirement("### Scenario: real\n- WHEN a\n- THEN b\n",
                                          "```\n### Scenario: example\n- WHEN only\n```\n"))
        self.apply("p1")
        self.assertIn("### Scenario: example", self.read(f"{SPECS}/export.md"))

    def test_edge2_fenced_when_and_then_do_not_fill_a_real_scenario(self) -> None:
        self.delta("p1", self.requirement("### Scenario: real\n- WHEN a\n\n```\n- THEN b\n```\n"))
        self.assert_refused("p1", "export.R1")

    def test_edge2_heading_in_a_tilde_fence_is_body(self) -> None:
        text = ("Example:\n\n~~~markdown\n## Not a change\n"
                "## ADDED other.R1: Not a change\n~~~")
        self.delta("p1", added("export.R1", "With code", text))
        self.apply("p1")
        spec = self.read(f"{SPECS}/export.md")
        self.assertIn("## ADDED other.R1: Not a change", spec)
        self.assertFalse((self.root / SPECS / "other.md").exists())
        self.assertEqual(self.requirement_headings("export")[0], "## export.R1: With code")

    def test_edge2_backtick_line_in_a_tilde_fence_does_not_end_the_fence(self) -> None:
        # In Markdown, a ~~~ fence ends only at a ~~~ line. A ``` line in it is text.
        text = ("Example:\n\n~~~markdown\n```\n## ADDED other.R1: Not a change\n"
                "```\n~~~")
        self.delta("p1", added("export.R1", "With code", text))
        self.apply("p1")
        self.assertFalse((self.root / SPECS / "other.md").exists())
        self.assertIn("## ADDED other.R1: Not a change", self.read(f"{SPECS}/export.md"))

    # Edge 3: a #### heading does not end a scenario

    def test_edge3_level_4_heading_in_a_scenario_keeps_the_scenario(self) -> None:
        self.delta("p1", self.requirement(
            "### Scenario: with a note\n- WHEN a\n\n#### Note\n\nSome text.\n\n- THEN b\n"))
        self.apply("p1")
        self.assertIn("#### Note", self.read(f"{SPECS}/export.md"))

    def test_edge3_level_4_heading_does_not_hide_a_missing_then(self) -> None:
        self.delta("p1", self.requirement("### Scenario: s\n- WHEN a\n\n#### Note\n\nText.\n"))
        self.assert_refused("p1", "export.R1")

    def test_edge3_level_3_heading_ends_the_scenario(self) -> None:
        # A THEN line after a `### ` heading is not in the scenario.
        self.delta("p1", self.requirement("### Scenario: s\n- WHEN a\n\n### Notes\n\n- THEN b\n"))
        self.assert_refused("p1", "export.R1")

    # Edge 4: bad YAML is an error with exit 1, not a traceback

    def test_edge4_bad_yaml_in_the_delta_frontmatter(self) -> None:
        for front in ("apply_order: [1", "plan: p1\n  bad: : indent", "key: \"open"):
            with self.subTest(front=front):
                self.delta("p1", added("export.R1"), front=front)
                self.assert_refused("p1", "p1.spec.md")

    def test_edge4_frontmatter_that_is_not_a_mapping(self) -> None:
        for front in ("- a\n- b", "just text", "42"):
            with self.subTest(front=front):
                self.delta("p1", added("export.R1"), front=front)
                self.assert_refused("p1", "p1.spec.md")

    def test_edge4_bad_yaml_in_another_delta_stops_apply(self) -> None:
        self.delta("good", added("export.R1"))
        self.delta("other", added("login.R1"), front="apply_order: [1")
        self.assert_refused("good", "other.spec.md")

    def test_edge4_list_frontmatter_in_another_delta_stops_apply(self) -> None:
        self.delta("good", added("export.R1"))
        self.delta("other", added("login.R1"), front="- a\n- b")
        self.assert_refused("good", "other.spec.md")

    def test_edge4_bad_yaml_in_the_config(self) -> None:
        self.write(".cornerstone/config.yaml", "paths:\n  plans: [docs/plans\n")
        self.delta("p1", added("export.R1"))
        self.assert_refused("p1", "config.yaml")

    def test_edge4_cli_prints_no_traceback(self) -> None:
        self.write(".cornerstone/config.yaml", "paths: {plans: \n")
        self.delta("p1", added("export.R1"), front="apply_order: [1")
        err = io.StringIO()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["spec", "apply", "p1", "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", out.getvalue() + err.getvalue())
        self.assertIn("stone spec apply:", out.getvalue())

    # Edge 5: a path outside the repo stops apply before it writes

    def nested_repo(self) -> Path:
        """Move the repo root one level down, so that '../outside/' stays in the temp folder."""
        outer = self.root
        self.root = outer / "repo"
        self.root.mkdir()
        return outer

    def test_edge5_specs_path_outside_the_repo_writes_nothing(self) -> None:
        outer = self.nested_repo()
        for value in ("../outside/", "../repo-specs/", "docs/../../outside/"):
            with self.subTest(value=value):
                self.write(".cornerstone/config.yaml", f"paths:\n  specs: {value}\n")
                delta = self.delta("p1", added("export.R1"))
                before = delta.read_text(encoding="utf-8")
                self.assert_refused("p1", "paths.specs")
                self.assertEqual(delta.read_text(encoding="utf-8"), before,
                                 "the delta was marked as applied")
                self.assertEqual([p.name for p in outer.iterdir()], ["repo"])

    def test_edge5_absolute_specs_path_outside_the_repo_writes_nothing(self) -> None:
        outer = self.nested_repo()
        self.write(".cornerstone/config.yaml", f"paths:\n  specs: {outer / 'outside'}\n")
        self.delta("p1", added("export.R1"))
        self.assert_refused("p1", "paths.specs")
        self.assertFalse((outer / "outside").exists())

    def test_edge5_plans_path_outside_the_repo_writes_nothing(self) -> None:
        outer = self.nested_repo()
        self.write(".cornerstone/config.yaml", "paths:\n  plans: ../outside/\n")
        delta = outer / "outside" / "p1.spec.md"
        delta.parent.mkdir()
        delta.write_text(added("export.R1"), encoding="utf-8")
        self.assert_refused("p1", "paths.plans")
        self.assertEqual(delta.read_text(encoding="utf-8"), added("export.R1"))
        self.assertEqual(sorted(p.name for p in (outer / "outside").iterdir()), ["p1.spec.md"])
        self.assertFalse((self.root / SPECS).exists())

    def test_edge5_path_that_stays_in_the_repo_is_accepted(self) -> None:
        self.nested_repo()
        self.write(".cornerstone/config.yaml", "paths:\n  specs: docs/../product/specs/\n")
        self.delta("p1", added("export.R1"))
        changed = self.apply("p1")
        self.assertEqual(sorted(changed), [f"{PLANS}/p1.spec.md", "product/specs/export.md"])

    # Part 2. Helpers for `stone spec sync` and check K19

    def sync(self) -> list[str]:
        return specs.sync(self.root)

    def run_sync_cli(self) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["spec", "sync", "--root", str(self.root)])
        return code, out.getvalue(), err.getvalue()

    def assert_sync_refused(self, fragment: str | None = None) -> str:
        """Sync must raise SpecError, write no file, and the CLI must return 1."""
        before = self.snapshot()
        with self.assertRaises(specs.SpecError) as caught:
            self.sync()
        self.assertEqual(self.snapshot(), before, "sync wrote a file on an error")
        code, output, _ = self.run_sync_cli()
        self.assertEqual(code, 1)
        self.assertIn(str(caught.exception), output)
        self.assertEqual(self.snapshot(), before, "the CLI sync wrote a file on an error")
        if fragment is not None:
            self.assertIn(fragment, str(caught.exception))
        return str(caught.exception)

    def k19(self) -> list:
        return specs.check(self.root)

    def k19_paths(self) -> list[str]:
        return sorted(finding.path for finding in self.k19())

    def assert_all_warnings(self, findings: list) -> None:
        self.assertTrue(findings, "K19 found nothing")
        for finding in findings:
            self.assertEqual(finding.check, "K19")
            self.assertEqual(finding.severity, "warning")

    def line_of(self, path: Path, start: str) -> int:
        lines = path.read_text(encoding="utf-8").splitlines()
        return next(n for n, line in enumerate(lines, 1) if line.startswith(start))

    def tie_after_merge(self) -> None:
        """Two branches applied a delta from order 1. Both merged. The specs are from one branch."""
        self.delta("base", added("export.R1"), front="apply_order: 1")
        self.delta("left", added("export.R2", "Left"), front="apply_order: 2")
        self.delta("right", added("login.R1", "Right"), front="apply_order: 2")
        self.write(f"{SPECS}/export.md", "stale text from one branch\n")

    # Part 2, AC1: a tie stops apply, and the message names `stone spec sync`

    def test_p2_ac1_tie_after_a_merge_stops_apply(self) -> None:
        self.tie_after_merge()
        self.delta("next", added("export.R3"))
        message = self.assert_refused("next", "stone spec sync")
        self.assertIn("left.spec.md", message)
        self.assertIn("right.spec.md", message)

    def test_p2_ac1_tie_with_specs_that_equal_the_replay_still_stops_apply(self) -> None:
        self.delta("a", added("export.R1"), front="apply_order: 1")
        self.delta("b", added("login.R1"), front="apply_order: 1")
        for name, text in specs.render_specs(
                specs.replay(specs.applied(specs.load_deltas(self.root)))).items():
            self.write(f"{SPECS}/{name}", text)
        self.delta("c", added("export.R2"))
        self.assert_refused("c", "stone spec sync")

    def test_p2_ac1_tie_of_three_deltas_stops_apply(self) -> None:
        for plan, req in (("a", "export.R1"), ("b", "login.R1"), ("c", "admin.R1")):
            self.delta(plan, added(req), front="apply_order: 4")
        self.delta("d", added("export.R2"))
        message = self.assert_refused("d", "stone spec sync")
        for name in ("a.spec.md", "b.spec.md", "c.spec.md"):
            self.assertIn(name, message)

    def test_p2_ac1_no_tie_after_apply_then_sync_then_apply(self) -> None:
        self.tie_after_merge()
        self.sync()
        self.delta("next", added("export.R3"))
        self.apply("next")
        self.assertEqual(self.meta(f"{PLANS}/next.spec.md")["apply_order"], 4)

    # Part 2, AC2: `stone spec sync`

    def test_p2_ac2_sync_gives_orders_1_to_n_in_replay_order(self) -> None:
        # Replay order is (order, plan ID): a(3) < x(3) < m(7) < b(9).
        self.delta("x", added("login.R1"), front="apply_order: 3")
        self.delta("a", added("export.R1"), front="apply_order: 3")
        self.delta("m", modified("export.R1"), front="apply_order: 7")
        self.delta("b", added("admin.R1"), front="apply_order: 9")
        self.sync()
        orders = {plan: self.meta(f"{PLANS}/{plan}.spec.md")["apply_order"]
                  for plan in ("a", "x", "m", "b")}
        self.assertEqual(orders, {"a": 1, "x": 2, "m": 3, "b": 4})

    def test_p2_ac2_sync_keeps_apply_order_before_plan_id(self) -> None:
        # "z" adds R1 and "a" modifies it. A sort by plan ID only would break the replay.
        self.delta("z", added("export.R1", "Old"), front="apply_order: 5")
        self.delta("a", modified("export.R1", "New"), front="apply_order: 8")
        self.sync()
        self.assertEqual(self.meta(f"{PLANS}/z.spec.md")["apply_order"], 1)
        self.assertEqual(self.meta(f"{PLANS}/a.spec.md")["apply_order"], 2)
        self.assertEqual(self.requirement_headings("export"), ["## export.R1: New"])

    def test_p2_ac2_sync_after_a_merge_gives_a_valid_history(self) -> None:
        self.tie_after_merge()
        changed = self.sync()
        self.assertEqual(self.meta(f"{PLANS}/base.spec.md")["apply_order"], 1)
        self.assertEqual(self.meta(f"{PLANS}/left.spec.md")["apply_order"], 2)
        self.assertEqual(self.meta(f"{PLANS}/right.spec.md")["apply_order"], 3)
        self.assertIn(f"{PLANS}/right.spec.md", changed)
        self.assertNotIn(f"{PLANS}/base.spec.md", changed)
        self.assertNotIn(f"{PLANS}/left.spec.md", changed)
        self.assertEqual(self.requirement_headings("export"),
                         ["## export.R1: A title", "## export.R2: Left"])
        self.assertEqual(self.requirement_headings("login"), ["## login.R1: Right"])

    def test_p2_ac2_sync_keeps_the_other_frontmatter_keys_and_the_body(self) -> None:
        body = added("export.R1")
        path = self.delta("p1", body, front="plan: p1\napply_order: 4\nowner: octocat\n"
                                            "tags: [a, b]")
        self.sync()
        self.assertEqual(self.meta(f"{PLANS}/p1.spec.md"),
                         {"apply_order": 1, "plan": "p1", "owner": "octocat", "tags": ["a", "b"]})
        self.assertTrue(path.read_text(encoding="utf-8").endswith(body))

    def test_p2_ac2_sync_does_not_touch_an_unapplied_delta(self) -> None:
        self.delta("p1", added("export.R1"), front="apply_order: 3")
        draft = self.delta("draft", added("export.R2"), front="plan: draft")
        bare = self.delta("bare", added("login.R1"))
        before = (draft.read_text(encoding="utf-8"), bare.read_text(encoding="utf-8"))
        changed = self.sync()
        self.assertEqual((draft.read_text(encoding="utf-8"), bare.read_text(encoding="utf-8")),
                         before)
        self.assertNotIn(f"{PLANS}/draft.spec.md", changed)
        self.assertNotIn(f"{PLANS}/bare.spec.md", changed)
        # The unapplied deltas are not in the specs.
        self.assertEqual(self.requirement_headings("export"), ["## export.R1: A title"])
        self.assertFalse((self.root / SPECS / "login.md").exists())

    def test_p2_ac2_sync_writes_the_specs_when_the_folder_is_missing(self) -> None:
        self.delta("p1", added("export.R1"), added("login.R1"), front="apply_order: 1")
        changed = self.sync()
        self.assertEqual(sorted(changed), [f"{SPECS}/export.md", f"{SPECS}/login.md"])
        self.assertEqual(self.read(f"{SPECS}/export.md"), self._replay_text())

    def test_p2_ac2_sync_overwrites_a_hand_edit(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        expected = self.read(f"{SPECS}/export.md")
        self.write(f"{SPECS}/export.md", expected + "\nA hand edit.\n")
        self.assertEqual(self.sync(), [f"{SPECS}/export.md"])
        self.assertEqual(self.read(f"{SPECS}/export.md"), expected)

    def test_p2_ac2_sync_deletes_an_extra_spec_and_restores_a_missing_spec(self) -> None:
        self.delta("p1", added("export.R1"), added("login.R1"))
        self.apply("p1")
        login = self.read(f"{SPECS}/login.md")
        (self.root / SPECS / "login.md").unlink()
        self.write(f"{SPECS}/extra.md", "# extra\n")
        changed = self.sync()
        self.assertEqual(sorted(changed), [f"{SPECS}/extra.md", f"{SPECS}/login.md"])
        self.assertFalse((self.root / SPECS / "extra.md").exists())
        self.assertEqual(self.read(f"{SPECS}/login.md"), login)

    def test_p2_ac2_sync_after_a_deleted_applied_delta_follows_the_replay(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.delta("p2", added("login.R1"))
        self.apply("p2")
        (self.root / PLANS / "p1.spec.md").unlink()
        changed = self.sync()
        self.assertIn(f"{SPECS}/export.md", changed)
        self.assertIn(f"{PLANS}/p2.spec.md", changed)
        self.assertFalse((self.root / SPECS / "export.md").exists())
        self.assertEqual(self.meta(f"{PLANS}/p2.spec.md")["apply_order"], 1)

    def test_p2_ac2_second_sync_changes_no_file(self) -> None:
        self.tie_after_merge()
        self.delta("draft", added("export.R9"))
        self.sync()
        before = self.snapshot()
        self.assertEqual(self.sync(), [])
        self.assertEqual(self.snapshot(), before)

    def test_p2_ac2_sync_on_a_repo_in_order_changes_no_file(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.delta("p2", added("login.R1"))
        self.apply("p2")
        before = self.snapshot()
        self.assertEqual(self.sync(), [])
        self.assertEqual(self.snapshot(), before)

    def test_p2_ac2_sync_on_an_empty_repo_writes_no_file(self) -> None:
        self.assertEqual(self.sync(), [])
        self.assertEqual(self.snapshot(), {})

    def test_p2_ac2_sync_refuses_on_a_format_error_in_an_applied_delta(self) -> None:
        self.tie_after_merge()
        self.delta("bad", "## CHANGED export.R5: Bad op\n\n### Scenario: s\n- WHEN a\n- THEN b\n",
                   front="apply_order: 2")
        self.assert_sync_refused("bad.spec.md")

    def test_p2_ac2_sync_refuses_on_a_format_error_in_an_unapplied_delta(self) -> None:
        self.tie_after_merge()
        self.delta("draft", "## ADDED bad id: Title\n\n### Scenario: s\n- WHEN a\n- THEN b\n")
        self.assert_sync_refused("draft.spec.md")

    def test_p2_ac2_sync_refuses_on_a_bad_apply_order(self) -> None:
        self.tie_after_merge()
        self.delta("bad", added("admin.R1"), front="apply_order: 0")
        self.assert_sync_refused("bad.spec.md")

    def test_p2_ac2_sync_refuses_on_a_replay_conflict(self) -> None:
        # Two branches each added export.R2. After the merge, the replay adds it two times.
        self.delta("base", added("export.R1"), front="apply_order: 1")
        self.delta("left", added("export.R2", "Left"), front="apply_order: 2")
        self.delta("right", added("export.R2", "Right"), front="apply_order: 2")
        self.write(f"{SPECS}/export.md", "stale\n")
        self.assert_sync_refused("export.R2")

    def test_p2_ac2_sync_refuses_a_specs_path_outside_the_repo(self) -> None:
        outer = self.nested_repo()
        self.write(".cornerstone/config.yaml", "paths:\n  specs: ../outside/\n")
        self.delta("p1", added("export.R1"), front="apply_order: 2")
        self.assert_sync_refused("paths.specs")
        self.assertEqual([p.name for p in outer.iterdir()], ["repo"])

    def test_p2_ac2_sync_uses_the_config_paths(self) -> None:
        self.write(".cornerstone/config.yaml",
                   "paths:\n  plans: work/plans/\n  specs: product/specs/\n")
        self.delta("p1", added("export.R1"), front="apply_order: 5", folder="work/plans")
        changed = self.sync()
        self.assertEqual(sorted(changed), ["product/specs/export.md", "work/plans/p1.spec.md"])
        self.assertFalse((self.root / SPECS).exists())

    # Part 2, AC3: check K19

    def test_p2_ac3_no_finding_with_no_delta_and_no_specs_folder(self) -> None:
        self.assertEqual(self.k19(), [])

    def test_p2_ac3_no_finding_after_apply(self) -> None:
        self.delta("p1", added("export.R1"), added("login.R1"))
        self.apply("p1")
        self.delta("p2", modified("export.R1"), removed("login.R1"))
        self.apply("p2")
        self.delta("draft", added("export.R2"))
        self.assertEqual(self.k19(), [])

    def test_p2_ac3_format_error_is_a_warning_with_its_line(self) -> None:
        path = self.delta("p1", added("export.R1"),
                          "## CHANGED export.R2: Bad op\n\n### Scenario: s\n- WHEN a\n- THEN b\n",
                          front="plan: p1")
        findings = self.k19()
        self.assert_all_warnings(findings)
        self.assertEqual([(f.path, f.line) for f in findings],
                         [(f"{PLANS}/p1.spec.md", self.line_of(path, "## CHANGED"))])

    def test_p2_ac3_each_format_error_is_a_finding(self) -> None:
        path = self.delta("p1", "## ADDED export.R1: No scenario\n\nText.\n",
                          "## ADDED bad id: Title\n\n### Scenario: s\n- WHEN a\n- THEN b\n")
        self.delta("p2", added("login.R1"), front="apply_order: 0")
        findings = self.k19()
        self.assert_all_warnings(findings)
        self.assertEqual(sorted((f.path, f.line) for f in findings),
                         [(f"{PLANS}/p1.spec.md", self.line_of(path, "## ADDED export.R1")),
                          (f"{PLANS}/p1.spec.md", self.line_of(path, "## ADDED bad id")),
                          (f"{PLANS}/p2.spec.md", 1)])

    def test_p2_ac3_bad_yaml_in_a_delta_is_a_warning(self) -> None:
        self.delta("p1", added("export.R1"), front="apply_order: [1")
        findings = self.k19()
        self.assert_all_warnings(findings)
        self.assertEqual([f.path for f in findings], [f"{PLANS}/p1.spec.md"])

    def test_p2_ac3_each_delta_in_a_tie_is_a_warning(self) -> None:
        self.delta("base", added("export.R1"), front="apply_order: 1")
        self.delta("left", added("export.R2"), front="apply_order: 2")
        self.delta("right", added("login.R1"), front="apply_order: 2")
        for name, text in specs.render_specs(
                specs.replay(specs.applied(specs.load_deltas(self.root)))).items():
            self.write(f"{SPECS}/{name}", text)
        findings = self.k19()
        self.assert_all_warnings(findings)
        self.assertEqual(self.k19_paths(), [f"{PLANS}/left.spec.md", f"{PLANS}/right.spec.md"])
        for finding in findings:
            self.assertIn("stone spec sync", finding.message)

    def test_p2_ac3_tie_of_three_deltas_gives_three_warnings(self) -> None:
        for plan, req in (("a", "export.R1"), ("b", "login.R1"), ("c", "admin.R1")):
            self.delta(plan, added(req), front="apply_order: 1")
        for name, text in specs.render_specs(
                specs.replay(specs.applied(specs.load_deltas(self.root)))).items():
            self.write(f"{SPECS}/{name}", text)
        self.assert_all_warnings(self.k19())
        self.assertEqual(self.k19_paths(),
                         [f"{PLANS}/a.spec.md", f"{PLANS}/b.spec.md", f"{PLANS}/c.spec.md"])

    def test_p2_ac3_replay_conflict_is_a_warning(self) -> None:
        self.delta("base", added("export.R1"), front="apply_order: 1")
        self.delta("left", added("export.R2", "Left"), front="apply_order: 2")
        self.delta("right", added("export.R2", "Right"), front="apply_order: 2")
        findings = self.k19()
        self.assert_all_warnings(findings)
        self.assertTrue(any("export.R2" in f.message for f in findings), findings)

    def test_p2_ac3_conflict_without_a_tie_is_a_warning(self) -> None:
        self.delta("p1", modified("export.R1"), front="apply_order: 1")
        findings = self.k19()
        self.assert_all_warnings(findings)
        self.assertTrue(any("export.R1" in f.message for f in findings), findings)

    def test_p2_ac3_hand_edit_is_a_warning(self) -> None:
        self.delta("p1", added("export.R1"), added("login.R1"))
        self.apply("p1")
        self.write(f"{SPECS}/export.md", self.read(f"{SPECS}/export.md") + "\nA hand edit.\n")
        self.assert_all_warnings(self.k19())
        self.assertEqual(self.k19_paths(), [f"{SPECS}/export.md"])

    def test_p2_ac3_extra_spec_file_is_a_warning(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.write(f"{SPECS}/extra.md", "# extra\n")
        self.assert_all_warnings(self.k19())
        self.assertEqual(self.k19_paths(), [f"{SPECS}/extra.md"])

    def test_p2_ac3_spec_file_with_no_delta_is_a_warning(self) -> None:
        self.write(f"{SPECS}/manual.md", "# manual\n")
        self.assert_all_warnings(self.k19())
        self.assertEqual(self.k19_paths(), [f"{SPECS}/manual.md"])

    def test_p2_ac3_missing_spec_file_is_a_warning(self) -> None:
        self.delta("p1", added("export.R1"), added("login.R1"))
        self.apply("p1")
        (self.root / SPECS / "login.md").unlink()
        self.assert_all_warnings(self.k19())
        self.assertEqual(self.k19_paths(), [f"{SPECS}/login.md"])

    def test_p2_ac3_applied_delta_with_no_specs_folder_is_a_warning(self) -> None:
        self.delta("p1", added("export.R1"), front="apply_order: 1")
        self.assert_all_warnings(self.k19())
        self.assertEqual(self.k19_paths(), [f"{SPECS}/export.md"])

    def test_p2_ac3_deleted_applied_delta_is_a_warning(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.delta("p2", added("login.R1"))
        self.apply("p2")
        (self.root / PLANS / "p1.spec.md").unlink()
        self.assert_all_warnings(self.k19())
        self.assertEqual(self.k19_paths(), [f"{SPECS}/export.md"])

    def test_p2_ac3_config_path_outside_the_repo_is_a_warning(self) -> None:
        self.nested_repo()
        for key in ("specs", "plans"):
            with self.subTest(key=key):
                self.write(".cornerstone/config.yaml", f"paths:\n  {key}: ../outside/\n")
                findings = self.k19()
                self.assert_all_warnings(findings)
                self.assertTrue(any(f"paths.{key}" in f.message for f in findings), findings)

    def test_p2_ac3_after_sync_k19_has_no_finding(self) -> None:
        self.tie_after_merge()
        self.write(f"{SPECS}/extra.md", "# extra\n")
        self.delta("draft", added("admin.R1"))
        self.assertTrue(self.k19())
        self.sync()
        self.assertEqual(self.k19(), [])

    def test_p2_ac3_after_sync_of_a_deleted_delta_k19_has_no_finding(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        self.delta("p2", added("login.R1"))
        self.apply("p2")
        (self.root / PLANS / "p1.spec.md").unlink()
        self.sync()
        self.assertEqual(self.k19(), [])

    def run_stone_check(self) -> tuple[int, str]:
        framework = Path(__file__).resolve().parents[2] / "framework"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["check", "--root", str(self.root), "--framework", str(framework)])
        return code, out.getvalue()

    def test_p2_ac3_stone_check_runs_k19_as_a_warning(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        clean_code, clean_output = self.run_stone_check()
        self.assertNotIn("K19", clean_output)
        self.write(f"{SPECS}/export.md", "A hand edit.\n")
        code, output = self.run_stone_check()
        self.assertIn(f"{SPECS}/export.md:1: warning: K19:", output)
        self.assertEqual(code, clean_code, "a K19 warning changed the exit code")

    def test_p2_ac3_stone_check_has_no_k19_finding_after_sync(self) -> None:
        self.tie_after_merge()
        _, before = self.run_stone_check()
        self.assertIn("K19", before)
        self.sync()
        _, after = self.run_stone_check()
        self.assertNotIn("K19", after)

    # Part 2, AC5: the CLI for `stone spec sync`

    def test_p2_ac5_cli_sync_returns_0_and_lists_the_changed_files(self) -> None:
        self.tie_after_merge()
        code, output, _ = self.run_sync_cli()
        self.assertEqual(code, 0)
        for path in (f"{PLANS}/right.spec.md", f"{SPECS}/export.md", f"{SPECS}/login.md"):
            self.assertIn(f"wrote {path}", output)
        self.assertNotIn(f"{PLANS}/base.spec.md", output)
        self.assertIn("stone spec sync: 3 file(s) changed", output)

    def test_p2_ac5_cli_sync_with_no_change_returns_0(self) -> None:
        self.delta("p1", added("export.R1"))
        self.apply("p1")
        code, output, _ = self.run_sync_cli()
        self.assertEqual(code, 0)
        self.assertNotIn("wrote ", output)
        self.assertIn("stone spec sync: 0 file(s) changed", output)

    def test_p2_ac5_cli_sync_error_returns_1_with_the_message_and_no_traceback(self) -> None:
        self.write(".cornerstone/config.yaml", "paths: {plans: \n")
        code, output, err = self.run_sync_cli()
        self.assertEqual(code, 1)
        self.assertIn("stone spec sync:", output)
        self.assertIn("config.yaml", output)
        self.assertNotIn("Traceback", output + err)

    # Helpers that build the expected spec text through the public replay

    def _replay_text(self) -> str:
        files = specs.render_specs(specs.replay(specs.applied(specs.load_deltas(self.root))))
        return files["export.md"]


if __name__ == "__main__":
    unittest.main()
