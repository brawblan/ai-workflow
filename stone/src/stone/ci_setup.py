"""`ci.setup` (#162): steps that the G3 job runs before `Install`."""

from __future__ import annotations

import json
import re
from typing import Any

# actions/setup-node v7.1.0. Pinned to a commit SHA.
SETUP_NODE = "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0"
SHA_REF = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
STEP_KEYS = {"name", "uses", "with", "run"}


def problems(config: dict[str, Any]) -> list[str]:
    """Return the problems of the `ci` section of the repo config."""
    section = config.get("ci")
    if section is None:
        return []
    if not isinstance(section, dict):
        return ["'ci' must be a map. Its only key is setup."]
    found = [f"'ci.{key}' is not a key. Use setup." for key in sorted(set(section) - {"setup"})]
    setup = section.get("setup")
    if setup is None:
        return found
    if not isinstance(setup, dict):
        return found + ["'ci.setup' must be a map with the keys node and steps."]
    found += [f"'ci.setup.{key}' is not a key. Use node or steps."
              for key in sorted(set(setup) - {"node", "steps"})]
    node = setup.get("node")
    if "node" in setup and (not isinstance(node, str) or not node.strip()):
        found.append("'ci.setup.node' must be a text, for example \"22\". Put it in quotes.")
    steps = setup.get("steps")
    if "steps" in setup and not isinstance(steps, list):
        return found + ["'ci.setup.steps' must be a list of steps."]
    for number, step in enumerate(steps or [], 1):
        found += _step_problems(number, step)
    return found


def _step_problems(number: int, step: Any) -> list[str]:
    label = f"'ci.setup.steps' item {number}"
    if not isinstance(step, dict):
        return [f"{label} must be a map with 'uses' or 'run'."]
    found = [f"{label} has the key '{key}'. Use name, uses, with, or run."
             for key in sorted(set(step) - STEP_KEYS)]
    if ("uses" in step) == ("run" in step):
        found.append(f"{label} needs one of 'uses' and 'run'.")
    for key in ("name", "uses", "run"):
        if key in step and (not isinstance(step[key], str) or not step[key].strip()):
            found.append(f"{label} needs '{key}' to be a text.")
    if isinstance(step.get("uses"), str) and not SHA_REF.match(step["uses"].strip()):
        found.append(f"{label} has 'uses: {step['uses']}'. Pin the action to a commit SHA "
                     "of 40 characters: owner/repo@<sha>.")
    if "with" in step and (not isinstance(step["with"], dict) or "uses" not in step):
        found.append(f"{label} has 'with' that is not a map, or has no 'uses'.")
    return found


def block(config: dict[str, Any], marker_if: str) -> str:
    """Return the lines of the setup steps. Return "" if the config has none."""
    setup = (config.get("ci") or {}).get("setup") or {}
    guard = f"\n{marker_if}" if marker_if else ""
    steps = []
    if setup.get("node"):
        steps.append(f"      - uses: {SETUP_NODE}{guard}\n        with:\n"
                     f"          node-version: {json.dumps(setup['node'])}\n          cache: npm")
    for step in setup.get("steps") or []:
        steps.append(_step(step, marker_if))
    return "\n".join(steps)


def _step(step: dict[str, Any], marker_if: str) -> str:
    """Return one step as YAML lines. A `run` text with many lines becomes a block."""
    lines = [f"name: {json.dumps(step['name'])}"] if step.get("name") else []
    if "uses" in step:
        lines.append(f"uses: {step['uses'].strip()}")
    elif "\n" in step["run"].strip():
        lines.append("run: |")
        lines += [f"  {line}" for line in step["run"].strip().splitlines()]
    else:
        lines.append(f"run: {json.dumps(step['run'].strip())}")
    if marker_if:
        lines.append(marker_if.strip())
    if step.get("with"):
        lines.append("with:")
        lines += [f"  {name}: {json.dumps(value)}" for name, value in step["with"].items()]
    return "\n".join(("      - " if number == 0 else "        ") + line
                     for number, line in enumerate(lines))
