"""`stone render`: write the generated files and the manifest into a target repo."""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any

import yaml

from stone import framework_check
from stone.markdown import split_frontmatter

CONFIG = Path(".cornerstone/config.yaml")
MANIFEST = Path(".cornerstone/manifest.yaml")
REQUIRED_FIELDS = ["framework_version", "harness", "model_profile", "profiles", "owners.default"]
SUPPORTED_PROFILES = {"single-ticket"}
REVIEW_MONTHS = 6
CONFIG_SECTION = {"command": "commands", "paths": "paths", "branch": "branches"}


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


def load_profiles(framework: Path, names: list[str]) -> list[dict[str, Any]]:
    profiles = []
    for name in names:
        if name not in SUPPORTED_PROFILES:
            print(f"skipped profile {name}: render does not support it yet", file=sys.stderr)
            continue
        text = (framework / "profiles" / f"{name}.md").read_text(encoding="utf-8")
        profiles.append(split_frontmatter(text)[0])
    return profiles


def template_values(config: dict[str, Any], model: str) -> dict[str, str]:
    """Return the repo facts that templates can use. TODO values are left out on purpose."""
    values = {"model": model, "paths_plans": "docs/plans/"}
    for key, value in (config.get("commands") or {}).items():
        values[f"command_{key}"] = str(value)
    for key, value in (config.get("paths") or {}).items():
        # A list becomes inline code items. A single path stays plain, so a template can extend it.
        values[f"paths_{key}"] = (", ".join(f"`{item}`" for item in value)
                                  if isinstance(value, list) else str(value))
    for key, value in (config.get("branches") or {}).items():
        values[f"branch_{key}"] = str(value)
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
    roles = {role for profile in load_profiles(framework, config["profiles"])
             for role in profile["roles"]}
    role_models = model_profile["defaults"]["role_models"]

    components = []
    for entry in registry:
        if entry["kind"] == "role" and entry["role"] not in roles:
            continue
        model = role_models.get(entry.get("role", ""), "")
        values = template_values(config, model)
        template = (harness / "templates" / entry["template"]).read_text(encoding="utf-8")
        try:
            content = Template(template).substitute(values)
        except KeyError as error:
            prefix, _, key = error.args[0].partition("_")
            raise RenderError(f"The template {entry['template']} needs '${error.args[0]}'. Add "
                              f"{CONFIG_SECTION.get(prefix, prefix)}.{key} to {CONFIG}, "
                              "without a TODO value.") from None
        components.append(Component(entry["id"], entry["kind"], entry["purpose"],
                                    entry["principle"], entry["eval"],
                                    {entry["target"]: content}))
    unknown = roles - {entry.get("role") for entry in registry}
    if unknown:
        raise RenderError(f"The adapter has no role file for {sorted(unknown)}. Add a template.")
    return components


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
    components = build_components(framework, config)
    manifest = load_manifest(root)
    old_entries = {entry["id"]: entry for entry in manifest.get("components", [])}

    result = Result()
    entries = [entry for entry in manifest.get("components", []) if entry.get("source") == "repo"]
    to_write: dict[str, str] = {}
    for component in components:
        old = old_entries.get(component.id)
        paths = sorted(component.files)
        disk = _disk_files(root, paths)
        if disk == component.files:
            result.skipped.extend(paths)
        elif not disk or (old and len(disk) == len(paths) and content_hash(disk) == old["hash"]):
            to_write.update(component.files)  # new, or unchanged since the last render
            result.wrote.extend(paths)
        else:
            result.drift.extend(paths)  # a human changed or removed a generated file
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
