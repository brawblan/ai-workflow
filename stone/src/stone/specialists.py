"""Specialist reviews (#123): the config, the trigger match, and the findings check."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stone import evidence_check, personas_check
from stone.findings import Finding

ID_PREFIX = "specialist."
DOC = ".cornerstone/specialists.md"
MATCH_MODULE = ".cornerstone/lib/path_match.py"  # render writes it; the hook and K6 import it
STAGES = ("verify",)  # after the tester, before the reviewer
KEYS = {"id", "run", "when", "stage", "blocks", "owner", "eval"}
WHEN_KEYS = ("paths", "personas_with", "labels")
SLUG = re.compile(r"^[a-z][a-z0-9-]*$")
HIGH = re.compile(r"^[\s>*_`-]*(?:\d+[.)]\s*)?[*_`]*severity[*_`]*\s*[:=][*_`\s]*high\b",
                  re.I | re.M)
CHECK = "K20"
TICKET_LINE = re.compile(r"^Ticket:[ \t]*#?([A-Za-z0-9][A-Za-z0-9._-]*)[ \t]*$", re.I | re.M)
PERSONAS_LINE = re.compile(r"^Personas:[ \t]*(.*?)[ \t]*$", re.I | re.M)
WAIVER = "waiver (k20)"


class SpecialistError(Exception):
    """An input is not valid. No specialist ran."""


def listed(config: dict[str, Any]) -> list[dict[str, Any]]:
    section = config.get("specialists")
    return [item for item in section if isinstance(item, dict)] if isinstance(section, list) else []


def problems(config: dict[str, Any]) -> list[str]:
    """Return the problems of the `specialists` section of the repo config."""
    section = config.get("specialists")
    if section is None:
        return []
    if not isinstance(section, list):
        return ["'specialists' must be a list of specialists."]
    found: list[str] = []
    seen: set[str] = set()
    for number, item in enumerate(section, 1):
        if not isinstance(item, dict):
            found.append(f"'specialists' item {number} must be a map.")
            continue
        name = str(item.get("id", ""))
        label = f"specialist '{name}'" if name else f"specialists item {number}"
        if not SLUG.match(name):
            found.append(f"The {label} needs an 'id' in lower case, with digits and '-'.")
        elif name in seen:
            found.append(f"The {label} has an ID that is used twice.")
        seen.add(name)
        if not str(item.get("run") or "").strip():
            found.append(f"The {label} needs 'run': the command or the agent to start.")
        unknown = sorted(set(item) - KEYS)
        if unknown:
            found.append(f"The {label} has the key '{unknown[0]}'. Use one of {sorted(KEYS)}.")
        if item.get("stage", STAGES[0]) not in STAGES:
            found.append(f"The {label} has stage '{item['stage']}'. Use one of {list(STAGES)}.")
        if not isinstance(item.get("blocks", False), bool):
            found.append(f"The {label} needs 'blocks' to be true or false.")
        for key in ("owner", "eval"):
            if key in item and not str(item[key] or "").strip():
                found.append(f"The {label} has an empty '{key}'. Give a value, or remove the key.")
        found += _when_problems(label, item.get("when"))
    return found


def _when_problems(label: str, when: Any) -> list[str]:
    if when is None:
        return []
    if not isinstance(when, dict):
        return [f"The {label} needs 'when' to be a map."]
    found = []
    for key, value in when.items():
        if key not in WHEN_KEYS:
            found.append(f"The {label} has 'when.{key}'. Use one of {list(WHEN_KEYS)}.")
        elif not (isinstance(value, list) and value
                  and all(isinstance(v, str) and v.strip() for v in value)):
            found.append(f"The {label} needs 'when.{key}' to be a list of text values.")
    return found


def path_matcher(root: Path) -> Callable[[list[str], str], bool]:
    """Return `covers` of the rendered match module: the match of `paths.tests` (D62, D65)."""
    path = root / MATCH_MODULE
    namespace: dict[str, Any] = {}
    try:
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        return namespace["covers"]
    except Exception as error:  # a missing or broken module, as in the hook
        raise SpecialistError(f"{MATCH_MODULE} is missing or broken. Run stone render.") from error


def reasons(spec: dict[str, Any], files: list[str], labels: list[str],
            limits: dict[str, list[str]],
            covers: Callable[[list[str], str], bool] | None) -> list[str]:
    """Return why a specialist matched. A specialist with no trigger always matches.

    `covers` is the path match from path_matcher. It can be None if the spec has no `when.paths`.
    """
    when = spec.get("when") or {}
    if not when:
        return ["always"]
    found = []
    for pattern in when.get("paths") or []:
        try:
            hit = next((path for path in files if covers([pattern], path)), None)
        except ValueError as error:
            message = f"'when.paths' of the specialist '{spec['id']}': {error}"
            raise SpecialistError(message) from error
        if hit:
            found.append(f"paths: {hit} matches {pattern}")
    wanted = {label.lower() for label in when.get("labels") or []}
    found += [f"labels: {label}" for label in labels if label.lower() in wanted]
    for term in when.get("personas_with") or []:
        for persona, texts in limits.items():
            if any(term.lower() in text.lower() for text in texts):
                found.append(f"personas_with: '{term}' in the limits of {persona}")
    return found


def persona_limits(root: Path, ids: list[str]) -> dict[str, list[str]]:
    """Return the limit texts of each named persona, from the personas file."""
    path = root / personas_check.PERSONAS_FILE
    if not ids:
        return {}
    if not path.exists():
        raise SpecialistError(f"{personas_check.PERSONAS_FILE}: no file, but the ticket names "
                              "personas.")
    by_id = {p.fields.get("id", ""): p for p in personas_check.parse(path.read_text("utf-8"))}
    unknown = [name for name in ids if name not in by_id]
    if unknown:
        raise SpecialistError(f"The persona '{unknown[0]}' is not in "
                              f"{personas_check.PERSONAS_FILE}.")
    return {name: [by_id[name].fields.get("limits", ""),
                   *(text for _, text in by_id[name].items.get("limits", []))] for name in ids}


def changed_files(root: Path, base: str) -> list[str]:
    for rev in (f"{base}...HEAD", f"{base}..HEAD"):
        done = subprocess.run(["git", "diff", "--name-only", rev], cwd=root,
                              capture_output=True, text=True)
        if done.returncode == 0:
            return done.stdout.split()
    raise SpecialistError(f"git cannot diff against '{base}'. Give a base that exists.")


def reports_folder(config: dict[str, Any], ticket: str = "<ticket-id>") -> str:
    """Return `paths.reports` as a folder that ends with '/'. The default is docs/reports/.

    '{id}' in the value (#146) becomes the ticket.
    """
    value = (config.get("paths") or {}).get("reports") or "docs/reports/"
    value = str(value[0] if isinstance(value, list) and value else value)
    value = value.replace("{id}", ticket)
    return value if value.endswith("/") else value + "/"


def report_path(root: Path, config: dict[str, Any], ticket: str, name: str) -> Path:
    return root / f"{reports_folder(config, ticket)}{ticket}.{name}.md"


@dataclass
class Row:
    spec: dict[str, Any]
    why: list[str]
    status: str  # reviewed, missing, or blocking

    def line(self) -> str:
        blocks = "yes" if self.spec.get("blocks") else "no"
        return (f"| {self.spec['id']} | {'; '.join(self.why)} | `{self.spec['run']}` | {blocks} "
                f"| {self.status} |")


def matched(root: Path, config: dict[str, Any], base: str, labels: list[str],
            persona_ids: list[str]) -> list[tuple[dict[str, Any], list[str]]]:
    """Return each specialist that matches the change, with the reasons, in config order."""
    files = changed_files(root, base)
    limits = persona_limits(root, persona_ids)
    specs = listed(config)
    covers = (path_matcher(root) if any((spec.get("when") or {}).get("paths") for spec in specs)
              else None)
    return [(spec, why) for spec in specs if (why := reasons(spec, files, labels, limits, covers))]


def status(root: Path, config: dict[str, Any], ticket: str, spec: dict[str, Any]) -> str:
    """Return reviewed, missing, or blocking for the report of one specialist."""
    path = report_path(root, config, ticket, spec["id"])
    if not path.is_file():
        return "missing"
    if spec.get("blocks") and HIGH.search(path.read_text(encoding="utf-8")):
        return "blocking"
    return "reviewed"


def run(root: Path, config: dict[str, Any], base: str, labels: list[str], persona_ids: list[str],
        ticket: str) -> tuple[list[Row], str]:
    """Match the specialists to a change and check their findings reports."""
    rows = [Row(spec, why, status(root, config, ticket, spec))
            for spec, why in matched(root, config, base, labels, persona_ids)]
    if not rows:
        return rows, "No specialist review matched this change."
    lines = ["Specialist findings (run order):", "",
             "| ID | Why it matched | Run | Blocks | Status |", "| --- | --- | --- | --- | --- |"]
    lines += [row.line() for row in rows]
    for row in rows:
        if row.status == "missing":
            lines.append(f"\nMissing: start `{row.spec['run']}` in a new session. It writes "
                         f"{report_path(root, config, ticket, row.spec['id']).relative_to(root)}.")
        if row.status == "blocking":
            lines.append(f"\nBlocking: {row.spec['id']} has a finding with severity high. "
                         "G4 cannot pass until a human decides.")
    return rows, "\n".join(lines)


def body_fields(body: str) -> tuple[str, list[str]]:
    """Return the ticket ID and the persona IDs from the `Ticket:` and `Personas:` lines."""
    ticket = TICKET_LINE.search(body)
    personas = PERSONAS_LINE.search(body)
    ids = re.split(r"[\s,]+", personas.group(1)) if personas else []
    return (ticket.group(1) if ticket else ""), [i for i in ids if i and i.lower() != "none"]


def waiver(body: str) -> str:
    """Return the text of the first heading with "waiver (K20)" that is not empty, or ''."""
    lines = body.splitlines()
    found = evidence_check.headings(lines)
    for heading in found:
        if WAIVER in heading.name:
            text = evidence_check.section_body(lines, heading, found, set())
            if not evidence_check.is_empty(text):
                return text.strip()
    return ""


def check(root: Path, config: dict[str, Any], base: str, body: str, labels: list[str],
          path: str = "<body>") -> list[Finding]:
    """K20 (D66): return the findings of the specialists that match the PR.

    A blocking finding, or a missing report of a `blocks: true` specialist, is an error. A
    missing report of another specialist is a warning. A waiver makes each error a warning.
    """
    body = body.replace("\r\n", "\n")  # a PR body from the web form has CRLF line ends
    ticket, persona_ids = body_fields(body)
    try:
        found = matched(root, config, base, labels, persona_ids)
    except SpecialistError as error:
        return [Finding(path, 1, CHECK, str(error))]
    if found and not ticket:
        names = ", ".join(spec["id"] for spec, _ in found)
        return _waived(body, [Finding(path, 1, CHECK, (
            f"The specialists {names} match this PR, but the PR body has no 'Ticket: <id>' "
            "line. Add the line, so K20 can find the reports."))])
    findings = []
    for spec, why in found:
        report = report_path(root, config, ticket, spec["id"])
        name = report.relative_to(root).as_posix()
        state = status(root, config, ticket, spec)
        if state == "blocking":
            text = report.read_text(encoding="utf-8")
            match = HIGH.search(text)
            line = text[:match.end()].count("\n") + 1 if match else 1
            findings.append(Finding(name, line, CHECK, (
                f"The specialist {spec['id']} has a finding with severity high, and it blocks. "
                "Fix the finding and run the specialist again. Or add a 'Waiver (K20)' section "
                "with the decision of the human at G4.")))
        elif state == "missing":
            blocks = bool(spec.get("blocks"))
            findings.append(Finding(name, 1, CHECK, (
                f"The specialist {spec['id']} matches ({'; '.join(why)}), but it has no report. "
                f"Start `{spec['run']}` in a new session, and commit its report."),
                "error" if blocks else "warning"))
    return _waived(body, findings)


def _waived(body: str, findings: list[Finding]) -> list[Finding]:
    """With a waiver, return each error as a warning that names the waiver."""
    if not waiver(body) or not any(f.severity == "error" for f in findings):
        return findings
    return [Finding(f.path, f.line, f.check, f"Waived (K20): {f.message} The human at G4 checks "
                    "the waiver.", "warning") if f.severity == "error" else f for f in findings]


def document(config: dict[str, Any]) -> str:
    """Return the text of `.cornerstone/specialists.md`."""
    reports = reports_folder(config)
    lines = ["<!-- Generated by stone render. Do not edit: change `specialists` in "
             ".cornerstone/config.yaml and render again. -->",
             "# Specialist reviews", "",
             "A specialist review runs in a fresh session after the tester and before the reviewer "
             "(P2). The reviewer reads its findings as an input.", "",
             "Run this command to find the specialists that the change needs:", "",
             "```bash",
             "stone specialists --base <base-branch> --labels <labels> --personas <ids> "
             "--ticket <ticket-id>", "```", "",
             "A trigger matches if one of its conditions matches. A specialist with no trigger "
             "always runs.", "",
             "| Order | ID | Run | Trigger | Blocks |", "| --- | --- | --- | --- | --- |"]
    for number, spec in enumerate(listed(config), 1):
        when = spec.get("when") or {}
        trigger = "; ".join(f"{key}: {', '.join(f'`{v}`' for v in when[key])}"
                            for key in WHEN_KEYS if key in when) or "always"
        lines.append(f"| {number} | {spec['id']} | `{spec['run']}` | {trigger} | "
                     f"{'yes' if spec.get('blocks') else 'no'} |")
    lines += ["", "## Findings report", "",
              f"Each specialist writes its findings to `{reports}<ticket-id>.<id>.md`. Each finding "
              "has a line `Severity: high`, `Severity: medium`, or `Severity: low`.", "",
              "A missing report is a missing review. For a specialist with Blocks `yes`, a finding "
              "with severity high stops G4."]
    return "\n".join(lines) + "\n"


def manifest_entry(spec: dict[str, Any], old: dict[str, Any] | None, config: dict[str, Any],
                   today: dt.date, review_by: dt.date) -> dict[str, Any]:
    """Return the manifest entry of one specialist (P5). The source is `repo`."""
    return {
        "id": ID_PREFIX + spec["id"], "kind": "specialist",
        "purpose": f"Specialist review '{spec['id']}': {spec['run']}", "principle": ["P2"],
        "source": "repo",
        "owner": spec.get("owner") or (old or {}).get("owner") or config["owners"]["default"],
        "eval": str(spec.get("eval") or ""), "models_tested": [],
        "added": str(old["added"]) if old else today.isoformat(),
        "review_by": str(old["review_by"]) if old else review_by.isoformat(),
        "files": [],
        "hash": hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest(),
    }
