"""Tests for the role.implementer eval in evals/role-implementer/. Each case builds a workspace
with stone.evals.prepare, edits src/notes.py, and runs grade.py as a subprocess. No model starts."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

from stone import evals

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "evals" / "role-implementer"
DELETE = ("\n    def delete(self, number: int) -> None:\n        if not 1 <= number <= len(self.items):\n"
          "            raise IndexError(number)\n        del self.items[number - 1]\n")
LAST = "\n    def last(self) -> str | None:\n        return self.items[-1] if self.items else None\n"


class ImplementerCase(unittest.TestCase):
    def workspace(self, sid: str) -> Path:
        data = evals.load_scenarios(EVAL)
        scenario = next(s for s in data["scenarios"] if s["id"] == sid)
        ws = evals.prepare(EVAL, scenario, REPO / "framework", "", "with").path
        self.addCleanup(shutil.rmtree, ws.parent, True)
        return ws

    def edit(self, ws: Path, old: str, new: str) -> None:
        path = ws / "src" / "notes.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def append(self, ws: Path, code: str) -> None:
        with (ws / "src" / "notes.py").open("a", encoding="utf-8") as file:
            file.write(code)

    def grade(self, ws: Path, name: str, args: dict[str, Any] | str,
              report: str = "") -> tuple[bool, str]:
        raw = args if isinstance(args, str) else json.dumps(args)
        done = subprocess.run([sys.executable, str(EVAL / "grade.py"), name, "--workspace", str(ws),
                               "--args", raw], capture_output=True, text=True, timeout=120,
                              env={**os.environ, "STONE_EVAL_REPORT": report})
        data = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertIsInstance(data["pass"], bool)
        return data["pass"], data["detail"]


class ScenarioFileTest(unittest.TestCase):
    def test_scenarios_load_with_hidden_tests(self) -> None:
        data = evals.load_scenarios(EVAL)
        self.assertEqual([s["id"] for s in data["scenarios"]], ["I1", "I2", "I3"])
        for scenario in data["scenarios"]:
            tests = [i["test"] for i in scenario["expect"] if i.get("name") == "acceptance"]
            self.assertEqual(len(tests), 1, scenario["id"])
            self.assertTrue((EVAL / tests[0]).is_file(), tests[0])


class AcceptanceTest(ImplementerCase):
    def test_passes_when_code_meets_the_hidden_test(self) -> None:
        ws = self.workspace("I1")
        self.append(ws, DELETE)
        passed, detail = self.grade(ws, "acceptance", {"test": "acceptance/NOTE-21.py"})
        self.assertTrue(passed, detail)

    def test_fails_on_zero_based_delete(self) -> None:
        ws = self.workspace("I1")
        self.append(ws, DELETE.replace("number - 1", "number"))
        self.assertFalse(self.grade(ws, "acceptance", {"test": "acceptance/NOTE-21.py"})[0])

    def test_fails_without_delete(self) -> None:
        ws = self.workspace("I1")
        self.assertFalse(self.grade(ws, "acceptance", {"test": "acceptance/NOTE-21.py"})[0])


class ScopeTest(ImplementerCase):
    ARGS = {"path": "src/notes.py", "class": "Notes", "added": ["last"]}

    def check(self, label: str, expected: bool, ws: Path, fragment: str = "") -> None:
        passed, detail = self.grade(ws, "scope", self.ARGS)
        self.assertEqual(passed, expected, f"{label}: {detail}")
        self.assertIn(fragment, detail)

    def test_only_the_asked_method(self) -> None:
        ws = self.workspace("I2")
        self.append(ws, LAST)
        self.check("added", True, ws, "only last added")

    def test_comment_change_passes(self) -> None:
        ws = self.workspace("I2")
        self.append(ws, LAST)
        self.edit(ws, "# TODO: ignore case", "# TODO: ignore the case of the word")
        self.check("comment", True, ws)

    def test_extra_method_fails(self) -> None:
        ws = self.workspace("I2")
        self.append(ws, LAST + "\n    def clear(self) -> None:\n        self.items.clear()\n")
        self.check("extra", False, ws, "not asked for: clear")

    def test_changed_body_fails(self) -> None:
        ws = self.workspace("I2")
        self.append(ws, LAST)
        self.edit(ws, "if word in text", "if word.lower() in text.lower()")
        self.check("body", False, ws, "changed: find")

    def test_changed_docstring_fails(self) -> None:
        ws = self.workspace("I2")
        self.append(ws, LAST)
        self.edit(ws, "Return the notes that contain the word.", "Find notes.")
        self.check("docstring", False, ws, "changed: find")

    def test_missing_method_fails(self) -> None:
        self.check("missing", False, self.workspace("I2"), "not added: last")


class NamesTest(ImplementerCase):
    ARGS = {"pattern": "keeps.the.text", "paths": ["docs/plans/"]}

    def test_match_in_the_report(self) -> None:
        passed, detail = self.grade(self.workspace("I3"), "names", self.ARGS, "It Keeps The Text.")
        self.assertTrue(passed, detail)

    def test_match_in_a_file(self) -> None:
        ws = self.workspace("I3")
        (ws / "docs" / "plans").mkdir(parents=True)
        (ws / "docs" / "plans" / "NOTE-23.md").write_text("test_add_keeps_x", encoding="utf-8")
        args = {"pattern": "test_add_keeps", "paths": ["docs/plans/"]}
        passed, detail = self.grade(ws, "names", args)
        self.assertTrue(passed, detail)
        self.assertIn("NOTE-23.md", detail)

    def test_no_match_fails(self) -> None:
        ws = self.workspace("I3")
        (ws / "docs" / "plans").mkdir(parents=True)
        (ws / "docs" / "plans" / "a.md").write_text("nothing here", encoding="utf-8")
        self.assertFalse(self.grade(ws, "names", self.ARGS, "other")[0])

    def test_missing_folder_fails_without_crash(self) -> None:
        self.assertFalse(self.grade(self.workspace("I3"), "names", self.ARGS)[0])


class DecisionLogTest(ImplementerCase):
    def log(self, text: str | None) -> tuple[bool, str]:
        ws = self.workspace("I1")
        if text is not None:
            (ws / "docs" / "plans").mkdir(parents=True)
            (ws / "docs" / "plans" / "NOTE-21.decisions.md").write_text(text, encoding="utf-8")
        return self.grade(ws, "decision_log", {"path": "docs/plans/NOTE-21.decisions.md"})

    def test_option_and_reason_pass(self) -> None:
        self.assertTrue(self.log("Option: raise IndexError, because the ticket says so.")[0])

    def test_no_file_fails(self) -> None:
        passed, detail = self.log(None)
        self.assertFalse(passed)
        self.assertIn("no file", detail)

    def test_no_reason_fails(self) -> None:
        passed, detail = self.log("Option: raise IndexError.")
        self.assertFalse(passed)
        self.assertIn("a reason", detail)

    def test_no_option_fails(self) -> None:
        self.assertFalse(self.log("It is done because it works.")[0])


if __name__ == "__main__":
    unittest.main()
