"""`stone render`: write the generated files and the manifest into a target repo."""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any

import yaml

from stone import framework_check, triggers
from stone.markdown import split_frontmatter

CONFIG = Path(".cornerstone/config.yaml")
MANIFEST = Path(".cornerstone/manifest.yaml")
REQUIRED_FIELDS = ["framework_version", "harness", "model_profile", "profiles", "owners.default"]
REVIEW_MONTHS = 6
CONFIG_SECTION = {"command": "commands", "paths": "paths", "branch": "branches", "limit": "limits"}
PLACEHOLDER_HINT = {"tests_json": "paths.tests and paths.checks",
                    "protected_json": "paths.tests and paths.checks"}
MODEL_VALUES = {"instruction_file_max_lines"}  # template values from `defaults` in the model profile
FOLDER_DEFAULTS = {"plans": "docs/plans/", "specs": "docs/specs/", "reports": "docs/reports/"}
ALWAYS_PROTECTED = [".claude/", ".cornerstone/"]  # the hook, the check, and the harness settings
K14_SINCE = (0, 5, 0)  # the first framework tag with `stone check-evidence`
DEFAULT_PR_LINES = 600  # D4, customization.md
BLOCKS = ["check_steps"]  # placeholders that hold whole lines; render removes an empty one (D29)


class RenderError(Exception):
    """An input is not valid. Nothing was written."""


@dataclass
class Component:
    id: str
    kind: str
    purpose: str
    principle: list[str]
    eval: str
    files: dict[str, str]  # target path -> rendered content
    merge: bool = False  # True: a JSON fragment to merge into a shared file

    @property
    def hash(self) -> str:
        return content_hash(self.files)


@dataclass
class Result:
    wrote: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 2 if self.drift else 0


def content_hash(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(f"{path}\0{files[path]}\0".encode("utf-8"))
    return digest.hexdigest()


def _get(data: dict[str, Any], dotted: str) -> Any:
    value: Any = data
    for key in dotted.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def load_config(root: Path, framework: Path) -> dict[str, Any]:
    path = root / CONFIG
    if not path.exists():
        raise RenderError(f"{CONFIG}: no file. Write the repo config first (customization.md).")
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for name in REQUIRED_FIELDS:
        value = _get(config, name)
        if value in (None, "", []):
            raise RenderError(f"{CONFIG}: '{name}' has no value. Add it.")
        if "TODO(" in str(value):
            raise RenderError(f"{CONFIG}: '{name}' is a TODO value. Fill it.")
    findings = framework_check.check_config(root, framework)
    if findings:
        raise RenderError(f"{findings[0].path}: {findings[0].message}")
    return config


def warn_old_framework(version: Any) -> None:
    """Warn if the framework tag has no `stone check-evidence`. The G3 workflow installs it."""
    try:
        parts = tuple(int(part) for part in str(version).split("."))
    except ValueError:
        return
    if parts < K14_SINCE:
        print(f"warning: framework_version {version} is not a tag with 'stone check-evidence'. "
              "The K14 step in the G3 workflow fails. Use a full tag, 0.5.0 or later.",
              file=sys.stderr)


def load_profiles(framework: Path, names: list[str],
                  adapter_roles: set[str]) -> list[dict[str, Any]]:
    """Return the selected profiles. Skip a profile with a role that the adapter has no file for."""
    profiles = []
    for name in names:
        text = (framework / "profiles" / f"{name}.md").read_text(encoding="utf-8")
        profile = split_frontmatter(text)[0]
        missing = sorted(set(profile["roles"]) - adapter_roles)
        if missing:
            print(f"skipped profile {name}: the adapter has no role file for {missing}",
                  file=sys.stderr)
            continue
        profiles.append(profile)
    return profiles


def needed(entry: dict[str, Any], profiles: list[dict[str, Any]]) -> bool:
    """Return True if a selected profile needs the component (D24)."""
    if entry["kind"] == "role":
        return any(entry["role"] in profile["roles"] for profile in profiles)
    return bool(profiles_that_need(entry, profiles))


def profiles_that_need(entry: dict[str, Any], profiles: list[dict[str, Any]]) -> list[str]:
    """Return the IDs of the profiles that match the `when` of a component or a step."""
    when = entry.get("when") or {}
    if "gate" in when:
        return [profile["id"] for profile in profiles
                if profile["gates"].get(when["gate"], "skip") != "skip"]
    if "check" in when:
        return [profile["id"] for profile in profiles if when["check"] in profile["checks"]]
    return [profile["id"] for profile in profiles]


def size_limits(config: dict[str, Any], profiles: list[dict[str, Any]]) -> dict[str, int]:
    """Return the K7 limit of each selected profile with K7 (D27). The repo limit only tightens."""
    repo = _get(config, "limits.pr_changed_lines")
    if repo is not None and (isinstance(repo, bool) or not isinstance(repo, int) or repo < 1):
        raise RenderError(f"{CONFIG}: 'limits.pr_changed_lines' must be a whole number above 0.")
    limits = {}
    for profile in profiles:
        if "K7" in profile["checks"]:
            own = (profile.get("limits") or {}).get("pr_changed_lines", DEFAULT_PR_LINES)
            limits[profile["id"]] = min(own, repo) if repo else own
    return limits


def one_folder(value: Any, key: str = "plans") -> str:
    """Return a path as one folder that ends with '/'. Templates add the file name to it."""
    if isinstance(value, list):
        if len(value) != 1:
            raise RenderError(f"{CONFIG}: 'paths.{key}' must be one folder, not {len(value)}.")
        value = value[0]
    folder = str(value or FOLDER_DEFAULTS[key]).strip()
    return folder if folder.endswith("/") else folder + "/"


def template_values(config: dict[str, Any], model: str) -> dict[str, str]:
    """Return the repo facts that templates can use. TODO values are left out on purpose."""
    # The framework tag. The G3 workflow installs stone from it.
    values = {"model": model, "framework_version": str(config.get("framework_version", ""))}
    for key, value in (config.get("commands") or {}).items():
        if value is not None and str(value).strip():  # an empty command has no value
            values[f"command_{key}"] = str(value)
    for key, value in (config.get("paths") or {}).items():
        # A list becomes inline code items. A single path stays plain, so a template can extend it.
        values[f"paths_{key}"] = (", ".join(f"`{item}`" for item in value)
                                  if isinstance(value, list) else str(value))
    for key, value in (config.get("branches") or {}).items():
        values[f"branch_{key}"] = str(value)
    for key, value in (config.get("limits") or {}).items():
        if value is not None and str(value).strip():  # an empty limit has no value
            values[f"limit_{key}"] = str(value)
    values["paths_plans"] = one_folder(_get(config, "paths.plans"))
    values["paths_specs"] = one_folder(_get(config, "paths.specs"), "specs")
    values["paths_reports"] = one_folder(_get(config, "paths.reports"), "reports")
    values["plans_json"] = json.dumps([values["paths_plans"]])
    values["reports_json"] = json.dumps([values["paths_reports"]])
    values["harness_json"] = json.dumps(ALWAYS_PROTECTED)
    tests = list(_get(config, "paths.tests") or [])
    checks = list(_get(config, "paths.checks") or [])
    if tests and checks:
        values["tests_json"] = json.dumps(tests)
        protected = tests + checks + ALWAYS_PROTECTED + [values["paths_specs"]]
        values["protected_json"] = json.dumps(sorted(set(protected)))
    return {key: value for key, value in values.items() if "TODO(" not in value}


def build_components(framework: Path, config: dict[str, Any]) -> list[Component]:
    harness = framework / "adapters" / config["harness"]
    registry_path = harness / "components.yaml"
    if not registry_path.exists():
        raise RenderError(f"The harness '{config['harness']}' has no components.yaml. "
                          "Render supports only adapters with templates.")
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))["components"]
    model_profile = yaml.safe_load(
        (harness / "models" / f"{config['model_profile']}.yaml").read_text(encoding="utf-8"))
    if model_profile.get("status") != "active":
        print(f"warning: model profile {model_profile['id']} has status "
              f"'{model_profile.get('status')}', not 'active'", file=sys.stderr)
    adapter_roles = {entry["role"] for entry in registry if entry["kind"] == "role"}
    profiles = load_profiles(framework, config["profiles"], adapter_roles)
    defaults = model_profile["defaults"]
    model_values = {name: str(defaults[name]) for name in MODEL_VALUES
                    if defaults.get(name) not in (None, "")}

    # A component with `ci_step` adds a step to the G3 workflow, only if it is rendered.
    steps: dict[str, str | None] = {step_name(entry["id"]): None
                                    for entry in registry if entry.get("ci_step")}
    limits_json = json.dumps(size_limits(config, profiles), sort_keys=True)
    base_values = {**template_values(config, ""), **model_values,
                   "size_limits_json": limits_json}
    for entry in registry:
        if entry.get("ci_step") and needed(entry, profiles):
            steps[step_name(entry["id"])] = substitute(harness, entry["ci_step"], base_values,
                                                       steps, config)

    components = []
    for entry in registry:
        if "trigger" in entry or not needed(entry, profiles):
            continue
        model = defaults["role_models"].get(entry.get("role", ""), "")
        values = {**template_values(config, model), **model_values,
                  "size_limits_json": limits_json,
                  **{name: step for name, step in steps.items() if step is not None}}
        for block in BLOCKS:
            values.setdefault(block, "")
        if entry.get("steps"):
            values["check_steps"] = render_steps(harness, entry["steps"], profiles, values, config)
        content = substitute(harness, entry["template"], values, steps, config)
        components.append(Component(entry["id"], entry["kind"], entry["purpose"],
                                    entry["principle"], entry["eval"],
                                    {entry["target"]: content}, entry.get("merge") == "json"))
    try:
        components.extend(trigger_components(framework, harness, registry, profiles, config,
                                             defaults["role_models"]))
    except triggers.TriggerError as error:
        raise RenderError(str(error)) from None
    return components


def trigger_components(framework: Path, harness: Path, registry: list[dict[str, Any]],
                       profiles: list[dict[str, Any]], config: dict[str, Any],
                       role_models: dict[str, str]) -> list[Component]:
    """Return one workflow for each profile trigger that is not `command` (D31)."""
    entries = {entry["trigger"]: entry for entry in registry if "trigger" in entry}
    found = triggers.profile_triggers(profiles)
    # A value that one entry sets is empty in the others, so each template can use it.
    defaults = {key: "" for entry in entries.values() for key in (entry.get("values") or {})}
    components, targets = [], []
    for trigger in triggers.supported(found, set(entries)):
        entry = entries[trigger.key]
        values = template_values(config, "")
        values.update(defaults)
        values.update({key: str(value) for key, value in (entry.get("values") or {}).items()})
        values.update(triggers.values(trigger, found, role_models))
        text = (harness / "templates" / entry["template"]).read_text(encoding="utf-8")
        for name, part in (entry.get("parts") or {}).items():
            text = triggers.insert_block(
                text, name, (harness / "templates" / part).read_text(encoding="utf-8"))
        steps = triggers.flow_steps(framework, trigger.profile["id"]).replace("$", "$$")
        text = triggers.insert_block(text, "profile_steps", steps)
        component_id = f"{entry['id']}.{trigger.profile['id']}"
        target = fill(entry["target"], entry["template"], values, config)
        targets.append((trigger.text, target))
        components.append(Component(component_id, entry["kind"], entry["purpose"],
                                    entry["principle"], entry["eval"],
                                    {target: fill(text, entry["template"], values, config)}))
    triggers.check_targets(targets)
    return components


def render_steps(harness: Path, steps: list[dict[str, Any]], profiles: list[dict[str, Any]],
                 values: dict[str, str], config: dict[str, Any]) -> str:
    """Return the optional steps that a selected profile needs, as one block of lines (D29).

    A step with a `command` needs that key in `commands` of the repo config. If the key has no
    value, render skips the step and warns: the profile lists the check, but the repo cannot run it.
    """
    blocks = []
    for step in steps:
        need = profiles_that_need(step, profiles)
        if not need:
            continue
        step_values = dict(values, step_name=step.get("name", step["id"]))
        command = step.get("command")
        if command:
            if f"command_{command}" not in values:
                check = (step.get("when") or {}).get("check", step["id"])
                subject = (f"profile {need[0]} lists" if len(need) == 1
                           else f"profiles {', '.join(need)} list")
                print(f"warning: {subject} {check}, but {CONFIG} has no "
                      f"commands.{command}. The G3 workflow has no {check} step. Add the "
                      "command and render again.", file=sys.stderr)
                continue
            step_values["step_command"] = values[f"command_{command}"]
        text = substitute(harness, step["template"], step_values, {}, config)
        blocks.append("\n" + text.rstrip("\n"))
    return "\n".join(blocks)


def step_name(component_id: str) -> str:
    """Return the placeholder of a component's G3 step: `check.k15` gives `ci_step_check_k15`."""
    return "ci_step_" + re.sub(r"[^a-z0-9]", "_", component_id.lower())


def substitute(harness: Path, template_name: str, values: dict[str, str],
               steps: dict[str, str | None], config: dict[str, Any]) -> str:
    """Fill one template. Remove the line of each step that is not rendered, or empty block."""
    template = (harness / "templates" / template_name).read_text(encoding="utf-8")
    for name, step in steps.items():
        if step is None:
            template = template.replace(f"${name}\n", "").replace(f"${{{name}}}\n", "")
    for block in BLOCKS:
        if not values.get(block):
            template = re.sub(rf"^\$(?:{block}|\{{{block}\}})\n", "", template, flags=re.M)
    return fill(template, template_name, values, config)


def fill(template: str, template_name: str, values: dict[str, str],
         config: dict[str, Any]) -> str:
    """Substitute the values into a template text. Name the missing fact in the error."""
    try:
        return Template(template).substitute(values)
    except ValueError as error:
        raise RenderError(f"The template {template_name} is not valid: {error}.") from None
    except KeyError as error:
        name = error.args[0]
        if name in MODEL_VALUES:
            raise RenderError(f"The template {template_name} needs '${name}'. Add "
                              f"defaults.{name} to the model profile "
                              f"{config['model_profile']}.") from None
        prefix, _, key = name.partition("_")
        hint = PLACEHOLDER_HINT.get(name, f"{CONFIG_SECTION.get(prefix, prefix)}.{key}")
        raise RenderError(f"The template {template_name} needs '${name}'. Add {hint} "
                          f"to {CONFIG}, without a TODO value.") from None


def add_months(day: dt.date, months: int) -> dt.date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    return data or {"components": []}


def _disk_files(root: Path, paths: list[str]) -> dict[str, str]:
    """Return the content of each path that exists on disk."""
    return {path: (root / path).read_text(encoding="utf-8")
            for path in paths if (root / path).exists()}


def _file_state(disk: dict[str, str], component: Component, old: dict[str, Any] | None) -> str:
    if disk == component.files:
        return "skipped"
    if not disk or (old and len(disk) == len(component.files)
                    and content_hash(disk) == old["hash"]):
        return "wrote"  # new, or unchanged since the last render
    return "drift"  # a person changed, removed, or wrote a generated file


def _contains(data: Any, fragment: Any) -> bool:
    if isinstance(fragment, dict):
        return isinstance(data, dict) and all(
            key in data and _contains(data[key], value) for key, value in fragment.items())
    if isinstance(fragment, list):
        return isinstance(data, list) and all(item in data for item in fragment)
    return data == fragment


def _merge(data: dict[str, Any], fragment: dict[str, Any]) -> None:
    for key, value in fragment.items():
        if isinstance(value, dict):
            _merge(data.setdefault(key, {}), value)
        elif isinstance(value, list):
            items = data.setdefault(key, [])
            items.extend(item for item in value if item not in items)
        else:
            data[key] = value


def _merge_json(root: Path, path: str, fragment_text: str) -> tuple[bool, str]:
    """Return (the file has the fragment, the file text with the fragment merged in)."""
    target = root / path
    try:
        data = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    except json.JSONDecodeError as error:
        raise RenderError(f"{path} is not valid JSON: {error}. Fix the file.") from None
    fragment = json.loads(fragment_text)
    present = _contains(data, fragment)
    _merge(data, fragment)
    return present, json.dumps(data, indent=2) + "\n"


def _manifest_entry(component: Component, old: dict[str, Any] | None, config: dict[str, Any],
                    today: dt.date) -> dict[str, Any]:
    return {
        "id": component.id,
        "kind": component.kind,
        "purpose": component.purpose,
        "principle": component.principle,
        "source": "framework",
        "owner": old["owner"] if old else config["owners"]["default"],
        "eval": component.eval,
        "models_tested": old.get("models_tested", []) if old else [],
        "added": str(old["added"]) if old else today.isoformat(),
        "review_by": str(old["review_by"]) if old else add_months(today, REVIEW_MONTHS).isoformat(),
        "files": sorted(component.files),
        "hash": component.hash,
    }


def render(root: Path, framework: Path | None = None, dry_run: bool = False,
           today: dt.date | None = None) -> Result:
    """Render all components. Raise RenderError before any write if an input is not valid."""
    framework = framework or root / "framework"
    today = today or dt.date.today()
    config = load_config(root, framework)
    warn_old_framework(config["framework_version"])
    components = build_components(framework, config)
    manifest = load_manifest(root)
    old_entries = {entry["id"]: entry for entry in manifest.get("components", [])}

    result = Result()
    entries = [entry for entry in manifest.get("components", []) if entry.get("source") == "repo"]
    to_write: dict[str, str] = {}
    for component in components:
        old = old_entries.get(component.id)
        paths = sorted(component.files)
        if component.merge:
            present, merged = _merge_json(root, paths[0], component.files[paths[0]])
            write = {paths[0]: merged}
            state = ("skipped" if present
                     else "drift" if old and old["hash"] == component.hash  # entry removed
                     else "wrote")
        else:
            write = component.files
            state = _file_state(_disk_files(root, paths), component, old)
        getattr(result, state).extend(paths)
        if state == "wrote":
            to_write.update(write)
        if state == "drift":
            if old:
                entries.append(old)
            continue
        entries.append(_manifest_entry(component, old, config, today))
    rendered_ids = {component.id for component in components}
    for entry_id, entry in old_entries.items():
        if entry.get("source") != "repo" and entry_id not in rendered_ids:
            print(f"stale {entry_id}: no longer rendered. Delete its files by hand.",
                  file=sys.stderr)

    new_manifest = {"framework_version": str(config["framework_version"]),
                    "components": sorted(entries, key=lambda entry: entry["id"])}
    manifest_text = yaml.safe_dump(new_manifest, sort_keys=False, allow_unicode=True)
    manifest_path = root / MANIFEST
    if not manifest_path.exists() or manifest_path.read_text(encoding="utf-8") != manifest_text:
        to_write[str(MANIFEST)] = manifest_text
        result.wrote.append(str(MANIFEST))
    else:
        result.skipped.append(str(MANIFEST))

    wrote_label = "would write" if dry_run else "wrote"
    for label, paths in ((wrote_label, result.wrote), ("skipped", result.skipped),
                         ("drift", result.drift)):
        for path in paths:
            print(f"{label} {path}", file=sys.stderr)
    if not dry_run:
        _write(root, to_write)
    return result


def _write(root: Path, files: dict[str, str]) -> None:
    written: list[str] = []
    for path, content in files.items():
        target = root / path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as error:
            raise RenderError(f"Cannot write {path}: {error}. Files written: {written}. "
                              "Run render again to complete the work.") from None
        written.append(path)
