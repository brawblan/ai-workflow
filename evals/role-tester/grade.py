"""Custom checks for the role.tester eval. `stone eval` runs this file once for each grader check.

Usage: grade.py <name> --workspace <path> --args <json>. The last line of the output is JSON:
{"pass": true|false, "detail": "..."}. Each grader runs the unittest suite (`tests`, default
"tests/"; `top`, default ".") in a copy of the workspace, with no bytecode cache.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TIMEOUT = 300
# Runs the unittest suite in the copy and prints {test id: "pass" | "fail" | "skip"} as JSON.
RUNNER = """
import json, sys, unittest
outcomes = {}
class Result(unittest.TestResult):
    def addSuccess(self, test): outcomes.setdefault(test.id(), "pass")
    def addFailure(self, test, err): outcomes[test.id()] = "fail"
    def addError(self, test, err): outcomes[test.id()] = "fail"
    def addSkip(self, test, reason): outcomes[test.id()] = "skip"
    def addExpectedFailure(self, test, err): outcomes[test.id()] = "pass"
    def addUnexpectedSuccess(self, test): outcomes[test.id()] = "fail"
    def addSubTest(self, test, subtest, err):
        if err is not None: outcomes[test.id()] = "fail"
unittest.defaultTestLoader.discover(sys.argv[1], top_level_dir=sys.argv[2]).run(Result())
print("\\n" + json.dumps(outcomes))
"""


class PatchError(Exception):
    """A patch does not apply to the workspace."""


def outcomes(workspace: Path, args: dict[str, Any], patch: str | None = None) -> dict[str, str]:
    """Copy the workspace, apply the patch, and run the tests. Return the outcome of each test.

    A test that does not run (an import error, a timeout) is not in the result.
    """
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(workspace, copy, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if patch:
            applied = subprocess.run(["git", "apply", str(HERE / patch)], cwd=copy,
                                     capture_output=True, text=True)
            if applied.returncode != 0:
                raise PatchError(f"{patch} does not apply: {applied.stderr.strip()}")
        argv = [sys.executable, "-B", "-c", RUNNER, args.get("tests", "tests"),
                args.get("top", ".")]
        try:
            result = subprocess.run(argv, cwd=copy, capture_output=True, text=True,
                                    timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return {}
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def kills_mutants(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """At least `min` mutants (default: all) make a test fail that passes on the code.

    A test that fails on the code is a finding of the tester. It does not fail this check.
    """
    passing = {test for test, result in outcomes(workspace, args).items() if result == "pass"}
    if not passing:
        return False, "no test passes on the code under test"
    killed, alive = [], []
    for mutant in args["mutants"]:
        after = outcomes(workspace, args, mutant)
        (killed if any(after.get(test) != "pass" for test in passing) else alive).append(
            Path(mutant).stem)
    minimum = args.get("min", len(args["mutants"]))
    detail = f"killed {len(killed)} of {len(args['mutants'])}"
    return len(killed) >= minimum, detail + (f"; alive: {', '.join(alive)}" if alive else "")


def passes_with_patch(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """A test fails on the code with the bug, and the same test passes after the fix patch."""
    failing = {test for test, result in outcomes(workspace, args).items() if result == "fail"}
    if not failing:
        return False, "no test fails on the code with the bug"
    after = outcomes(workspace, args, args["patch"])
    found = sorted(test for test in failing if after.get(test) == "pass")
    if not found:
        return False, "no test that fails on the bug passes after the fix"
    return True, f"{len(found)} test(s) fail on the bug and pass after the fix"


def test_names(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """Each requirement ID (for example `r1`) is a word of a test function name in tests/."""
    names = [name for path in sorted((workspace / "tests").rglob("*.py"))
             for name in _test_functions(path)]
    missing = [rid for rid in args["ids"]
               if not any(re.search(rf"(^|_){re.escape(rid.lower())}(_|$)", name.lower())
                          for name in names)]
    return not missing, f"no test name has {', '.join(missing)}" if missing else "all IDs found"


def _test_functions(path: Path) -> list[str]:
    """Return the names of the test functions in a file. A file that does not parse has none."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return []
    return [node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test")]


GRADERS = {"kills_mutants": kills_mutants, "passes_with_patch": passes_with_patch,
           "test_names": test_names}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=sorted(GRADERS))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--args", default="{}")
    options = parser.parse_args()
    try:
        passed, detail = GRADERS[options.name](options.workspace, json.loads(options.args))
    except PatchError as error:
        passed, detail = False, str(error)
    except (KeyError, TypeError, ValueError, OSError) as error:  # bad args or a missing file
        passed, detail = False, f"the grader input is not valid: {error!r}"
    print(json.dumps({"pass": passed, "detail": detail}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
