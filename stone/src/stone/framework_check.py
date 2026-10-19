"""`stone check`: validate the framework files and, if present, the repo config."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

import yaml

from stone import personas_check, specs
from stone.findings import Finding
from stone.markdown import relative_links, split_frontmatter, table_rows

CHECK = "stone check"
GATE_VALUES: dict[str, set[str]] = {
    "G1": {"human", "check", "skip"},
    "G2": {"human", "skip"},
    "G3": {"required", "skip"},
    "G4": {"human", "skip"},
    "G5": {"always", "if-needed"},
}
PLAN_FORMS = {"plan-artifact", "decision-log", "none"}
MODES = {"agent-centric", "hybrid", "human-centric"}
REQUIRED_KEYS = ["id", "name", "version", "purpose", "triggers", "stages", "roles",
                 "plan_form", "mode", "gates", "checks", "limits", "outputs"]
MATRIX_VALUE = {"—": "skip", "yes": "required", "if needed": "if-needed"}
VENDOR_NAMES = ["claude", "codex", "cursor", "copilot", "gemini", "openspec", "kiro",
                "anthropic", "openai"]
EVAL_OPTIONAL_KINDS = {"check"}  # lifecycle.md: a check is its own test, so its eval can be ""


def _first_column(rows: list[list[str]]) -> list[str]:
    return [row[0] for row in rows if row]


def _known_names(framework: Path) -> tuple[set[str], set[str], set[str]]:
    """Return the stage names, role names, and check IDs that the framework defines."""
    model = (framework / "workflow-model.md").read_text(encoding="utf-8")
    stages_part = model.split("## Stages", 1)[1].split("### Loop limits", 1)[0]
    roles_part = model.split("## Roles", 1)[1].split("### Session rules", 1)[0]
    stages = {name.lower() for name in _first_column(table_rows(stages_part))} - {"stage"}
    roles = set(_first_column(table_rows(roles_part))) - {"Role"}
    checks_text = (framework / "checks.md").read_text(encoding="utf-8")
    check_ids = set(re.findall(r"^\| (K\d+) \|", checks_text, re.M))
    return stages, roles, check_ids


def _gate_matrix(framework: Path) -> dict[str, list[str]]:
    text = (framework / "gates.md").read_text(encoding="utf-8")
    matrix: dict[str, list[str]] = {}
    for row in table_rows(text):
        match = re.match(r"\[([a-z-]+)\]\(profiles/", row[0])
        if match:
            matrix[match.group(1)] = [_matrix_value(cell) for cell in row[1:6]]
    return matrix


def _matrix_value(cell: str) -> str:
    cell = cell.strip()
    if cell in MATRIX_VALUE:
        return MATRIX_VALUE[cell]
    return cell.split(" ")[0]  # "human (label decisions)" -> "human"


def check_profiles(framework: Path) -> list[Finding]:
    findings: list[Finding] = []
    stages, roles, check_ids = _known_names(framework)
    matrix = _gate_matrix(framework)
    for path in sorted((framework / "profiles").glob("*.md")):
        if path.name in {"README.md", "_template.md"}:
            continue
        data, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        findings.extend(_check_profile(path, data, stages, roles, check_ids, matrix))
    return findings


def _check_profile(path: Path, data: dict[str, Any], stages: set[str], roles: set[str],
                   check_ids: set[str], matrix: dict[str, list[str]]) -> list[Finding]:
    found: list[Finding] = []

    def add(message: str) -> None:
        found.append(Finding(str(path), 1, CHECK, message))

    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        add(f"The frontmatter has no {', '.join(missing)}. Add the missing keys.")
        return found
    if data["id"] != path.stem:
        add(f"The id '{data['id']}' is not the file name '{path.stem}'. Make them the same.")
    if data["plan_form"] not in PLAN_FORMS:
        add(f"The plan_form '{data['plan_form']}' is not valid. Use one of {sorted(PLAN_FORMS)}.")
    if data["mode"] not in MODES:
        add(f"The mode '{data['mode']}' is not valid. Use one of {sorted(MODES)}.")
    for stage in set(data["stages"]) - stages:
        add(f"The stage '{stage}' is not in workflow-model.md. Use a defined stage.")
    for role in set(data["roles"]) - roles:
        add(f"The role '{role}' is not in workflow-model.md. Use a defined role.")
    for check in set(data["checks"]) - check_ids:
        add(f"The check '{check}' is not in checks.md. Add it there first.")
    if "K17" not in data["checks"]:
        add("The profile does not run K17. Add K17 (writing.md says that all profiles run it).")
    gates = data["gates"]
    for gate, allowed in GATE_VALUES.items():
        if gates.get(gate) not in allowed:
            add(f"Gate {gate} has the value '{gates.get(gate)}'. Use one of {sorted(allowed)}.")
    if "build" in data["stages"] and "pr" in data["outputs"] and gates.get("G3") != "required":
        add("The profile builds code for a PR, but G3 is not 'required'. Set G3 to 'required'.")
    expected = matrix.get(data["id"])
    actual = [str(gates.get(gate)) for gate in GATE_VALUES]
    if expected is None:
        add("The profile has no row in the gates.md table. Add a row.")
    elif expected != actual:
        add(f"The gates {actual} do not agree with gates.md {expected}. Make them the same.")
    return found


def check_links(root: Path, paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if "templates" in path.relative_to(root).parts:
            continue  # template links resolve in the target repo, not here
        for line, target in relative_links(path):
            if not (path.parent / target.split("#")[0]).resolve().exists():
                findings.append(Finding(str(path.relative_to(root)), line, CHECK,
                                        f"The link '{target}' points to no file. Fix the path."))
    return findings


def check_neutral(framework: Path) -> list[Finding]:
    """P12: core files outside adapters/ must not name a harness, a model, or a spec tool."""
    pattern = re.compile(r"\b(" + "|".join(VENDOR_NAMES) + r")\b", re.I)
    findings: list[Finding] = []
    for path in sorted(framework.rglob("*.md")):
        if "adapters" in path.relative_to(framework).parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = pattern.search(line)
            if match:
                findings.append(Finding(str(path), number, CHECK,
                                        f"The core names '{match.group(1)}' (P12). "
                                        "Move this detail to an adapter."))
    return findings


def branch_name_problems(config: dict[str, Any]) -> list[str]:
    """Name each `branches.*` value that YAML did not parse as a string (1.10 is 1.1, yes is True)."""
    branches = config.get("branches")
    if not isinstance(branches, dict):
        return []
    return [f"'branches.{key}' is {value!r}, not a YAML string. Quote the value, "
            f'for example {key}: "{value}".'
            for key, value in branches.items() if value is not None and not isinstance(value, str)]


def check_config(root: Path, framework: Path) -> list[Finding]:
    path = root / ".cornerstone" / "config.yaml"
    if not path.exists():
        return []
    findings: list[Finding] = []
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def add(message: str) -> None:
        findings.append(Finding(str(path.relative_to(root)), 1, CHECK, message))

    for problem in branch_name_problems(config):
        add(problem)
    harness = config.get("harness", "")
    if not (framework / "adapters" / f"{harness}.md").exists():
        add(f"The harness '{harness}' has no adapter file. Use a file name in adapters/.")
    profile = config.get("model_profile")
    if profile and not (framework / "adapters" / harness / "models" / f"{profile}.yaml").exists():
        add(f"The model_profile '{profile}' has no file. Use a file in adapters/{harness}/models/.")
    for name in config.get("profiles", []):
        if not (framework / "profiles" / f"{name}.md").exists():
            add(f"The profile '{name}' does not exist. Use a file name in profiles/.")
    for mode in config.get("modes_allowed", []):
        if mode not in MODES:
            add(f"The mode '{mode}' is not valid. Use one of {sorted(MODES)}.")
    for waiver in config.get("waivers", []):
        if waiver.get("gate") in {"G3", "G5"}:
            add(f"A waiver removes {waiver['gate']}. No waiver can remove G3 or G5. Remove it.")
    return findings


def _is_date(value: Any) -> bool:
    if isinstance(value, dt.date):
        return True
    try:
        dt.date.fromisoformat(str(value))
    except ValueError:
        return False
    return True


def component_problems(entry: dict[str, Any], needs_review_by: bool) -> list[str]:
    """P5 (D43): name each missing eval plan or review date of one component entry."""
    problems = []
    if "eval" not in entry:
        problems.append("has no 'eval' key (P5). Add the eval folder, or \"\" for a check.")
    elif not str(entry["eval"] or "").strip() and entry.get("kind") not in EVAL_OPTIONAL_KINDS:
        problems.append("has no eval plan (P5). Set 'eval' to its eval folder, for example "
                        f"evals/{str(entry.get('id', '')).replace('.', '-')}/.")
    if needs_review_by and not _is_date(entry.get("review_by")):
        problems.append("has no valid 'review_by' date (P5). Set it to YYYY-MM-DD.")
    return problems


def check_components(root: Path, framework: Path) -> list[Finding]:
    """P5 (D43): test the adapter component lists and, if present, the repo manifest.

    Each component needs an eval plan (empty only for a check). Each manifest entry also needs a
    review date. Render sets `review_by`, so the component lists do not have it.
    """
    paths = [(path, False) for path in sorted((framework / "adapters").glob("*/components.yaml"))]
    manifest = root / ".cornerstone" / "manifest.yaml"
    if manifest.exists():
        paths.append((manifest, True))
    findings: list[Finding] = []
    for path, needs_review_by in paths:
        text = path.read_text(encoding="utf-8")
        name = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        for entry in (yaml.safe_load(text) or {}).get("components") or []:
            component_id = entry.get("id", "?")
            match = re.search(rf"^\s*- id: {re.escape(str(component_id))}\s*$", text, re.M)
            line = text.count("\n", 0, match.start()) + 1 if match else 1
            for problem in component_problems(entry, needs_review_by):
                findings.append(Finding(name, line, CHECK,
                                        f"The component '{component_id}' {problem}"))
    return findings


def run(root: Path, framework: Path | None = None) -> list[Finding]:
    """Run all framework checks. `framework` defaults to `<root>/framework`."""
    framework = framework or root / "framework"
    if not framework.is_dir():
        return [Finding(str(root), 1, CHECK,
                        "No framework folder. Run stone from the repo root, or pass --framework.")]
    docs = [p for p in sorted(root.rglob("*.md"))
            if ".git" not in p.parts and "node_modules" not in p.parts]
    return (check_profiles(framework) + check_links(root, docs) + check_neutral(framework)
            + check_config(root, framework) + check_components(root, framework)
            + personas_check.run(root) + specs.check(root))
