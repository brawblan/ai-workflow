"""`stone gate`: run G3 on this machine (K6, K7, K20, and `commands.all_checks`) for delivery: local."""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from stone import specialists

CONFIG = Path(".cornerstone/config.yaml")
CHECKS = Path(".cornerstone/checks")
K20_MODE = "block"  # the same mode as the K20 step of the G3 workflow. Blocks since 1.4.0 (D80).


class GateError(Exception):
    """An input is not valid. No check ran."""


@dataclass
class Step:
    name: str
    command: list[str] | str
    passed: bool = False
    output: str = ""
    skipped: str = ""  # the reason, if the check did not run

    @property
    def result(self) -> str:
        return f"skipped ({self.skipped})" if self.skipped else "pass" if self.passed else "FAIL"


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else ""


def load_config(root: Path) -> dict[str, Any]:
    path = root / CONFIG
    if not path.exists():
        raise GateError(f"{CONFIG}: no file. Run stone render first.")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def default_base(config: dict[str, Any]) -> str:
    branches = config.get("branches") or {}
    return f"origin/{branches.get('integration') or branches.get('main') or 'main'}"


def plan(root: Path, config: dict[str, Any], base: str, body: Path | None,
         labels: list[str] | None = None) -> list[Step]:
    no_k6 = (config.get("commits") or {}).get("trailers") == "none"
    for script in ("change_size.py",) if no_k6 else ("protected_paths.py", "change_size.py"):
        if not (root / CHECKS / script).exists():
            raise GateError(f"{CHECKS / script}: no file. Run stone render first.")
    all_checks = str((config.get("commands") or {}).get("all_checks") or "").strip()
    if not all_checks:
        raise GateError(f"{CONFIG}: 'commands.all_checks' has no value. Add it.")
    size = [sys.executable, str(CHECKS / "change_size.py"), base, "--mode", "block"]
    if body:
        size += ["--body", str(body)]
    k6 = Step("K6 protected paths", [sys.executable, str(CHECKS / "protected_paths.py"), base])
    if no_k6:
        k6.skipped = "commits.trailers: none"
    steps = [k6, Step("K7 change size", size)]
    if specialists.listed(config):
        k20 = Step("K20 specialist findings",
                   [sys.executable, "-m", "stone", "check-specialists",
                    str(body.resolve()) if body else "-", "--base", base,
                    "--labels", ",".join(labels or []), "--mode", K20_MODE])
        if not body:
            k20.skipped = "no --body"
        steps.append(k20)
    return steps + [Step("All checks", all_checks)]


def run_step(root: Path, step: Step) -> None:
    done = subprocess.run(step.command, cwd=root, capture_output=True, text=True,
                          shell=isinstance(step.command, str))
    step.passed = done.returncode == 0
    step.output = (done.stdout + done.stderr).strip()


def evidence(steps: list[Step], base: str, head: str, today: dt.date) -> str:
    """Return the G3 evidence as Markdown, for the Evidence section of the PR."""
    lines = [f"G3 on the developer machine (delivery: local), {today.isoformat()}.",
             f"Base `{base}`, head `{head or 'unknown'}`.", "",
             "| Check | Result |", "| --- | --- |"]
    lines += [f"| {step.name} | {step.result} |" for step in steps]
    for step in steps:
        if not (step.passed or step.skipped) and step.output:
            lines += ["", f"{step.name}:", "", "```", *step.output.splitlines()[-30:], "```"]
    return "\n".join(lines)


def run(root: Path, base: str | None = None, body: Path | None = None,
        today: dt.date | None = None, labels: list[str] | None = None) -> tuple[list[Step], str]:
    config = load_config(root)
    base = base or default_base(config)
    steps = plan(root, config, base, body, labels)
    for step in steps:
        if not step.skipped:
            run_step(root, step)
    head = _git(root, "rev-parse", "--short", "HEAD")
    return steps, evidence(steps, base, head, today or dt.date.today())
