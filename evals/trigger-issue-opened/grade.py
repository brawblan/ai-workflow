"""Custom checks for the issue-opened trigger eval. The triage form and the post checks are the
same as in the schedule eval, so this file runs the graders of `../trigger-schedule/grade.py`.

Usage: grade.py <name> --workspace <path> --args <json>. See that file for the inputs.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SOURCE = Path(__file__).parent.parent / "trigger-schedule" / "grade.py"
SPEC = importlib.util.spec_from_file_location("schedule_grade", SOURCE)
assert SPEC and SPEC.loader, f"no grader at {SOURCE}"
schedule_grade = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(schedule_grade)

if __name__ == "__main__":
    sys.exit(schedule_grade.main())
