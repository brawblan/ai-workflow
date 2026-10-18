"""Custom checks for the role.tester eval. `stone eval` runs this file once for each grader check.

Usage: grade.py <name> --workspace <path> --args <json>. The last line of the output is JSON:
{"pass": true|false, "detail": "..."}. Each grader works on a copy of the workspace.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_RUN = "python -m unittest discover -s tests -t ."
TIMEOUT = 300


def run_tests(workspace: Path, command: str) -> int:
    """Run the test command in the workspace. Return the exit code (-1 on a timeout)."""
    argv = shlex.split(command)
    if argv and argv[0] == "python":
        argv[0] = sys.executable  # the same interpreter as stone
    try:
        return subprocess.run(argv, cwd=workspace, capture_output=True, timeout=TIMEOUT).returncode
    except subprocess.TimeoutExpired:
        return -1


def with_patch(workspace: Path, patch: str, command: str) -> int | str:
    """Apply a patch to a copy of the workspace and run the tests.

    Return the exit code, or a message if the patch does not apply.
    """
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(workspace, copy, symlinks=True)
        applied = subprocess.run(["git", "apply", str(HERE / patch)], cwd=copy,
                                 capture_output=True, text=True)
        if applied.returncode != 0:
            return f"{patch} does not apply: {applied.stderr.strip()}"
        return run_tests(copy, command)


def kills_mutants(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The tests pass on the code, and fail on at least `min` of the mutants."""
    command = args.get("run", DEFAULT_RUN)
    if run_tests(workspace, command) != 0:
        return False, "the tests fail on the code under test"
    killed, alive = [], []
    for mutant in args["mutants"]:
        code = with_patch(workspace, mutant, command)
        if isinstance(code, str):
            return False, code
        (killed if code != 0 else alive).append(Path(mutant).stem)
    minimum = args.get("min", len(args["mutants"]))
    detail = f"killed {len(killed)} of {len(args['mutants'])}"
    return len(killed) >= minimum, detail + (f"; alive: {', '.join(alive)}" if alive else "")


def passes_with_patch(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The tests fail on the code, and pass after the patch (the fix of the planted bug)."""
    command = args.get("run", DEFAULT_RUN)
    if run_tests(workspace, command) == 0:
        return False, "the tests pass on the code with the bug"
    code = with_patch(workspace, args["patch"], command)
    if isinstance(code, str):
        return False, code
    return code == 0, "the tests pass after the fix" if code == 0 else "the tests fail after the fix"


def test_names(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """Each requirement ID (for example `r1`) is a word of a test function name in tests/."""
    names = [name for path in sorted((workspace / "tests").rglob("*.py"))
             for name in re.findall(r"def (test\w*)", path.read_text(encoding="utf-8"))]
    missing = [rid for rid in args["ids"]
               if not any(re.search(rf"(^|_){re.escape(rid.lower())}(_|$)", name.lower())
                          for name in names)]
    return not missing, f"no test name has {', '.join(missing)}" if missing else "all IDs found"


GRADERS = {"kills_mutants": kills_mutants, "passes_with_patch": passes_with_patch,
           "test_names": test_names}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=sorted(GRADERS))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--args", default="{}")
    options = parser.parse_args()
    passed, detail = GRADERS[options.name](options.workspace, json.loads(options.args))
    print(json.dumps({"pass": passed, "detail": detail}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
