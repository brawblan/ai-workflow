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

    def test_ac4_tie_in_apply_order_is_sorted_by_plan_id(self) -> None:
        self.delta("a", added("export.R1", "From a"), front="apply_order: 1")
        self.delta("b", modified("export.R1", "From b"), front="apply_order: 1")
        self.write(f"{SPECS}/export.md", self._replay_text())
        self.assertIn("From b", self.read(f"{SPECS}/export.md"))
        self.delta("c", added("export.R2"))
        self.apply("c")
        self.assertEqual(self.meta(f"{PLANS}/c.spec.md")["apply_order"], 2)
        self.assertEqual(self.requirement_headings("export"),
                         ["## export.R1: From b", "## export.R2: A title"])

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

    # Helpers that build the expected spec text through the public replay

    def _replay_text(self) -> str:
        files = specs.render_specs(specs.replay(specs.applied(specs.load_deltas(self.root))))
        return files["export.md"]


if __name__ == "__main__":
    unittest.main()
