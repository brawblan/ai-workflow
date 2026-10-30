"""K23: report a new package in a manifest that the PR body does not name (D90)."""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from stone import evidence_check
from stone.findings import Finding

CHECK = "K23"
SECTION = "Dependencies"
MANIFESTS = ["package.json", "pyproject.toml", "requirements*.txt"]
NODE_KEYS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalize(name: str) -> str:
    """Return the package name in the form that the index compares (PEP 503 for Python)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _python_names(requirements: list[Any]) -> set[str]:
    names = set()
    for item in requirements:
        match = REQUIREMENT.match(str(item))
        if match:
            names.add(_normalize(match.group(1)))
    return names


def package_names(name: str, text: str) -> set[str]:
    """Return the package names in a manifest. A file that does not parse has none."""
    base = name.rsplit("/", 1)[-1]
    try:
        if base == "package.json":
            data = json.loads(text)
            return {key.lower() for field in NODE_KEYS for key in (data.get(field) or {})}
        if base == "pyproject.toml":
            data = tomllib.loads(text)
            project = data.get("project") or {}
            items = list(project.get("dependencies") or [])
            for group in (project.get("optional-dependencies") or {}).values():
                items += list(group)
            for group in (data.get("dependency-groups") or {}).values():
                items += [entry for entry in group if isinstance(entry, str)]
            names = _python_names(items)
            poetry = (data.get("tool") or {}).get("poetry") or {}
            names |= {_normalize(key) for key in poetry.get("dependencies") or {}} - {"python"}
            return names
    except (ValueError, AttributeError, TypeError):
        return set()
    lines = [line for line in text.splitlines() if not line.lstrip().startswith(("#", "-"))]
    return _python_names(lines)


def is_manifest(path: str) -> bool:
    return any(fnmatch.fnmatch(path.rsplit("/", 1)[-1], pattern) for pattern in MANIFESTS)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def changed_manifests(root: Path, base: str) -> list[tuple[str, str]]:
    """Return (old path, new path) for each added, changed, or renamed manifest."""
    run = _git(root, "diff", "-z", "--name-status", "--diff-filter=AMR", f"{base}...HEAD")
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip() or f"git diff {base}...HEAD failed")
    fields, pairs = run.stdout.split("\0"), []
    while len(fields) > 1:
        status = fields.pop(0)
        old = fields.pop(0)
        new = fields.pop(0) if status.startswith("R") else old
        if is_manifest(new):
            pairs.append((old, new))
    return pairs


def new_packages(root: Path, base: str) -> dict[str, set[str]]:
    """Return {manifest path: new package names} for each changed manifest."""
    found = {}
    for old_path, path in changed_manifests(root, base):
        old = _git(root, "show", f"{base}:{old_path}")
        before = package_names(old_path, old.stdout) if old.returncode == 0 else set()
        file = root / path
        text = file.read_text(encoding="utf-8", errors="replace") if file.is_file() else ""
        after = package_names(path, text)
        if after - before:
            found[path] = after - before
    return found


def dependencies_section(body: str) -> str:
    """Return the text of the Dependencies section of the PR body, or '' if it has none."""
    lines = body.splitlines()
    found = evidence_check.headings(lines)
    texts = [evidence_check.section_body(lines, heading, found, set())
             for heading in found if heading.name == SECTION.lower()]
    return "\n".join(texts)


def check(root: Path, base: str, body: str) -> list[Finding]:
    """Return a K23 finding for each new package that the Dependencies section does not name."""
    section = dependencies_section(body)
    words = {_normalize(re.sub(r"(?<=.)@[^@/]*$", "", word.strip("./-")))  # left-pad@1.3.0
             for word in re.findall(r"[@\w./-]+", section)}
    findings = []
    for manifest, names in sorted(new_packages(root, base).items()):
        for name in sorted(names):
            if _normalize(name) not in words:
                findings.append(Finding(
                    manifest, 1, CHECK,
                    f"The new package '{name}' is not in the '{SECTION}' section of the PR "
                    f"body. Add a '## {SECTION}' section. Name each new package with the "
                    "reason and the source."))
    return findings
