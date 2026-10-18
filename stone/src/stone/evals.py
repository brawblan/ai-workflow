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

from stone import render, specs

VARIANTS = ("with", "without")
KINDS = {"outcome", "contract"}
REPORT = "@report"  # a check path that means the final text of the run
RUNS = Path(".cornerstone/eval-runs")
RESULTS = Path("evals/results")
GIT_ENV = {"GIT_AUTHOR_NAME": "stone eval", "GIT_AUTHOR_EMAIL": "eval@example.invalid",
           "GIT_COMMITTER_NAME": "stone eval", "GIT_COMMITTER_EMAIL": "eval@example.invalid"}


class EvalError(Exception):
    """The eval folder or the run config is not valid. No run started."""


@dataclass
class Workspace:
    path: Path
    setup: str  # the commit after the setup: the agent's changes come after it
    report: str = ""


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


def load_scenarios(folder: Path) -> dict[str, Any]:
    """Read and validate `scenarios.yaml`. Raise EvalError with each problem."""
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
    problems = [f"no '{key}'" for key in ("component", "role", "scenarios") if not data.get(key)]
    if data.get("scenarios") and not isinstance(data["scenarios"], list):
        problems.append("'scenarios' must be a list")
    seen: set[str] = set()
    for number, scenario in enumerate(data.get("scenarios") or [], 1):
        if not isinstance(scenario, dict):
            problems.append(f"#{number}: a scenario must be a mapping")
            continue
        if not isinstance(scenario.get("expect") or [], list):
            problems.append(f"{scenario.get('id') or f'#{number}'}: 'expect' must be a list")
            continue
        sid = scenario.get("id") or f"#{number}"
        problems += [f"{sid}: no '{key}'" for key in ("id", "fixture", "prompt", "expect")
                     if not scenario.get(key)]
        problems += [f"{sid}: the id is used again"] if sid in seen else []
        seen.add(sid)
        for name in ("fixture", "change"):
            if scenario.get(name) and not (folder / scenario[name]).exists():
                problems.append(f"{sid}: the {name} '{scenario[name]}' does not exist")
        for item in scenario.get("expect") or []:
            problems += [f"{sid}: {p}" for p in _check_problems(item, folder)]
    if problems:
        raise EvalError(f"{path}: " + "; ".join(problems) + ". Fix the file.")
    return data


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
    return problems


def find_component(framework: Path, harness: str, component_id: str) -> dict[str, Any]:
    registry = yaml.safe_load((framework / "adapters" / harness / "components.yaml")
                              .read_text(encoding="utf-8"))["components"]
    for entry in registry:
        if entry["id"] == component_id:
            if not entry.get("eval"):
                raise EvalError(f"{component_id} has no eval folder. A check is its own test.")
            return entry
    raise EvalError(f"The adapter '{harness}' has no component '{component_id}'.")


def load_run_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise EvalError(f"{path}: no file. The harness adapter must give the eval command.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise EvalError(f"{path}: the YAML is not valid: {error}") from None
    if not isinstance(data, dict) or not isinstance(data.get("run"), dict):
        raise EvalError(f"{path}: the file must be a mapping with 'run.with' and 'run.without'.")
    for variant in VARIANTS:
        if not isinstance(data["run"].get(variant), list):
            raise EvalError(f"{path}: 'run.{variant}' must be a list of arguments.")
    return data


# Running -----------------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                            env={**os.environ, **GIT_ENV})
    if result.returncode != 0:
        raise EvalError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result.stdout.strip()


def _commit(cwd: Path, message: str) -> None:
    _git(cwd, "add", "-A")
    _git(cwd, "commit", "-q", "--allow-empty", "-m", message)


def prepare(folder: Path, scenario: dict[str, Any], framework: Path, role_file: str,
            variant: str) -> Workspace:
    """Make the workspace: the fixture, the rendered files, and the change of the scenario."""
    path = Path(tempfile.mkdtemp(prefix=f"stone-eval-{scenario['id']}-")) / "repo"
    shutil.copytree(folder / scenario["fixture"], path)
    _git(path, "init", "-q", "-b", "main")
    _commit(path, "chore: fixture base")
    if (path / render.CONFIG).exists():
        with redirect_stderr(StringIO()):
            render.render(path, framework)
        if variant == "without":
            (path / role_file).unlink(missing_ok=True)
        _commit(path, "chore(cornerstone): render\n\nRole: generator\nActor: agent")
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


def parse_output(stdout: str, fields: dict[str, str]) -> dict[str, Any]:
    """Read the last JSON object in the output: one object, or the last line of a stream."""
    for line in reversed(stdout.strip().splitlines() or [""]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return {name: _dotted(data, path) for name, path in fields.items()}
    return {}


def run_once(folder: Path, data: dict[str, Any], scenario: dict[str, Any], variant: str,
             trial: int, opts: dict[str, Any]) -> Run:
    run = Run(scenario["id"], variant, trial)
    config = opts["run_config"]
    try:
        workspace = prepare(folder, scenario, opts["framework"], opts["role_file"], variant)
    except (EvalError, render.RenderError, OSError) as error:
        run.error = f"the setup failed: {error}"  # the harness does not start
        return run
    prompt = "\n\n".join(part for part in (data.get("task"), scenario["prompt"]) if part)
    values = {"role": data["role"], "model": opts["model"], "budget": opts["budget"],
              "prompt": prompt, "tools": (config.get("tools") or {}).get(data["role"], [])}
    env = {**os.environ, **{k: Template(str(v)).safe_substitute(values)
                            for k, v in ((config.get("env") or {}).get(variant) or {}).items()}}
    start = time.monotonic()
    try:
        result = subprocess.run(build_command(config, variant, values), cwd=workspace.path,
                                env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=opts["timeout"])
        stdout = result.stdout
        if result.returncode != 0:
            run.error = f"the harness exit code is {result.returncode}"
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else error.stdout or ""
        run.error = f"the harness ran for more than {opts['timeout']} seconds"
    except OSError as error:
        stdout, run.error = "", f"the harness did not start: {error}"
    run.usage = parse_output(stdout, config.get("output") or {})
    run.usage.setdefault("seconds", round(time.monotonic() - start, 1))
    workspace.report = str(run.usage.pop("report", "") or "")
    transcript = opts["runs"] / f"{scenario['id']}-{variant}-{trial}.out"
    transcript.write_text(stdout, encoding="utf-8")
    run.usage.update(transcript=str(transcript), workspace=str(workspace.path))
    run.checks = grade(folder, scenario, workspace)
    if not opts["keep"]:
        shutil.rmtree(workspace.path.parent, ignore_errors=True)
    return run


# Checks ------------------------------------------------------------------------------------


def _changed(ws: Workspace) -> list[str]:
    committed = _git(ws.path, "diff", "--name-only", ws.setup, "HEAD").splitlines()
    status = _git(ws.path, "status", "--porcelain", "--untracked-files=all").splitlines()
    return sorted(set(committed + [line[3:] for line in status]) - {""})


def _under(path: str, prefixes: list[str]) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes)


def _text(ws: Workspace, path: str) -> str | None:
    if path == REPORT:
        return ws.report
    target = ws.path / path
    return target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None


def _file_exists(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    found = sorted(str(p.relative_to(ws.path)) for p in ws.path.glob(item["path"]))
    return bool(found), ", ".join(found) or "no match"


def _file_absent(ws: Workspace, item: dict[str, Any], folder: Path) -> tuple[bool, str]:
    exists, detail = _file_exists(ws, item, folder)
    return not exists, detail


def _unchanged(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    hits = [p for p in _changed(ws) if _under(p, item["paths"])]
    return not hits, ", ".join(hits) or "no change"


def _only_changed(ws: Workspace, item: dict[str, Any], _: Path) -> tuple[bool, str]:
    outside = [p for p in _changed(ws) if not _under(p, item["paths"])]
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
                                text=True, timeout=item.get("timeout", 300))
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
            cwd=folder, capture_output=True, text=True, timeout=item.get("timeout", 600))
        data = json.loads(result.stdout.strip().splitlines()[-1])
        return bool(data["pass"]), str(data.get("detail", ""))
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
        passed, detail = CHECKS[item["check"]][0](ws, item, folder)
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
        for variant in VARIANTS:
            group = [r for r in runs if r.scenario == sid and r.variant == variant]
            if group:
                lines.append(
                    f"| {sid} | {variant} | {len(group)} | {int(all(r.passed() for r in group))} "
                    f"| {_rate(group, 'outcome'):.2f} | {_rate(group, 'contract'):.2f} "
                    f"| {_mean(group, 'cost_usd', 2)} | {_mean(group, 'output_tokens')} "
                    f"| {_mean(group, 'seconds', 1)} | {sum(bool(r.error) for r in group)} |")
    with_runs = [r for r in runs if r.variant == "with"]
    without = [r for r in runs if r.variant == "without"]
    if with_runs and without:
        gain = _rate(with_runs, "outcome") - _rate(without, "outcome")
        lines += ["", f"Outcome pass rate, with minus without: {gain:+.2f}."]
    return "\n".join(lines) + "\n"


def run_eval(root: Path, component_id: str, *, framework: Path | None = None,
             scenario_ids: list[str] | None = None, variant: str = "both", trials: int = 1,
             model: str | None = None, budget: str = "5", timeout: int = 1800,
             run_config: Path | None = None, keep: bool = False,
             check_only: bool = False) -> tuple[list[Run], str]:
    """Run the eval. Return the runs and the path of the result file ('' for check_only)."""
    framework = framework or root / "framework"
    config = render.load_config(root, framework)
    entry = find_component(framework, config["harness"], component_id)
    folder = root / entry["eval"]
    data = load_scenarios(folder)
    scenarios = [s for s in data["scenarios"] if not scenario_ids or s["id"] in scenario_ids]
    if scenario_ids and len(scenarios) != len(set(scenario_ids)):
        unknown = sorted(set(scenario_ids) - {s["id"] for s in scenarios})
        raise EvalError(f"No scenario has the id {unknown}. Use an id in scenarios.yaml.")
    harness = framework / "adapters" / config["harness"]
    loaded = load_run_config(run_config or harness / "eval.yaml")
    profile = yaml.safe_load((harness / "models" / f"{config['model_profile']}.yaml")
                             .read_text(encoding="utf-8"))
    model = model or profile["defaults"]["role_models"].get(data["role"], "")
    variants = VARIANTS if variant == "both" else (variant,)
    if check_only:
        for scenario in scenarios:
            print(f"{scenario['id']}: {len(scenario['expect'])} check(s), "
                  f"{len(variants) * trials} run(s)")
        return [], ""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    runs_folder = root / RUNS / f"{stamp}-{entry['eval'].strip('/').split('/')[-1]}"
    runs_folder.mkdir(parents=True, exist_ok=True)
    opts = {"framework": framework.resolve(), "role_file": entry.get("target", ""),
            "run_config": loaded, "model": model, "budget": budget, "timeout": timeout,
            "runs": runs_folder, "keep": keep}
    runs: list[Run] = []
    for scenario in scenarios:
        for name in variants:
            for trial in range(1, trials + 1):
                run = run_once(folder, data, scenario, name, trial, opts)
                print(f"{run.scenario} {run.variant} {run.trial}: "
                      f"{'pass' if run.passed() else 'fail'} {run.error}".rstrip())
                runs.append(run)
    with (runs_folder / "runs.jsonl").open("w", encoding="utf-8") as handle:
        for run in runs:
            handle.write(json.dumps(run.__dict__) + "\n")
    result_path = root / RESULTS / f"{stamp}-{component_id}-{model or 'default'}.md"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(summary(component_id, model, runs), encoding="utf-8")
    return runs, str(result_path)
