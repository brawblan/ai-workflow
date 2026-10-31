"""`stone eval`: run the eval of one component with the component and without it (P5).

The eval folder (`evals/<component-id>/`) has `scenarios.yaml` and an optional `grade.py`. Each run
copies a fixture to a new git repo in the system temp folder, renders the repo config, starts the
harness with the command in `framework/adapters/<harness>/eval.yaml`, and grades the result.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stderr
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from string import Template
from typing import Any

import yaml

from stone import render, results, specs, trigger_eval, triggers
from stone.markdown import split_frontmatter

VARIANTS = ("with", "without")
KINDS = {"outcome", "contract"}
REPORT = "@report"  # a check path that means the final text of the run
REPORT_ENV = "STONE_EVAL_REPORT"  # grade.py reads the final text of the run here
POSTED = "@posted"  # a check path that means the text that the post job of a trigger posted
POSTED_ENV = "STONE_EVAL_POSTED"  # grade.py reads the posted text here (D100)
GH_CALLS_ENV = "STONE_EVAL_GH_CALLS"  # and each call of the forge CLI, one on each line
RUNS = Path(".cornerstone/eval-runs")
RESULTS = results.RESULTS
WORK_BRANCH = "feature/eval-work"
GIT_ENV = {"GIT_AUTHOR_NAME": "stone eval", "GIT_AUTHOR_EMAIL": "eval@example.invalid",
           "GIT_COMMITTER_NAME": "stone eval", "GIT_COMMITTER_EMAIL": "eval@example.invalid",
           # No global or system git config, so each machine gives the same result.
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class EvalError(Exception):
    """The eval folder or the run config is not valid. No run started."""


@dataclass
class Workspace:
    path: Path
    setup: str  # the commit after the setup: the agent's changes come after it
    report: str = ""
    posted: str = ""  # a trigger eval: the body that the post job gave to gh
    gh_calls: str = ""  # a trigger eval: the arguments of each gh call


@dataclass
class Run:
    scenario: str
    variant: str
    trial: int
    checks: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def passed(self, kind: str | None = None) -> bool:
        return not self.error and all(c["pass"] for c in self.checks
                                      if kind is None or c["kind"] == kind)


# Loading -----------------------------------------------------------------------------------


def load_scenarios(folder: Path, role_required: bool = True) -> dict[str, Any]:
    """Read and validate `scenarios.yaml`. Raise EvalError with each problem. A trigger eval
    needs no `role`: the role is the first role of the profile (D100)."""
    path = folder / "scenarios.yaml"
    if not path.exists():
        raise EvalError(f"{path}: no file. Write the scenarios first (lifecycle.md).")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise EvalError(f"{path}: the YAML is not valid: {error}") from None
    if not isinstance(data, dict):
        raise EvalError(f"{path}: the file must be a mapping with 'component', 'role', and "
                        "'scenarios'. Fix the file.")
    keys = ("component", "role", "scenarios") if role_required else ("component", "scenarios")
    problems = [f"no '{key}'" for key in keys if not data.get(key)]
    scenarios = data.get("scenarios") or []
    if not isinstance(scenarios, list):
        problems.append("'scenarios' must be a list")
        scenarios = []
    problems += _variant_problems(data.get("variants"), folder)
    seen: set[str] = set()
    for number, scenario in enumerate(scenarios, 1):
        if not isinstance(scenario, dict):
            problems.append(f"#{number}: a scenario must be a mapping")
            continue
        if not isinstance(scenario.get("expect") or [], list):
            problems.append(f"{scenario.get('id') or f'#{number}'}: 'expect' must be a list")
            continue
        sid = scenario.get("id") or f"#{number}"
        needs = ("id", "fixture", "prompt", "expect") + (() if role_required else ("event",))
        problems += [f"{sid}: no '{key}'" for key in needs if not scenario.get(key)]
        problems += [f"{sid}: the id is used again"] if sid in seen else []
        seen.add(sid)
        for name in ("fixture", "change", "event"):
            if scenario.get(name) and not (folder / scenario[name]).exists():
                problems.append(f"{sid}: the {name} '{scenario[name]}' does not exist")
        for item in scenario.get("expect") or []:
            problems += [f"{sid}: {p}" for p in _check_problems(item, folder)]
    if problems:
        raise EvalError(f"{path}: " + "; ".join(problems) + ". Fix the file.")
    return data


def _variant_problems(variants: Any, folder: Path) -> list[str]:
    """Check the optional `variants` of a guidance eval: a name and the files it puts in the repo."""
    if variants is None:
        return []
    if not isinstance(variants, dict) or not variants:
        return ["'variants' must be a mapping from a variant name to a list of files"]
    problems = []
    for name, files in variants.items():
        if not isinstance(files, list):
            problems.append(f"the variant '{name}' must be a list of {{copy, to}} items")
            continue
        for item in files:
            if not isinstance(item, dict) or not item.get("copy") or not item.get("to"):
                problems.append(f"the variant '{name}' has an item with no 'copy' or 'to'")
                continue
            target = Path(str(item["to"]))
            if target.is_absolute() or ".." in target.parts:
                problems.append(f"the variant '{name}': 'to' must stay inside the repo: {item['to']}")
            if not (folder / str(item["copy"])).is_file():
                problems.append(f"the variant '{name}': the file '{item['copy']}' does not exist")
    return problems


def _check_problems(item: Any, folder: Path) -> list[str]:
    if not isinstance(item, dict) or item.get("check") not in CHECKS:
        name = item.get("check") if isinstance(item, dict) else item
        return [f"the check '{name}' is not known. Use one of {sorted(CHECKS)}"]
    problems = [f"the check '{item['check']}' has no '{key}'"
                for key in CHECKS[item["check"]][1] if key not in item]
    if item.get("kind", "outcome") not in KINDS:
        problems.append(f"the kind '{item['kind']}' is not valid. Use one of {sorted(KINDS)}")
    if item["check"] == "grader" and not (folder / "grade.py").exists():
        problems.append("a grader check needs grade.py in the eval folder")
    if item["check"] == "matches" and "pattern" in item:
        try:
            re.compile(str(item["pattern"]))
        except re.error as error:
            problems.append(f"the pattern '{item['pattern']}' is not a valid regex: {error}")
    return problems


def find_guidance(root: Path, component_id: str) -> dict[str, Any] | None:
    """Return the entry of a guidance eval: an eval folder whose scenarios name the id and have
    `variants`. Guidance (a skill, a rule text) is not a file that `stone render` writes, so it is
    not in the component list of the adapter (D69)."""
    found: list[str] = []
    for path in sorted((root / "evals").glob("*/scenarios.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError, ValueError):  # a file that is not YAML or not UTF-8
            continue
        if isinstance(data, dict) and data.get("component") == component_id and data.get("variants"):
            found.append(f"evals/{path.parent.name}/")
    if len(found) > 1:
        raise EvalError(f"{component_id} is in more than one eval folder: {', '.join(found)}. "
                        "Give each guidance eval its own component id.")
    return {"id": component_id, "kind": "guidance", "eval": found[0]} if found else None


def find_component(framework: Path, harness: str, component_id: str,
                   root: Path | None = None) -> dict[str, Any]:
    registry = yaml.safe_load((framework / "adapters" / harness / "components.yaml")
                              .read_text(encoding="utf-8"))["components"]
    for entry in registry:
        if entry["id"] == component_id:
            if "trigger" in entry:
                raise EvalError(f"{component_id} is one workflow for each profile. Add the "
                                f"profile to the id, for example {component_id}.single-ticket.")
            if not entry.get("eval"):
                raise EvalError(f"{component_id} has no eval folder. A check is its own test.")
            return entry
    trigger = trigger_eval.split_id(component_id, registry)  # trigger.label.single-ticket (D100)
    if trigger:
        return trigger
    guidance = find_guidance(root, component_id) if root else None
    if guidance:
        return guidance
    raise EvalError(f"The adapter '{harness}' has no component '{component_id}'.")


def registered_in(framework: Path, harness: str, target: str) -> list[str]:
    """Return each shared JSON file whose merged fragment names `target` (the entry of a hook)."""
    registry = yaml.safe_load((framework / "adapters" / harness / "components.yaml")
                              .read_text(encoding="utf-8"))["components"]
    found = []
    for entry in registry:
        if entry.get("merge") == "json" and entry.get("template") and target:
            fragment = framework / "adapters" / harness / "templates" / entry["template"]
            if target in fragment.read_text(encoding="utf-8"):
                found.append(entry["target"])
    return found


def load_run_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise EvalError(f"{path}: no file. The harness adapter must give the eval command.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise EvalError(f"{path}: the YAML is not valid: {error}") from None
    if not isinstance(data, dict) or not isinstance(data.get("run"), dict):
        raise EvalError(f"{path}: the file must be a mapping with 'run.with' and 'run.without'.")
    for variant in (*VARIANTS, *(["guidance"] if "guidance" in data["run"] else [])):
        if not isinstance(data["run"].get(variant), list):
            raise EvalError(f"{path}: 'run.{variant}' must be a list of arguments.")
    for key in ("output", "output_where", "env", "tools"):
        if not isinstance(data.get(key) or {}, dict):
            raise EvalError(f"{path}: '{key}' must be a mapping.")
    return data


# Running -----------------------------------------------------------------------------------


def _git(cwd: Path, *args: str, strip: bool = True) -> str:
    """Run git. A caller that parses fixed columns (status --porcelain) passes strip=False."""
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                            env={**os.environ, **GIT_ENV})
    if result.returncode != 0:
        raise EvalError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result.stdout.strip() if strip else result.stdout


def _commit(cwd: Path, message: str) -> None:
    _git(cwd, "add", "-A")
    _git(cwd, "commit", "-q", "--allow-empty", "-m", message)


def _prune(node: Any, target: str) -> Any:
    """Remove each list item that names `target`. Remove a container that this makes empty."""
    if isinstance(node, list):
        return [_prune(item, target) for item in node if target not in json.dumps(item)]
    if isinstance(node, dict):
        for key in list(node):
            was_empty = node[key] in ({}, [])
            node[key] = _prune(node[key], target)
            if node[key] in ({}, []) and not was_empty:
                del node[key]
    return node


def unregister(path: Path, target: str) -> None:
    """Remove from the JSON file `path` each entry that names `target`. Other entries stay."""
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(_prune(data, target), indent=2) + "\n", encoding="utf-8")


def prepare(folder: Path, scenario: dict[str, Any], framework: Path, role_file: str,
            variant: str, files: list[dict[str, Any]] | None = None,
            profile: str = "") -> Workspace:
    """Make the workspace: the fixture, the rendered files, the files of a guidance variant, and
    the change of the scenario. A trigger eval selects only its `profile` in the repo config."""
    path = Path(tempfile.mkdtemp(prefix=f"stone-eval-{scenario['id']}-")) / "repo"
    shutil.copytree(folder / scenario["fixture"], path)
    if profile:
        config = yaml.safe_load((path / render.CONFIG).read_text(encoding="utf-8"))
        config["profiles"] = [profile]
        (path / render.CONFIG).write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    _git(path, "init", "-q", "-b", "main")
    _commit(path, "chore: fixture base")
    _git(path, "checkout", "-q", "-b", WORK_BRANCH)  # an agent does not commit to the default
    if (path / render.CONFIG).exists():
        with redirect_stderr(StringIO()):
            render.render(path, framework)
    if variant == "without" and role_file:
        (path / role_file).unlink(missing_ok=True)
        # A shared settings file can still name the file (a hook entry). A missing hook file makes
        # every file-tool edit fail, so "without" removes those entries too (D44).
        if (path / render.CONFIG).exists():
            harness = render.load_config(path, framework)["harness"]
            for shared in registered_in(framework, harness, role_file):
                if (path / shared).is_file():
                    unregister(path / shared, role_file)
    _commit(path, "chore(cornerstone): render\n\nRole: generator\nActor: agent")
    for item in files or []:  # a guidance variant: its files are the only difference (D69)
        target = path / str(item["to"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(folder / str(item["copy"]), target)
    if files:
        _commit(path, f"chore(eval): the guidance of the variant {variant}")
    if scenario.get("change"):
        _git(path, "apply", "--whitespace=nowarn", str((folder / scenario["change"]).resolve()))
        _commit(path, "feat: the change under test\n\nRole: implementer\nActor: agent")
    return Workspace(path, _git(path, "rev-parse", "HEAD"))


def build_command(config: dict[str, Any], variant: str, values: dict[str, Any]) -> list[str]:
    """Fill the argv template. An argument that is only `$tools` becomes one item per tool."""
    argv: list[str] = []
    for item in config["run"][variant]:
        if item == "$tools":
            argv.extend(values["tools"])
        else:
            argv.append(Template(str(item)).safe_substitute(values))
    return argv


def _dotted(data: Any, dotted: str) -> Any:
    for key in dotted.split("."):
        data = data.get(key) if isinstance(data, dict) else None
    return data


def _same(data: dict[str, Any], key: str, value: Any) -> bool:
    """The key is in the object with the same value and type (true is not 1)."""
    return key in data and type(data[key]) is type(value) and data[key] == value


def parse_output(stdout: str, fields: dict[str, str],
                 where: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read the last JSON object in the output that has each key and value in `where`."""
    for line in reversed(stdout.strip().splitlines() or [""]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and all(_same(data, k, v) for k, v in (where or {}).items()):
            return {name: _dotted(data, path) for name, path in fields.items()}
    return {}


def _harness(argv: list[str], cwd: Path, env: dict[str, str],
             timeout: int) -> tuple[int | None, str, str]:
    """Run the harness in its own process group. Return (exit code or None on timeout, out, err).

    On a timeout, the whole group stops, so no tool process writes to the workspace after it.
    """
    with subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True) as process:
        try:
            out, err = process.communicate(timeout=timeout)
            code: int | None = process.returncode
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            out, err = process.communicate()
            code = None
    return code, out.decode(errors="replace"), err.decode(errors="replace")


def run_once(folder: Path, data: dict[str, Any], scenario: dict[str, Any], variant: str,
             trial: int, opts: dict[str, Any]) -> Run:
    run = Run(scenario["id"], variant, trial)
    config = opts["run_config"]
    try:
        workspace = prepare(folder, scenario, opts["framework"], opts["role_file"], variant,
                            opts["variants"].get(variant), opts.get("profile", ""))
    except (EvalError, render.RenderError, OSError, yaml.YAMLError) as error:
        run.error = f"the setup failed: {error}"  # the harness does not start
        return run
    # Only a role eval removes the role. For another component, both variants load the same role
    # file, so the hook (or other component) is the only difference (D44).
    launch = {"role": variant, "guidance": "guidance"}.get(opts["kind"], "with")
    prompt = "\n\n".join(part for part in (data.get("task"), scenario["prompt"]) if part)
    values = {"role": data["role"], "model": opts["model"], "budget": opts["budget"],
              "prompt": prompt, "tools": (config.get("tools") or {}).get(data["role"], [])}
    env = {**os.environ, **GIT_ENV,
           **{k: Template(str(v)).safe_substitute(values)
              for k, v in ((config.get("env") or {}).get(launch) or {}).items()}}
    workflow: dict[str, Any] | None = None
    try:
        argv = build_command(config, launch, values)
        if opts.get("profile"):
            argv, workflow = _trigger_argv(folder, scenario, variant, workspace, values, opts)
    except (trigger_eval.TriggerEvalError, OSError, yaml.YAMLError) as error:
        run.error = f"the setup failed: {error}"
        if not opts["keep"]:
            shutil.rmtree(workspace.path.parent, ignore_errors=True)
        return run
    start = time.monotonic()
    stdout = stderr = ""
    try:
        code, stdout, stderr = _harness(argv, workspace.path, env, opts["timeout"])
        if code is None:
            run.error = f"the harness ran for more than {opts['timeout']} seconds"
        elif code != 0:
            run.error = f"the harness exit code is {code}"
    except OSError as error:
        run.error = f"the harness did not start: {error}"
    try:
        run.usage = parse_output(stdout, config.get("output") or {}, config.get("output_where"))
        run.usage.setdefault("seconds", round(time.monotonic() - start, 1))
        workspace.report = str(run.usage.pop("report", "") or "")
        structured = run.usage.pop("structured_output", None)
        if workflow is not None:  # the trigger posts only the structured report (D71)
            _trigger_post(run, workspace, workflow, structured, scenario)
        transcript = opts["runs"] / f"{scenario['id']}-{variant}-{trial}.out"
        transcript.write_text(stdout, encoding="utf-8")
        if stderr:
            transcript.with_suffix(".err").write_text(stderr, encoding="utf-8")
        run.usage.update(transcript=str(transcript), workspace=str(workspace.path))
        run.checks = grade(folder, scenario, workspace)
    finally:
        if not opts["keep"]:
            shutil.rmtree(workspace.path.parent, ignore_errors=True)
    return run


def _trigger_argv(folder: Path, scenario: dict[str, Any], variant: str, workspace: Workspace,
                  values: dict[str, Any], opts: dict[str, Any]) -> tuple[list[str], dict | None]:
    """Return the command of a trigger run and, for `with`, the rendered workflow (D100)."""
    config = opts["run_config"].get("trigger") or {}
    if not isinstance(config.get(variant), list):
        raise trigger_eval.TriggerEvalError(f"the harness run file has no 'trigger.{variant}'.")
    runner_temp = workspace.path.parent / "runner-temp"
    event = trigger_eval.write_event(runner_temp, folder / str(scenario["event"]))
    values = {**values, "event_dir": str(event.parent), "tools": config.get("tools") or [],
              "prompt": Template(values["prompt"]).safe_substitute(event_file=str(event))}
    if variant == "without":  # the role run by hand: no workflow, no schema, no post job
        return trigger_eval.build(config[variant], values), None
    workflow = trigger_eval.load_workflow(workspace.path / opts["role_file"])
    words, prompt = trigger_eval.role_args(workflow, runner_temp, opts["model"])
    return trigger_eval.build(config[variant], {**values, "claude_args": words,
                                                "prompt": prompt}), workflow


def _trigger_post(run: Run, ws: Workspace, workflow: dict[str, Any], structured: Any,
                  scenario: dict[str, Any]) -> None:
    """Run the post job on the structured report. The report checks read that report."""
    ws.report = trigger_eval.structured_report(structured)
    runner_temp = ws.path.parent / "runner-temp"
    try:
        result = trigger_eval.post(workflow, ws.report, runner_temp,
                                   str(scenario.get("number", 1)))
    except (trigger_eval.TriggerEvalError, subprocess.TimeoutExpired, OSError) as error:
        result = {"posted": "", "calls": [], "error": str(error)}
    ws.posted = result["posted"]
    ws.gh_calls = "\n".join(result["calls"])
    if result["error"] and not run.error:
        run.error = f"the post job failed: {result['error']}"


# Checks ------------------------------------------------------------------------------------


def _changed(ws: Workspace) -> list[str]:
    """Return each path that the run added, changed, or removed. A rename gives both paths."""
    committed = _git(ws.path, "diff", "--name-only", "--no-renames", "-z", ws.setup, "HEAD")
    # No strip: the first entry can start with a space (" M path" is a change not in the index).
    status = _git(ws.path, "status", "--porcelain=v1", "-z", "--no-renames",
                  "--untracked-files=all", strip=False)
    return sorted(set(committed.split("\0") + [item[3:] for item in status.split("\0")]) - {""})


def under(path: str, prefixes: list[str]) -> bool:
    """Return True if `path` is a prefix or is under one. It matches no glob (D62).

    The one copy of this rule: evals/hook-protect-paths/grade.py imports it (D64).
    """
    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes)


def _text(ws: Workspace, path: str) -> str | None:
    if path == REPORT:
        return ws.report
    if path == POSTED:
        return ws.posted
    target = ws.path / path
    return target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None


def _file_exists(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    found = sorted(str(p.relative_to(ws.path)) for p in ws.path.glob(item["path"]))
    return bool(found), ", ".join(found) or "no match"


def _file_absent(ws: Workspace, item: dict[str, Any], folder: Path) -> tuple[bool, str]:
    exists, detail = _file_exists(ws, item, folder)
    return not exists, detail


def _unchanged(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    hits = [p for p in _changed(ws) if under(p, item["paths"])]
    return not hits, ", ".join(hits) or "no change"


def _only_changed(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    outside = [p for p in _changed(ws) if not under(p, item["paths"])]
    return not outside, ", ".join(outside) or "no change outside"


def _matches(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    text = _text(ws, item["path"])
    if text is None:
        return False, "no file"
    found = re.search(item["pattern"], text, re.M | re.I)
    return bool(found), found.group(0)[:80] if found else "no match"


def _sections_in_order(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    text = _text(ws, item["path"])
    if text is None:
        return False, "no file"
    headings = [line.lower() for line in text.splitlines() if line.startswith("#")]
    position = 0
    for name in item["sections"]:
        hit = next((i for i in range(position, len(headings)) if name.lower() in headings[i]), -1)
        if hit < 0:
            return False, f"no '{name}' heading after the earlier sections"
        position = hit + 1
    return True, "all sections in order"


def _json_valid(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    text = _text(ws, item["path"])
    try:
        data = json.loads(text) if text is not None else None
    except json.JSONDecodeError as error:
        return False, f"not valid JSON: {error}"
    if not isinstance(data, dict):
        return False, "no file" if text is None else "not a JSON object"
    missing = [key for key in item.get("required", []) if key not in data]
    return not missing, f"no {', '.join(missing)}" if missing else "valid"


def _command(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(shlex.split(item["run"]), cwd=ws.path, capture_output=True,
                                text=True, timeout=item.get("timeout", 300),
                                env={**os.environ, **GIT_ENV})
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    return result.returncode == item.get("exit", 0), f"exit code {result.returncode}"


def _commit_trailer(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    log = _git(ws.path, "log", "--format=%B", f"{ws.setup}..HEAD")
    found = any(line.strip() == item["trailer"] for line in log.splitlines())
    return found, "found" if found else "no commit after the setup has it"


def _spec_delta_valid(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    path = ws.path / item["path"]
    if not path.is_file():
        return False, "no file"
    delta = specs.parse_delta(path)
    if delta.errors:
        return False, "; ".join(f"line {line}: {message}" for line, message in delta.errors)
    return True, ", ".join(f"{c.op} {c.id}" for c in delta.changes)


def _grader(ws: Workspace, item: dict[str, Any], folder: Path) -> tuple[bool, str]:
    args = {k: v for k, v in item.items() if k not in {"check", "kind", "name"}}
    try:
        result = subprocess.run(
            [sys.executable, str((folder / "grade.py").resolve()), item["name"],
             "--workspace", str(ws.path), "--args", json.dumps(args)],
            cwd=folder, capture_output=True, text=True, timeout=item.get("timeout", 600),
            env={**os.environ, **GIT_ENV, REPORT_ENV: ws.report, POSTED_ENV: ws.posted,
                 GH_CALLS_ENV: ws.gh_calls})
        data = json.loads(result.stdout.strip().splitlines()[-1])
        return data["pass"] is True, str(data.get("detail", ""))
    except (OSError, subprocess.TimeoutExpired, IndexError, KeyError, TypeError,
            json.JSONDecodeError) as error:
        return False, f"the grader failed: {error}"


CHECKS: dict[str, tuple[Any, tuple[str, ...]]] = {  # name -> (function, required keys)
    "file_exists": (_file_exists, ("path",)),
    "file_absent": (_file_absent, ("path",)),
    "unchanged": (_unchanged, ("paths",)),
    "only_changed": (_only_changed, ("paths",)),
    "matches": (_matches, ("path", "pattern")),
    "sections_in_order": (_sections_in_order, ("path", "sections")),
    "json_valid": (_json_valid, ("path",)),
    "command": (_command, ("run",)),
    "commit_trailer": (_commit_trailer, ("trailer",)),
    "spec_delta_valid": (_spec_delta_valid, ("path",)),
    "grader": (_grader, ("name",)),
}


def grade(folder: Path, scenario: dict[str, Any], ws: Workspace) -> list[dict[str, Any]]:
    results = []
    for item in scenario["expect"]:
        try:
            passed, detail = CHECKS[item["check"]][0](ws, item, folder)
        except Exception as error:  # a broken check fails itself, not the eval
            passed, detail = False, f"the check failed: {error}"
        label = (item.get("name") or item.get("path") or item.get("trailer") or item.get("run")
                 or ", ".join(item.get("paths", [])))
        results.append({"check": item["check"], "label": str(label), "kind":
                        item.get("kind", "outcome"), "pass": passed, "detail": detail})
    return results


# Report ------------------------------------------------------------------------------------


def _mean(runs: list[Run], key: str, digits: int = 0) -> str:
    values = [r.usage[key] for r in runs if isinstance(r.usage.get(key), (int, float))]
    return f"{sum(values) / len(values):.{digits}f}" if values else "—"


def _rate(runs: list[Run], kind: str | None) -> float:
    return sum(r.passed(kind) for r in runs) / len(runs) if runs else 0.0


def summary(component: str, model: str, runs: list[Run]) -> str:
    """Return the result table in Markdown: one row for each scenario and variant."""
    lines = [f"# Eval results: {component}", "", f"Model: `{model}`. Date: {dt.date.today()}.", "",
             "| Scenario | Variant | Trials | pass^k | Outcome | Contract | Cost | Tokens out "
             "| Seconds | Errors |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for sid in dict.fromkeys(r.scenario for r in runs):
        for variant in dict.fromkeys(r.variant for r in runs):
            group = [r for r in runs if r.scenario == sid and r.variant == variant]
            if group:
                lines.append(
                    f"| {sid} | {variant} | {len(group)} | {int(all(r.passed() for r in group))} "
                    f"| {_rate(group, 'outcome'):.2f} | {_rate(group, 'contract'):.2f} "
                    f"| {_mean(group, 'cost_usd', 2)} | {_mean(group, 'output_tokens')} "
                    f"| {_mean(group, 'seconds', 1)} | {sum(bool(r.error) for r in group)} |")
    names = list(dict.fromkeys(r.variant for r in runs))
    base = next((name for name in ("without", "none") if name in names), "")
    others = [name for name in names if name != base]
    if base and others:
        lines.append("")
        for name in others:
            gain = (_rate([r for r in runs if r.variant == name], "outcome")
                    - _rate([r for r in runs if r.variant == base], "outcome"))
            lines.append(f"Outcome pass rate, {name} minus {base}: {gain:+.2f}.")
    return "\n".join(lines) + "\n"


def _first_role(framework: Path, entry: dict[str, Any]) -> str:
    """The role that the trigger of the profile starts (D31). The profile must use the trigger."""
    path = framework / "profiles" / f"{entry['profile']}.md"
    if not path.is_file():
        raise EvalError(f"The profile '{entry['profile']}' does not exist. Use a profile id.")
    profile = split_frontmatter(path.read_text(encoding="utf-8"))[0]
    kinds = {triggers.parse(str(text))[0] for text in profile.get("triggers") or []}
    if entry["trigger"] not in kinds:
        raise EvalError(f"The profile '{entry['profile']}' has no {entry['trigger']} trigger. "
                        "Use a profile that has it.")
    return profile["roles"][0]


def _select(scenarios: list[dict[str, Any]], ids: list[str] | None,
            profile_id: str) -> list[dict[str, Any]]:
    """The scenarios to run: the ids, if given, and for a trigger only those of its profile."""
    chosen = [s for s in scenarios if (not ids or s["id"] in ids)
              and profile_id in (s.get("profiles") or [profile_id])]
    if ids and len(chosen) != len(set(ids)):
        unknown = sorted(set(ids) - {s["id"] for s in chosen})
        raise EvalError(f"No scenario has the id {unknown} for this component. Use an id in "
                        "scenarios.yaml.")
    return chosen


def run_eval(root: Path, component_id: str, *, framework: Path | None = None,
             scenario_ids: list[str] | None = None, variant: str = "both", trials: int = 1,
             model: str | None = None, budget: str = "5", timeout: int = 1800,
             run_config: Path | None = None, keep: bool = False,
             check_only: bool = False) -> tuple[list[Run], str]:
    """Run the eval. Return the runs and the path of the result file ('' for check_only)."""
    framework = framework or root / "framework"
    config = render.load_config(root, framework)
    entry = find_component(framework, config["harness"], component_id, root)
    folder = root / entry["eval"]
    profile_id = entry.get("profile", "")
    data = load_scenarios(folder, role_required=not profile_id)
    data["role"] = _first_role(framework, entry) if profile_id else data["role"]
    scenarios = _select(data["scenarios"], scenario_ids, profile_id)
    harness = framework / "adapters" / config["harness"]
    loaded = load_run_config(run_config or harness / "eval.yaml")
    profile = yaml.safe_load((harness / "models" / f"{config['model_profile']}.yaml")
                             .read_text(encoding="utf-8"))
    model = model or profile["defaults"]["role_models"].get(data["role"], "")
    if data.get("variants") and entry.get("kind") != "guidance":
        raise EvalError(f"{component_id} is in the adapter component list, so it takes the variants "
                        "'with' and 'without'. Remove 'variants' from its scenarios.")
    names = tuple(data.get("variants") or VARIANTS)
    if variant != "both" and variant not in names:
        raise EvalError(f"The variant '{variant}' is not known. Use 'both' or one of "
                        f"{list(names)}.")
    variants = names if variant == "both" else (variant,)
    if entry.get("kind") == "guidance" and not model:
        raise EvalError("A guidance eval has no role model. Pass --model.")
    if entry.get("kind") == "guidance" and "guidance" not in loaded["run"]:
        raise EvalError("The harness run file has no 'run.guidance' command for a guidance eval.")
    if entry.get("merge") and "without" in variants:
        raise EvalError(f"{component_id} is merged into a shared file. The runner cannot remove "
                        "it for 'without' yet. Use --variant with.")
    if check_only:
        for scenario in scenarios:
            print(f"{scenario['id']}: {len(scenario['expect'])} check(s), "
                  f"{len(variants) * trials} run(s)")
        return [], ""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    runs_folder = root / RUNS / f"{stamp}-{entry['eval'].strip('/').split('/')[-1]}"
    runs_folder.mkdir(parents=True, exist_ok=True)
    opts = {"framework": framework.resolve(), "role_file": entry.get("target", ""), "kind": entry.get("kind", ""),
            "run_config": loaded, "model": model, "budget": budget, "timeout": timeout,
            "runs": runs_folder, "keep": keep, "variants": data.get("variants") or {},
            "profile": profile_id}
    runs: list[Run] = []
    with (runs_folder / "runs.jsonl").open("w", encoding="utf-8") as handle:
        for scenario in scenarios:
            for name in variants:
                for trial in range(1, trials + 1):
                    run = run_once(folder, data, scenario, name, trial, opts)
                    print(f"{run.scenario} {run.variant} {run.trial}: "
                          f"{'pass' if run.passed() else 'fail'} {run.error}".rstrip())
                    runs.append(run)
                    handle.write(json.dumps(run.__dict__) + "\n")  # kept if a later run stops
                    handle.flush()
    safe_model = re.sub(r"[^\w.-]+", "-", model) or "default"
    result_path = root / RESULTS / f"{stamp}-{component_id}-{safe_model}.md"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(summary(component_id, model, runs), encoding="utf-8")
    return runs, str(result_path)
