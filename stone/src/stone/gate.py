"""`stone gate`: run G3 on this machine (K6, K7, K20, and `commands.all_checks`) for delivery: local."""

from __future__ import annotations

import datetime as dt
import re
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
SHELL_STATE = {"cd", "pushd", "popd", "export", "source", ".", "set", "unset", "alias", "eval", "exec",
               "nvm", "ulimit", "umask", "trap", "shopt", "declare", "typeset", "local", "readonly",
               "[[", "[", "test"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")  # NAME=value, alone or before a command
TOKEN = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"|\\.|&&|[|;&()`#\n]|[^'\"\\&|;()`#\n]+")
OPERATOR = re.compile(r"[|;&()`#\n]")


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


def split_commands(command: str) -> list[str]:
    """Return the commands that a top-level '&&' joins, or [command] if a split can change the result.

    A command splits only if '&&' is its only shell operator, outside quotes. A command that changes
    the shell state, such as `cd` or `export`, does not split: the next command needs that state.
    """
    tokens = TOKEN.findall(command)
    if "".join(tokens) != command or any(OPERATOR.fullmatch(token) for token in tokens):
        return [command]  # a quote with no end, or an operator such as || ; | & ( ` #
    parts = [part.strip() for part in "".join(
        "\0" if token == "&&" else token for token in tokens).split("\0")]
    if len(parts) == 1 or not all(parts) or any(
            part.split()[0] in SHELL_STATE or ASSIGNMENT.match(part) for part in parts):
        return [command]
    return parts


def check_steps(all_checks: str, split: bool) -> list[Step]:
    """Return one step for `commands.all_checks`, or with split one step for each command."""
    commands = split_commands(all_checks) if split else [all_checks]
    if len(commands) == 1:
        if split:
            print("warning: commands.all_checks does not split into commands that '&&' joins. "
                  "It runs as one command.", file=sys.stderr)
        return [Step("All checks", all_checks)]
    return [Step(f"All checks: `{command}`", command) for command in commands]


def plan(root: Path, config: dict[str, Any], base: str, body: Path | None,
         labels: list[str] | None = None, split_checks: bool = False) -> list[Step]:
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
    return steps + check_steps(all_checks, split_checks)


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
        today: dt.date | None = None, labels: list[str] | None = None,
        split_checks: bool = False) -> tuple[list[Step], str]:
    config = load_config(root)
    base = base or default_base(config)
    steps = plan(root, config, base, body, labels, split_checks)
    for step in steps:
        if not step.skipped:
            run_step(root, step)
    head = _git(root, "rev-parse", "--short", "HEAD")
    return steps, evidence(steps, base, head, today or dt.date.today())
