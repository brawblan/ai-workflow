"""`stone upgrade`: read framework/upgrades.yaml, plan the move to a new version, and apply it."""

from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

from stone import render

FILE = Path("upgrades.yaml")
CONFIG = Path(".cornerstone/config.yaml")
KINDS = ("major", "minor", "patch")
FILE_CHANGES = ("added", "changed", "removed")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
REPO_URL = "https://github.com/brawblan/ai-workflow"  # the G3 workflow installs stone from it


class UpgradeError(Exception):
    """An input is not valid. Nothing was written."""


def parse(version: Any) -> tuple[int, ...]:
    text = str(version)
    if not VERSION.match(text):
        raise UpgradeError(f"'{text}' is not a version. Use X.Y.Z.")
    return tuple(int(part) for part in text.split("."))


def load(framework: Path) -> list[dict[str, Any]]:
    path = framework / FILE
    if not path.exists():
        raise UpgradeError(f"{path}: no file. Use a framework folder from version 1.1.0 or later.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    versions = data.get("versions") if isinstance(data, dict) else None
    if not isinstance(versions, list) or not versions:
        raise UpgradeError(f"{path}: 'versions' must be a list of releases.")
    return versions


def _kind_for(newer: tuple[int, ...], older: tuple[int, ...] | None) -> str:
    if older is None or newer[0] != older[0]:
        return "major"
    return "minor" if newer[1] != older[1] else "patch"


def problems(framework: Path) -> list[str]:
    """Return the problems of upgrades.yaml: the form, the order, and the kind of each release."""
    try:
        versions = load(framework)
    except UpgradeError as error:
        return [str(error)]
    found: list[str] = []
    parsed: list[tuple[int, ...] | None] = []
    for number, entry in enumerate(versions, 1):
        if not isinstance(entry, dict):
            found.append(f"versions item {number} must be a map.")
            parsed.append(None)
            continue
        label = f"version {entry.get('version')}"
        try:
            parsed.append(parse(entry.get("version")))
        except UpgradeError as error:
            found.append(f"versions item {number}: {error}")
            parsed.append(None)
        if entry.get("kind") not in KINDS:
            found.append(f"The {label} has kind '{entry.get('kind')}'. Use one of {list(KINDS)}.")
        if not str(entry.get("summary") or "").strip():
            found.append(f"The {label} needs a 'summary'.")
        released = entry.get("released")
        if released is not None and not isinstance(released, dt.date):
            found.append(f"The {label} needs 'released' to be a date (YYYY-MM-DD), or null.")
        if released is None and number != 1:
            found.append(f"The {label} has no release date, but it is not the newest. Only the "
                         "newest version can be unreleased.")
        found += _content_problems(label, entry)
    for number in range(len(versions) - 1):
        newer, older = parsed[number], parsed[number + 1]
        if newer is None or older is None:
            continue
        if newer <= older:
            found.append(f"The version {'.'.join(map(str, newer))} must be newer than the next "
                         "item. Put the newest version first, and use each version once.")
        elif versions[number].get("kind") != _kind_for(newer, older):
            found.append(f"The version {versions[number]['version']} is a "
                         f"{_kind_for(newer, older)} release after {versions[number + 1]['version']}, "
                         f"but its kind is '{versions[number].get('kind')}'.")
    return found


def _content_problems(label: str, entry: dict[str, Any]) -> list[str]:
    found: list[str] = []
    config = entry.get("config") or {}
    if not isinstance(config, dict):
        return [f"The {label} needs 'config' to be a map."]
    for group, keys in (("added", ("key",)), ("renamed", ("from", "to")), ("removed", ("key",))):
        items = config.get(group) or []
        if not isinstance(items, list):
            found.append(f"The {label} needs 'config.{group}' to be a list.")
            continue
        for item in items:
            if not isinstance(item, dict) or not all(str(item.get(k) or "").strip() for k in keys):
                found.append(f"The {label} has a bad item in 'config.{group}'. "
                             f"Each item needs {', '.join(keys)}.")
    if entry.get("kind") == "patch" and any(config.get(g) for g in ("added", "renamed", "removed")):
        found.append(f"The {label} is a patch release, so it cannot change the config.")
    if entry.get("kind") == "minor" and (config.get("renamed") or config.get("removed")):
        found.append(f"The {label} is a minor release, so it cannot rename or remove a config key.")
    for item in entry.get("files") or []:
        if not (isinstance(item, dict) and str(item.get("path") or "").strip()
                and item.get("change") in FILE_CHANGES):
            found.append(f"The {label} has a bad item in 'files'. Each item needs a path and a "
                         f"change: one of {list(FILE_CHANGES)}.")
    steps = entry.get("steps") or []
    if not (isinstance(steps, list) and all(isinstance(s, str) and s.strip() for s in steps)):
        found.append(f"The {label} needs 'steps' to be a list of text.")
    return found


def _has(data: Any, dotted: str) -> bool:
    for key in dotted.split("."):
        if not isinstance(data, dict) or key not in data:
            return False
        data = data[key]
    return True


def plan(root: Path, framework: Path, target: str | None) -> tuple[str, list[str], int]:
    """Return the plan text, the lines that need a person, and the exit code."""
    path = root / CONFIG
    if not path.exists():
        raise UpgradeError(f"{CONFIG}: no file. Run the setup first (add-to-a-repo.md).")
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    current = parse(config.get("framework_version"))
    versions = load(framework)
    released = [v for v in versions if v.get("released")]
    if target is None:
        if not released:
            raise UpgradeError("upgrades.yaml has no released version.")
        target = str(released[0]["version"])
    goal = parse(target)
    if str(target) not in {str(v.get("version")) for v in versions}:
        raise UpgradeError(f"The version {target} is not in upgrades.yaml.")
    if goal < current:
        raise UpgradeError(f"framework_version is {config['framework_version']}, which is newer "
                           f"than {target}. A downgrade is not supported.")
    steps = sorted((v for v in versions if current < parse(v["version"]) <= goal),
                   key=lambda v: parse(v["version"]))
    lines = [f"stone upgrade: {config['framework_version']} -> {target}"]
    actions: list[str] = []
    if not steps:
        return "\n".join(lines + ["Nothing to do. The config is at this version."]), actions, 0
    kinds = [v["kind"] for v in steps]
    biggest = "major" if "major" in kinds else "minor" if "minor" in kinds else "patch"
    lines.append(f"This is a {biggest} upgrade over {len(steps)} release(s).")
    for entry in steps:
        lines += ["", f"Version {entry['version']} ({entry['kind']}): {entry['summary']}"]
        lines += _config_lines(config, entry.get("config") or {}, actions)
        for item in entry.get("files") or []:
            note = f" - {item['note']}" if item.get("note") else ""
            lines.append(f"  file {item['change']}: {item['path']}{note}")
        lines += [f"  step: {text}" for text in entry.get("steps") or []]
    lines += ["", render_summary(root, framework, actions)]
    if actions:
        lines += ["", f"{len(actions)} action(s) need a person:"] + [f"  - {a}" for a in actions]
    return "\n".join(lines), actions, 1 if actions else 0


def _config_lines(config: dict[str, Any], changes: dict[str, Any], actions: list[str]) -> list[str]:
    lines = []
    for item in changes.get("added") or []:
        state = "present" if _has(config, item["key"]) else "not set (optional)"
        default = f", default {item['default']}" if item.get("default") is not None else ""
        note = f" - {item['note']}" if item.get("note") else ""
        lines.append(f"  config add {item['key']}{default}: {state}{note}")
    for item in changes.get("renamed") or []:
        lines.append(f"  config rename {item['from']} -> {item['to']}")
        if _has(config, item["from"]):
            actions.append(f"Rename the config key '{item['from']}' to '{item['to']}'.")
    for item in changes.get("removed") or []:
        lines.append(f"  config remove {item['key']}" + (f" - {item['note']}" if item.get("note") else ""))
        if _has(config, item["key"]):
            actions.append(f"Remove the config key '{item['key']}'.")
    return lines


def render_summary(root: Path, framework: Path, actions: list[str]) -> str:
    """Run render as a dry run, and say what it would do. The messages of render go to stderr."""
    try:
        result = render.render(root, framework, dry_run=True)
    except render.RenderError as error:
        actions.append(f"Fix the render error: {error}")
        return f"Render dry run: failed. {error}"
    if result.drift:
        actions.append("Resolve the drift in " + ", ".join(sorted(result.drift))
                       + ": restore the file, or move the change to the config.")
    return (f"Render dry run: {len(result.wrote)} would be written, {len(result.skipped)} "
            f"unchanged, {len(result.drift)} with drift.")


def tag_commit(tag: str) -> str:
    """Return the commit SHA of a framework tag, from the remote repo. Raise if git cannot find it."""
    ref, peeled = f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"  # peeled: an annotated tag's commit
    try:
        out = subprocess.run(["git", "ls-remote", REPO_URL, ref, peeled], capture_output=True,
                             text=True, timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise UpgradeError(f"git ls-remote could not read the tag {tag}: {error}") from None
    refs = {name: sha for sha, name in (line.split("\t", 1) for line in out.splitlines()
                                        if "\t" in line)}
    commit = refs.get(peeled) or refs.get(ref)
    if not commit:
        raise UpgradeError(f"The tag {tag} is not in {REPO_URL}.")
    return commit


def _set_commit(text: str, commit: str) -> str:
    """Set framework_commit in the config text. Add the line after framework_version if it is missing."""
    line = f'framework_commit: "{commit}"  # the commit of the tag. G3 installs stone from it.'
    new, count = re.subn(r"^framework_commit:.*$", line, text, count=1, flags=re.M)
    if count:
        return new
    return re.sub(r"^(framework_version:.*)$", rf"\g<1>\n{line}", text, count=1, flags=re.M)


def apply(root: Path, framework: Path, target: str | None,
          resolve: Callable[[str], str] = tag_commit) -> list[str]:
    """Set framework_version and framework_commit, then render. Stop if a person must act first."""
    _, actions, _ = plan(root, framework, target)
    if actions:
        raise UpgradeError("Not applied. " + str(len(actions)) + " action(s) need a person first. "
                           "Run stone upgrade to see them.")
    versions = load(framework)
    if target is None:
        target = str([v for v in versions if v.get("released")][0]["version"])
    path = root / CONFIG
    text = path.read_text(encoding="utf-8")
    new, count = re.subn(r"^(framework_version:[ \t]*)[^\s#]+", rf"\g<1>{target}", text,
                         count=1, flags=re.M)
    if not count:
        raise UpgradeError(f"{CONFIG}: no 'framework_version:' line to change.")
    try:
        new = _set_commit(new, resolve(f"v{target}"))
    except UpgradeError as error:
        if re.search(r"^framework_commit:", text, flags=re.M):
            raise  # the old commit would install the old stone: stop before a write
        print(f"warning: {error} framework_commit is not set, so G3 installs stone from the tag.",
              file=sys.stderr)
    path.write_text(new, encoding="utf-8")
    result = render.render(root, framework)
    return result.wrote + result.drift
