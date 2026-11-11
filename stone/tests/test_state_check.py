"""Tests for K25, the state type with no transition table check (D120), and `stone check-states`."""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from stone import state_check
from stone.cli import main

GIT = ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]

PY3 = "from enum import Enum\n\nclass OrderState(Enum):\n    NEW = 1\n    PAID = 2\n    DONE = 3\n"
PY2 = "from enum import Enum\n\nclass OrderState(Enum):\n    NEW = 1\n    DONE = 2\n"
TS_ENUM = "export enum OrderStatus {\n  New,\n  Paid,\n  Done,\n}\n"
TS_UNION = "export type JobPhase =\n  | 'queued'\n  | 'running'\n  | 'finished';\n"
TABLE = "TRANSITIONS = {'new': ['paid']}\n"


def body(section: str = "") -> str:
    return f"## Summary\n\nA change.\n\n{section}\n## Risks\n\nNone.\n"


WAIVER = "## Waiver (K25)\n\nThe moves are in a database table.\n"


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> None:
        subprocess.run([*GIT, "-C", str(self.root), *args], check=True, capture_output=True)

    def write(self, files: dict[str, str]) -> None:
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def make(self, base: dict[str, str], head: dict[str, str]) -> None:
        self.write({"README.md": "x\n", **base})
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.write(head)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "head")

    def findings(self, head: dict[str, str], text: str = "", base: dict[str, str] | None = None):
        self.make(base or {}, head)
        return state_check.check(self.root, "main", text)


class DetectionTest(RepoCase):
    def test_r1_python_enum_with_3_states_and_no_table_is_found(self) -> None:
        found = self.findings({"order.py": PY3})
        self.assertEqual([(f.path, f.check) for f in found], [("order.py", "K25")])
        self.assertIn("OrderState", found[0].message)

    def test_r1_python_enum_with_2_states_is_not_found(self) -> None:
        self.assertEqual(self.findings({"order.py": PY2}), [])

    def test_r1_typescript_enum_is_found(self) -> None:
        found = self.findings({"order.ts": TS_ENUM})
        self.assertEqual([f.path for f in found], ["order.ts"])
        self.assertIn("OrderStatus", found[0].message)

    def test_r1_typescript_multi_line_string_union_is_found(self) -> None:
        found = self.findings({"job.ts": TS_UNION})
        self.assertEqual([f.path for f in found], ["job.ts"])
        self.assertIn("JobPhase", found[0].message)

    def test_r1_typescript_union_with_2_members_is_not_found(self) -> None:
        self.assertEqual(self.findings({"job.ts": "type JobPhase = 'a' | 'b';\n"}), [])

    def test_r1_name_without_a_state_suffix_is_not_found(self) -> None:
        text = PY3.replace("OrderState", "Color")
        self.assertEqual(self.findings({"color.py": text, "color.ts": TS_ENUM.replace(
            "OrderStatus", "Color")}), [])

    def test_r1_each_suffix_is_found(self) -> None:
        for suffix in ("State", "Status", "Phase", "Stage"):
            with self.subTest(suffix=suffix):
                self.setUp()
                found = self.findings({"m.py": PY3.replace("OrderState", f"Job{suffix}")})
                self.assertEqual(len(found), 1)

    def test_r1_finding_has_the_line_of_the_declaration(self) -> None:
        found = self.findings({"order.py": PY3})
        self.assertEqual(found[0].line, 3)


class TableTest(RepoCase):
    def test_r2_table_in_the_same_file_passes(self) -> None:
        self.assertEqual(self.findings({"order.py": PY3 + TABLE}), [])

    def test_r2_table_in_a_sibling_file_passes(self) -> None:
        self.assertEqual(self.findings({"pkg/order.py": PY3, "pkg/rules.py": TABLE}), [])

    def test_r2_table_in_another_folder_does_not_count(self) -> None:
        found = self.findings({"pkg/order.py": PY3, "other/rules.py": TABLE})
        self.assertEqual([f.path for f in found], ["pkg/order.py"])

    def test_r2_typescript_table_passes(self) -> None:
        text = TS_ENUM + "const transitions = { New: [OrderStatus.Paid] };\n"
        self.assertEqual(self.findings({"order.ts": text}), [])

    def test_r2_css_transition_does_not_count_as_a_table(self) -> None:
        for css in ("el.style.transition: 'all 1s'\n", "x = {transition: 'all 1s'}\n",
                    "transition-duration: 1s\n", "const a = {transition: 0.3}\n"):
            with self.subTest(css=css):
                self.setUp()
                found = self.findings({"order.py": PY3 + css})
                self.assertEqual(len(found), 1)

    def test_r2_next_states_name_counts_as_a_table(self) -> None:
        self.assertEqual(self.findings({"order.py": PY3 + "next_states = {}\n"}), [])


class ScopeTest(RepoCase):
    def test_r3_unchanged_old_enum_is_not_reported(self) -> None:
        found = self.findings({"other.py": "x = 1\n"}, base={"old.py": PY3})
        self.assertEqual(found, [])

    def test_r3_unchanged_enum_in_a_changed_file_is_not_reported(self) -> None:
        found = self.findings({"old.py": PY3 + "y = 2\n"}, base={"old.py": PY3})
        self.assertEqual(found, [])

    def test_r3_new_enum_in_a_changed_file_is_reported(self) -> None:
        new = "class JobStage(Enum):\n    A = 1\n    B = 2\n    C = 3\n"
        found = self.findings({"old.py": PY3 + "\n" + new}, base={"old.py": PY3})
        self.assertEqual(len(found), 1)
        self.assertIn("JobStage", found[0].message)

    def test_r3_all_mode_reads_tracked_files(self) -> None:
        self.make({"old.py": PY3}, {"x.txt": "1\n"})
        self.assertEqual(state_check.check(self.root, "main", ""), [])
        found = state_check.check(self.root, None, "")
        self.assertEqual([f.path for f in found], ["old.py"])

    def test_r4_test_files_and_vendor_folders_are_skipped(self) -> None:
        head = {"test_order.py": PY3, "order_test.py": PY3, "tests/order.py": PY3,
                "node_modules/pkg/index.ts": TS_ENUM, "a.test.ts": TS_ENUM,
                "a.spec.tsx": TS_ENUM, "dist/a.js": TS_ENUM.replace("enum", "type")}
        self.assertEqual(self.findings(head), [])

    def test_r4_non_source_files_are_skipped(self) -> None:
        self.assertEqual(self.findings({"notes.md": PY3}), [])

    def test_r4_bad_base_ref_raises(self) -> None:
        self.make({}, {"order.py": PY3})
        with self.assertRaises(RuntimeError):
            state_check.check(self.root, "no-such-ref", "")


class WaiverTest(RepoCase):
    def test_r5_waiver_with_text_turns_findings_into_warnings(self) -> None:
        found = self.findings({"order.py": PY3}, body(WAIVER))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, "warning")

    def test_r5_no_waiver_keeps_the_severity(self) -> None:
        found = self.findings({"order.py": PY3}, body())
        self.assertNotEqual(found[0].severity, "warning")

    def test_r5_empty_waiver_does_not_count(self) -> None:
        found = self.findings({"order.py": PY3}, body("## Waiver (K25)\n\n"))
        self.assertNotEqual(found[0].severity, "warning")

    def test_r5_has_waiver(self) -> None:
        self.assertTrue(state_check.has_waiver(body(WAIVER)))
        self.assertFalse(state_check.has_waiver(body()))


class CliTest(RepoCase):
    def run_cli(self, argv: list[str], stdin: str) -> tuple[int, str]:
        out = io.StringIO()
        old = os.getcwd()
        os.chdir(self.root)
        try:
            with redirect_stdout(out), mock.patch("sys.stdin", io.StringIO(stdin)):
                code = main(argv)
        finally:
            os.chdir(old)
        return code, out.getvalue()

    def setUp(self) -> None:
        super().setUp()
        self.make({}, {"order.py": PY3})

    def test_r6_warn_mode_exits_0_and_prints_findings(self) -> None:
        code, out = self.run_cli(["check-states", "-", "--base", "main"], body())
        self.assertEqual(code, 0)
        self.assertIn("OrderState", out)
        self.assertIn("K25", out)
        self.assertIn("mode warn", out)

    def test_r6_block_mode_exits_1(self) -> None:
        code, out = self.run_cli(["check-states", "-", "--base", "main", "--mode", "block"], body())
        self.assertEqual(code, 1)
        self.assertIn("mode block", out)

    def test_r6_block_mode_with_a_waiver_exits_0_and_prints_a_notice(self) -> None:
        code, out = self.run_cli(
            ["check-states", "-", "--base", "main", "--mode", "block"], body(WAIVER))
        self.assertEqual(code, 0)
        self.assertIn("Waiver (K25)", out)

    def test_r6_all_mode_reads_tracked_files(self) -> None:
        code, out = self.run_cli(["check-states", "-", "--all", "--mode", "block"], body())
        self.assertEqual(code, 1)
        self.assertIn("order.py", out)

    def test_r6_github_format(self) -> None:
        _, out = self.run_cli(["check-states", "-", "--base", "main", "--format", "github"], body())
        self.assertIn("::warning", out)
        _, out = self.run_cli(["check-states", "-", "--base", "main", "--format", "github",
                               "--mode", "block"], body())
        self.assertIn("::error", out)

    def test_r6_body_file_is_read(self) -> None:
        (self.root / "body.md").write_text(body(WAIVER), encoding="utf-8")
        code, out = self.run_cli(["check-states", "body.md", "--base", "main"], "")
        self.assertEqual(code, 0)
        self.assertIn("notice", out)

    def test_r6_missing_body_file_exits_2(self) -> None:
        code, out = self.run_cli(["check-states", "nope.md", "--base", "main"], "")
        self.assertEqual(code, 2)
        self.assertIn("check-states", out)

    def test_r6_bad_base_ref_exits_2(self) -> None:
        code, _ = self.run_cli(["check-states", "-", "--base", "no-such-ref"], body())
        self.assertEqual(code, 2)

    def test_r6_clean_repo_exits_0_in_block_mode(self) -> None:
        (self.root / "order.py").write_text(PY3 + TABLE, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "table")
        code, out = self.run_cli(["check-states", "-", "--base", "main", "--mode", "block"], body())
        self.assertEqual(code, 0)
        self.assertIn("0 finding", out)


if __name__ == "__main__":
    unittest.main()
