"""The trigger part of `stone eval`: run a rendered trigger workflow on the local machine (D100).

A trigger component id is the registry id and the profile: `trigger.label.single-ticket`. The
variant `with` runs the role with the arguments of the rendered workflow (the prompt with the
profile steps, the report schema, and the tool limits of D32). Then it runs the shell steps of the
post job with a fake `gh` on PATH, so no real post happens. The variant `without` is the same role
run by hand: the same event file, a plain prompt, no schema, and no post job.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path
from string import Template
from typing import Any

import yaml

EVENT = Path("cornerstone") / "event.json"  # the path of the event file under runner.temp
FAKE_TOKEN = "stone-eval-fake-token"
KEEP_ENV = ("HOME", "LANG", "LC_ALL", "TMPDIR")  # the only variables of the caller in a post step
EXPRESSION = re.compile(r"\$\{\{\s*([^}]*?)\s*\}\}")
# The fake gh writes each call to a file. It prints a URL, as gh does after a post.
FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$STONE_EVAL_GH_LOG"
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--body-file" ]; then cat "$2" > "$STONE_EVAL_GH_LOG.body"; fi
  shift
done
echo "https://github.com/owner/repo/issues/1"
"""


class TriggerEvalError(Exception):
    """The rendered workflow does not have the form that the runner reads."""


def split_id(component_id: str, registry: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return a copy of the trigger entry for `<entry id>.<profile>`, with `profile` set."""
    for entry in registry:
        prefix = f"{entry['id']}."
        if "trigger" in entry and component_id.startswith(prefix) and entry.get("eval"):
            profile = component_id[len(prefix):]
            if profile and "." not in profile:
                return {**entry, "id": component_id, "profile": profile,
                        "target": entry["target"].replace("$profile", profile)}
    return None


def expand(text: str, values: dict[str, str]) -> str:
    """Replace each `${{ expression }}` with its value. Fail on an expression with no value."""
    def one(match: re.Match[str]) -> str:
        if match.group(1) not in values:
            raise TriggerEvalError(f"the runner has no value for the expression "
                                   f"'{match.group(1)}'. Add it to the trigger runner.")
        return values[match.group(1)]
    return EXPRESSION.sub(one, text)


def load_workflow(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TriggerEvalError(f"render wrote no workflow {path.name}. Check the profile.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("jobs"), dict) or not {"run", "post"} <= set(data["jobs"]):
        raise TriggerEvalError(f"{path.name}: the workflow has no 'run' and 'post' jobs.")
    return data


def role_step(workflow: dict[str, Any]) -> dict[str, Any]:
    """Return the `with` map of the step `run` of the job `run` (the role run)."""
    for step in workflow["jobs"]["run"].get("steps") or []:
        if step.get("id") == "run":
            inputs = step.get("with") or {}
            if isinstance(inputs.get("prompt"), str) and isinstance(inputs.get("claude_args"), str):
                return inputs
    raise TriggerEvalError("the job 'run' has no step 'run' with a prompt and claude_args.")


def expressions(runner_temp: Path, report: str = "", number: str = "1") -> dict[str, str]:
    """The values of the GitHub expressions that the run step and the post job use."""
    return {"runner.temp": str(runner_temp), "github.token": FAKE_TOKEN,
            "secrets.CLAUDE_CODE_OAUTH_TOKEN": FAKE_TOKEN,
            "needs.run.outputs.report": report,
            "github.event.issue.number": number,
            "github.event.pull_request.number": number}


def role_args(workflow: dict[str, Any], runner_temp: Path, model: str = "") -> tuple[list[str], str]:
    """Return the harness arguments and the prompt of the role run. `model` replaces --model."""
    inputs = role_step(workflow)
    values = expressions(runner_temp)
    words = shlex.split(expand(inputs["claude_args"], values))
    if model and "--model" in words:
        words[words.index("--model") + 1] = model
    return words, expand(inputs["prompt"], values)


def write_event(runner_temp: Path, source: Path) -> Path:
    """Copy the event file of the scenario to the place where the workflow reads it."""
    target = runner_temp / EVENT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    return target


def structured_report(structured: Any) -> str:
    """The job output of the run job: `structured_output && fromJSON(structured_output).report`."""
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except json.JSONDecodeError:
            return ""
    report = structured.get("report") if isinstance(structured, dict) else None
    return report if isinstance(report, str) else ""


def _fake_gh(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    gh = folder / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    return folder


def post(workflow: dict[str, Any], report: str, runner_temp: Path,
         number: str = "1") -> dict[str, Any]:
    """Run the shell steps of the post job, as GitHub runs them, with a fake gh.

    Return {"posted": the body that gh got, "calls": each gh call, "error": a failed step}.
    The job does not run if the report is empty (`if: needs.run.outputs.report != ''`).
    """
    if not report:
        return {"posted": "", "calls": [], "error": ""}
    log = runner_temp / "gh-calls.txt"
    values = expressions(runner_temp, report, number)
    for step in workflow["jobs"]["post"].get("steps") or []:
        if "run" not in step:
            continue
        env = step_env(runner_temp, log,
                       {k: expand(str(v), values) for k, v in (step.get("env") or {}).items()})
        done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c",
                               step["run"]], env=env, capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            return {"posted": "", "calls": _lines(log),
                    "error": f"the step '{step.get('name')}' failed: {done.stderr.strip()}"}
    body = log.with_name(log.name + ".body")
    return {"posted": body.read_text(encoding="utf-8") if body.exists() else "",
            "calls": _lines(log), "error": ""}


def step_env(runner_temp: Path, log: Path, step: dict[str, str]) -> dict[str, str]:
    """A closed environment for one post step: no token of the caller, no BASH_ENV, and no
    exported shell function. Only the fake gh is on PATH before the system folders. The fake token
    and an empty gh config folder win over a step value, so a real gh cannot post."""
    config = runner_temp / "gh-config"
    config.mkdir(parents=True, exist_ok=True)
    system = [d for d in os.environ.get("PATH", "").split(os.pathsep)
              if d and not (Path(d) / "gh").exists()]
    return {**{k: os.environ[k] for k in KEEP_ENV if k in os.environ}, **step,
            "PATH": os.pathsep.join([str(_fake_gh(runner_temp / "bin")), *system]),
            "RUNNER_TEMP": str(runner_temp), "GITHUB_REPOSITORY": "owner/repo",
            "STONE_EVAL_GH_LOG": str(log), "GH_TOKEN": FAKE_TOKEN, "GITHUB_TOKEN": FAKE_TOKEN,
            "GH_CONFIG_DIR": str(config)}


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def build(template: list[Any], values: dict[str, Any]) -> list[str]:
    """Fill the argv template. `$claude_args` and `$tools` become one item for each word."""
    argv: list[str] = []
    for item in template:
        if item in ("$claude_args", "$tools"):
            argv.extend(values[item[1:]])
        else:
            argv.append(Template(str(item)).safe_substitute(values))
    return argv


ZWSP = "​"
HEADER = re.compile(r"^\*\*Cornerstone report from the (?P<role>[\w-]+) \((?P<profile>[\w-]+)\)\.\*\* ")


def framed(posted: str, report: str, role: str, calls: str, call: str) -> tuple[bool, str]:
    """The post job posted the report with the framing of D38: one gh call that starts with
    `call`, the fixed header, each line of the report in a quote, and no live mention or end tag.
    The grader of each trigger eval uses this one copy."""
    if not posted:
        return False, "nothing was posted"
    if not any(line.startswith(call) and "--body-file" in line for line in calls.splitlines()):
        return False, f"no gh call starts with '{call}': {calls.splitlines()}"
    problem = _frame_problem(posted.rstrip("\n").split("\n"), report, role)
    if problem:
        return False, problem
    return True, f"posted with '{call}', framed"


def _frame_problem(lines: list[str], report: str, role: str) -> str:
    """Return what is wrong with the header, the quote, or the mentions, or ''."""
    header = HEADER.match(lines[0])
    if not header or header.group("role") != role:
        return f"the first line is not the header for the {role}: {lines[0][:80]!r}"
    body = lines[2:] if len(lines) > 2 and lines[1] == "" else []
    if not body or any(not line.startswith("> ") for line in body):
        return "a line of the report is not in a quote"
    if re.search(rf"@(?!{ZWSP})|</(?!{ZWSP})", "\n".join(body)):
        return "the posted text has a live mention or end tag"
    if "\n".join(line[2:] for line in body).replace(ZWSP, "").strip() != report.strip():
        return "the quoted text is not the structured report"
    return ""
