"""`stone check`: validate the framework files and, if present, the repo config."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

import yaml

from stone import personas_check, results, specs
from stone.findings import Finding
from stone.markdown import link_file, relative_links, split_frontmatter, table_rows

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


# The files that Cornerstone owns (issue #124). The link check reads only these by default.
LINK_FILES = ["AGENTS.md", "CLAUDE.md"]
LINK_FOLDERS = ["constitution", ".cornerstone"]
LINK_MODES = ("default", "all")


def link_config_paths(root: Path) -> tuple[list[str], list[str]]:
    """Return (paths, problems) from `checks.links.paths` in the repo config."""
    path = root / specs.CONFIG
    if not path.exists():
        return [], []
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return [], []  # check_config reports a config that is not valid
    checks = config.get("checks") if isinstance(config, dict) else None
    links = checks.get("links") if isinstance(checks, dict) else None
    value = links.get("paths") if isinstance(links, dict) else None
    if value is None:
        return [], []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return [], ["'checks.links.paths' must be a list of file and folder paths."]
    resolved = root.resolve()
    outside = [item for item in value if not (resolved / item).resolve().is_relative_to(resolved)]
    if outside:
        return [], [f"'checks.links.paths' has '{outside[0]}', which is outside the repo. "
                    "Use a path in the repo."]
    return value, []


def link_scope(root: Path, framework: Path | None = None, mode: str = "default") -> list[Path]:
    """Return the Markdown files for the link check.

    `all`: each Markdown file in the repo. `default`: the files that Cornerstone owns
    (`AGENTS.md`, `CLAUDE.md`, `constitution/`, `.cornerstone/`, the plans and specs folders, the
    framework folder), and the paths in `checks.links.paths`.
    """
    root = root.resolve()
    if mode == "all":
        return [p for p in sorted(root.rglob("*.md"))
                if ".git" not in p.parts and "node_modules" not in p.parts]
    targets = [root / name for name in LINK_FILES + LINK_FOLDERS]
    for key in ("plans", "specs"):
        try:
            targets.append(specs.config_path(root, key))
        except specs.SpecError:
            pass  # K19 reports a path that is not valid
    if framework and framework.resolve().is_relative_to(root):
        targets.append(framework.resolve())
    targets += [root / item for item in link_config_paths(root)[0]]
    files: set[Path] = set()
    for target in targets:
        if target.is_dir():
            files.update(p for p in target.rglob("*.md") if ".git" not in p.parts)
        elif target.suffix == ".md" and target.is_file():
            files.add(target)
    return sorted(files)


def link_target(root: Path, path: Path, target: str) -> Path:
    """Return the file that a link points to. A link that starts with / starts at the repo root."""
    name = link_file(target)
    if name.startswith("/"):
        return (root / name.lstrip("/")).resolve()
    return (path.parent / name).resolve()


def check_links(root: Path, paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    root = root.resolve()
    for path in paths:
        path = path.resolve()
        if "templates" in path.relative_to(root).parts:
            continue  # template links resolve in the target repo, not here
        for line, target in relative_links(path):
            if link_file(target) and not link_target(root, path, target).exists():
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


DELIVERY_MODES = ("ci", "local")
HARNESS_DIRS = (".claude/", ".cornerstone/")  # the hook protects these for every role
FOLDER_DEFAULTS = {"plans": "docs/plans/", "reports": "docs/reports/"}


def _folder_prefix(value: Any) -> str:
    """Return the folder of a path or glob, with no './' and no trailing '/'."""
    text = re.split(r"[*?\[]", str(value).strip())[0]  # a glob counts up to its first wildcard
    if text != str(value).strip():
        text = text.rpartition("/")[0]
    return text.removeprefix("./").rstrip("/")


def _paths(value: Any) -> list[str]:
    return [str(item) for item in (value if isinstance(value, list) else [value]) if item]


def protected_path_problems(config: dict[str, Any]) -> list[str]:
    """Return a problem for each plans or reports folder that overlaps a protected path.

    The hook blocks a role that writes to a protected path, so the implementer could not write
    its decision log, and the investigator could not write a report there.
    """
    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    protected = [(item, _folder_prefix(item)) for item in
                 [*HARNESS_DIRS, *_paths(paths.get("tests")), *_paths(paths.get("checks"))]]
    problems = []
    for key, default in FOLDER_DEFAULTS.items():
        for folder in _paths(paths.get(key)) or [default]:
            mine = _folder_prefix(folder)
            for item, theirs in protected:
                if not theirs:
                    continue  # a glob with no folder part: it cannot be compared
                if mine == theirs or mine.startswith(theirs + "/") or theirs.startswith(mine + "/"):
                    problems.append(
                        f"'paths.{key}' ({folder}) overlaps the protected path '{item}'. The hook "
                        f"blocks the role that writes there. Use a folder outside {item}, "
                        f"for example {default}.")
    return problems


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
    for problem in link_config_paths(root)[1]:
        add(problem)
    delivery = config.get("delivery", "ci")
    if delivery not in DELIVERY_MODES:
        add(f"The delivery '{delivery}' is not valid. Use one of {list(DELIVERY_MODES)}.")
    for problem in protected_path_problems(config):
        add(problem)
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


def component_problems(entry: dict[str, Any], is_manifest: bool,
                       tested: dict[str, list[str]] | None = None) -> list[str]:
    """P5 (D43, D50): name each missing item of one component entry.

    An adapter component list needs only the eval plan. A manifest entry also needs a review date,
    an owner, and (if it has a result file) the model of each result in `models_tested`.
    `tested` maps a component id to the models in `evals/results/`.
    """
    problems = []
    if "eval" not in entry:
        problems.append("has no 'eval' key (P5). Add the eval folder, or \"\" for a check.")
    elif not str(entry["eval"] or "").strip() and entry.get("kind") not in EVAL_OPTIONAL_KINDS:
        problems.append("has no eval plan (P5). Set 'eval' to its eval folder, for example "
                        f"evals/{str(entry.get('id', '')).replace('.', '-')}/.")
    if not is_manifest:
        return problems
    if not _is_date(entry.get("review_by")):
        problems.append("has no valid 'review_by' date (P5). Set it to YYYY-MM-DD.")
    if not str(entry.get("owner") or "").strip():
        problems.append("has no owner (P5). Set 'owners.default' in .cornerstone/config.yaml, "
                        "then run stone render.")
    listed = entry.get("models_tested")
    listed = listed if isinstance(listed, list) else []
    missing = [model for model in (tested or {}).get(str(entry.get("id")), [])
               if model not in listed]
    if missing:
        problems.append(f"has a result file for the model {', '.join(missing)} in "
                        "evals/results/, but 'models_tested' does not list it (P5). "
                        "Run stone render.")
    return problems


def check_components(root: Path, framework: Path) -> list[Finding]:
    """P5 (D43, D50): test the adapter component lists and, if present, the repo manifest.

    Each component needs an eval plan (empty only for a check). Each manifest entry also needs a
    review date, an owner, and the models of its result files in `models_tested`. Render sets
    these three items, so the component lists do not have them.
    """
    paths = [(path, False) for path in sorted((framework / "adapters").glob("*/components.yaml"))]
    manifest = root / ".cornerstone" / "manifest.yaml"
    if manifest.exists():
        paths.append((manifest, True))
    tested = results.result_models(root)
    findings: list[Finding] = []
    for path, is_manifest in paths:
        text = path.read_text(encoding="utf-8")
        name = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        for entry in (yaml.safe_load(text) or {}).get("components") or []:
            component_id = entry.get("id", "?")
            match = re.search(rf"^\s*- id: {re.escape(str(component_id))}\s*$", text, re.M)
            line = text.count("\n", 0, match.start()) + 1 if match else 1
            for problem in component_problems(entry, is_manifest, tested):
                findings.append(Finding(name, line, CHECK,
                                        f"The component '{component_id}' {problem}"))
    return findings


def run(root: Path, framework: Path | None = None, links: str = "default") -> list[Finding]:
    """Run all framework checks. `framework` defaults to `<root>/framework`.

    `links` is `default` (the Cornerstone files) or `all` (each Markdown file) for the link check.
    """
    framework = framework or root / "framework"
    if not framework.is_dir():
        return [Finding(str(root), 1, CHECK,
                        "No framework folder. Run stone from the repo root, or pass --framework.")]
    docs = link_scope(root, framework, links)
    return (check_profiles(framework) + check_links(root, docs) + check_neutral(framework)
            + check_config(root, framework) + check_components(root, framework)
            + personas_check.run(root) + specs.check(root))
