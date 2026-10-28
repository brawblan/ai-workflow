"""Custom checks for the role.implementer eval. `stone eval` runs this file once for each grader check.

Usage: grade.py <name> --workspace <path> --args <json>. The last line of the output is JSON:
{"pass": true|false, "detail": "..."}. The final text of the run is in STONE_EVAL_REPORT.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPORT_ENV = "STONE_EVAL_REPORT"
HERE = Path(__file__).resolve().parent
SETUP = "^feat: the change under test"  # the subject of the last setup commit (evals.prepare)
OPTION = re.compile(r"\b(options?|alternatives?|instead|considered|rejected|vs)\b", re.I)
REASON = re.compile(r"\b(reasons?|because|why|so that|rationale|since)\b", re.I)


def _git(workspace: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=workspace, capture_output=True, text=True,
                          check=True).stdout


def acceptance(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The hidden test `test` passes on a copy of the workspace. The run never sees the test."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(workspace, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        (copy / "tests").mkdir(exist_ok=True)
        (copy / "tests" / "__init__.py").touch()
        shutil.copyfile(HERE / args["test"], copy / "tests" / "test_eval_acceptance.py")
        result = subprocess.run([sys.executable, "-m", "unittest", "tests.test_eval_acceptance"],
                                cwd=copy, capture_output=True, text=True, timeout=120)
    lines = result.stderr.strip().splitlines()
    return result.returncode == 0, lines[-1] if lines else f"exit code {result.returncode}"


def _methods(source: str, name: str) -> dict[str, str]:
    """Return each item in the body of class `name`, as a dump of its syntax tree."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return {getattr(item, "name", f"<item {n}>"): ast.dump(item)
                    for n, item in enumerate(node.body)}
    return {}


def scope(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """Class `class` in `path` adds only the methods in `added`. The other items are as they
    were at the end of the setup. Comments are not in the tree, so a comment change passes."""
    setup = _git(workspace, "log", "--format=%H", "-n1", f"--grep={SETUP}").strip()
    before = _methods(_git(workspace, "show", f"{setup}:{args['path']}"), args["class"])
    target = workspace / args["path"]
    if not target.is_file():
        return False, f"no file {args['path']}"
    after = _methods(target.read_text(encoding="utf-8"), args["class"])
    extra = sorted(set(after) - set(before) - set(args["added"]))
    changed = sorted(n for n in before if after.get(n) != before[n])
    missing = sorted(set(args["added"]) - set(after))
    problems = ([f"not asked for: {', '.join(extra)}"] if extra else []) + (
        [f"changed: {', '.join(changed)}"] if changed else []) + (
        [f"not added: {', '.join(missing)}"] if missing else [])
    return not problems, "; ".join(problems) or "only " + ", ".join(args["added"]) + " added"


def names(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The report, or a file under one of `paths`, matches `pattern`."""
    pattern = re.compile(args["pattern"], re.I)
    if pattern.search(os.environ.get(REPORT_ENV, "")):
        return True, "the report"
    for folder in args.get("paths", []):
        for path in sorted((workspace / folder).rglob("*")):
            if path.is_file() and pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                return True, str(path.relative_to(workspace))
    return False, "no match in the report or in " + ", ".join(args.get("paths", []))


def decision_log(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The file `path` exists and gives an option and a reason."""
    path = workspace / args["path"]
    if not path.is_file():
        return False, f"no file {args['path']}"
    text = path.read_text(encoding="utf-8", errors="replace")
    missing = [name for name, regex in (("an option", OPTION), ("a reason", REASON))
               if not regex.search(text)]
    return not missing, "no " + " and no ".join(missing) if missing else "option and reason"


GRADERS = {"acceptance": acceptance, "scope": scope, "names": names, "decision_log": decision_log}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=sorted(GRADERS))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--args", default="{}")
    options = parser.parse_args()
    try:
        args = json.loads(options.args)
        if not isinstance(args, dict):
            raise TypeError("--args must be a JSON object")
        passed, detail = GRADERS[options.name](options.workspace, args)
    except (KeyError, TypeError, ValueError, OSError, SyntaxError, re.error,
            subprocess.SubprocessError) as error:  # bad args, or a file that does not parse
        passed, detail = False, f"the grader input is not valid: {error!r}"
    print(json.dumps({"pass": passed, "detail": detail}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
