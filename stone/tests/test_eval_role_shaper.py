"""Tests for the role.shaper eval in evals/role-shaper/. Each case builds a git workspace from the
fixture, applies the `change` diff of a scenario, edits the ticket, and runs grade.py as a
subprocess with the final text of the run in STONE_EVAL_REPORT. No model starts. Each call also
checks that the workspace does not change and that the last output line is JSON."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "evals" / "role-shaper"
GRADE = EVAL / "grade.py"
SCENARIOS = {s["id"]: s for s in
             yaml.safe_load((EVAL / "scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]}
GIT_ENV = {"GIT_AUTHOR_NAME": "tester", "GIT_AUTHOR_EMAIL": "tester@example.com",
           "GIT_COMMITTER_NAME": "tester", "GIT_COMMITTER_EMAIL": "tester@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
FORM = ("## Definition of Ready\nProblem: A writer wants to remove a note.\n"
        "Acceptance criteria:\n- Notes.delete(number) removes the note.\n"
        "Non-goals: No undo.\nTest oracle: A unit test compares Notes.list().\nPersonas: writer\n")
OPTIONS = "\n   a) writer\n   b) none"


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV})
    assert done.returncode == 0, f"git {args}: {done.stderr}"
    return done.stdout


def snapshot(ws: Path) -> dict[str, str]:
    return {p.relative_to(ws).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ws.rglob("*")) if p.is_file() and ".git" not in p.relative_to(ws).parts}


def check_args(sid: str, name: str, **override: Any) -> dict[str, Any]:
    item = next(i for i in SCENARIOS[sid]["expect"] if i.get("name") == name)
    return {**{k: v for k, v in item.items() if k not in {"check", "kind", "name"}}, **override}


class ShaperCase(unittest.TestCase):
    def workspace(self, sid: str, edit: tuple[str, str, str] | None = None,
                  append: str = "") -> tuple[Path, str]:
        """The fixture with the `change` of scenario `sid` committed on a work branch.
        `edit` is (old, new) text to replace in the ticket; `append` is added at its end."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ws = Path(tmp.name) / "ws"
        shutil.copytree(EVAL / "fixtures" / "notes", ws)
        git(ws, "init", "-q", "-b", "main")
        git(ws, "add", "-A")
        git(ws, "commit", "-q", "-m", "base")
        git(ws, "checkout", "-q", "-b", "feature/eval-work")
        git(ws, "apply", str(EVAL / SCENARIOS[sid]["change"]))
        git(ws, "add", "-A")
        git(ws, "commit", "-q", "-m", "ticket")
        ticket = f"tickets/{git(ws, 'ls-files', 'tickets').split()[0].split('/')[-1]}"
        path = ws / ticket
        if edit:
            text = path.read_text(encoding="utf-8")
            self.assertIn(edit[0], text)
            path.write_text(text.replace(edit[0], edit[1]), encoding="utf-8")
        if append:
            path.write_text(path.read_text(encoding="utf-8") + append, encoding="utf-8")
        return ws, ticket

    def grade(self, name: str, ws: Path, args: dict[str, Any] | str, report: str = "") -> tuple[bool, str]:
        env = {**os.environ, "STONE_EVAL_REPORT": report}
        before = (git(ws, "status", "--porcelain", "--ignored"), snapshot(ws))
        raw = args if isinstance(args, str) else json.dumps(args)
        done = subprocess.run([sys.executable, str(GRADE), name, "--workspace", str(ws),
                               "--args", raw], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual((git(ws, "status", "--porcelain", "--ignored"), snapshot(ws)), before)
        data = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertIsInstance(data["pass"], bool)
        self.assertIsInstance(data["detail"], str)
        return data["pass"], data["detail"]

    def table(self, name: str, sid: str, cases: list[tuple[str, bool, dict[str, Any]]],
              override: dict[str, Any] | None = None) -> None:
        """Each case is (label, expected, {edit, append, report})."""
        for label, expected, kw in cases:
            with self.subTest(label):
                ws, ticket = self.workspace(sid, kw.get("edit"), kw.get("append", ""))
                args = check_args(sid, name, **(override or {}))
                passed, detail = self.grade(name, ws, args, kw.get("report", ""))
                self.assertEqual(passed, expected, detail)

    def test_says_ready(self) -> None:
        self.table("says_ready", "S1", [
            ("ready", True, {"report": "NOTE-1 meets the Definition of Ready. Each field is complete."}),
            ("not ready", False, {"report": "The ticket does not meet the Definition of Ready"}),
            ("no claim", False, {"report": "I looked at the ticket."})])

    def test_not_invented_s2(self) -> None:
        open_dor = ("\n## Definition of Ready\nNon-goals: OPEN (Q4) — not stated by the author\n"
                    "Test oracle: TBD\n")
        self.table("not_invented", "S2", [
            ("no change", True, {}),
            ("placeholders", True, {"append": open_dor}),
            ("non-goals heading", False, {"append": "\n## Non-goals\n- No import from CSV.\n"}),
            ("oracle", False, {"append": "\n**Test oracle:** A unit test compares the CSV file.\n"})])

    def test_not_invented_s5(self) -> None:
        self.table("not_invented", "S5", [
            ("kept", True, {}),
            ("open", True, {"edit": ("Personas: admin", "Personas: OPEN (Q1). admin is not in the personas file")}),
            ("invented", False, {"edit": ("Personas: admin", "Personas: writer")})])

    def test_no_new_match(self) -> None:
        old = "The search is fast."
        self.table("no_new_match", "S3", [
            ("unchanged", True, {}),
            ("invented limit", False, {"edit": (old, "Notes.search() returns in 100 ms or less.")}),
            ("open question", True, {"edit": (old, "Notes.search() returns in 100 ms or less. (Open question: 100 ms?)")})])

    def test_asks_with_options(self) -> None:
        goals, persona = ["non-goal|out of scope"], ["persona"]
        cases = [
            ("list", goals, True, "1. What are the non-goals?\n   a) no import\n   b) no export"),
            ("bold item", persona, True, "6. **Q6 – Personas.** The only persona is `writer`." + OPTIONS),
            ("table", persona, True, "| Personas | Which persona? | writer; none |"),
            ("or", persona, True, "Which persona? Should it be `writer`, or must an `admin` persona be added first?"),
            ("no options", goals, False, "1. What are the non-goals?"),
            ("no question", goals, False, "The ticket needs non-goals.")]
        for label, topics, expected, report in cases:
            with self.subTest(label):
                ws, _ = self.workspace("S2")
                passed, detail = self.grade("asks_with_options", ws, {"topics": topics}, report)
                self.assertEqual(passed, expected, detail)

    def test_dor_form(self) -> None:
        swapped = FORM.replace("Non-goals: No undo.\nTest oracle: A unit test compares Notes.list().\n",
                               "Test oracle: A unit test compares Notes.list().\nNon-goals: No undo.\n")
        self.table("dor_form", "S4", [
            ("full form", True, {"append": "\n" + FORM}),
            ("no section", False, {}),
            ("bold label", False, {"append": "\n" + FORM.replace("Personas:", "**Personas:**")}),
            ("out of order", False, {"append": "\n" + swapped}),
            ("unknown persona", False, {"append": "\n" + FORM.replace("Personas: writer", "Personas: admin")})])


if __name__ == "__main__":
    unittest.main()
