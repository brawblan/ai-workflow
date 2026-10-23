"""K18: test the personas file and the persona and job story IDs in the plans."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from stone import specs
from stone.findings import Finding

CHECK = "K18"
PERSONAS_FILE = Path("constitution") / "personas.md"
FIELDS = ["id", "who", "jobs", "limits", "evidence"]
LIMITS = ["device", "skill", "access"]
EVIDENCE = {"assumed", "validated"}
JOBS_MIN, JOBS_MAX = 3, 5
SLUG = re.compile(r"^[a-z][a-z0-9-]*$")
FIELD_LINE = re.compile(r"^- (\w+):\s*(.*)$")
ITEM_LINE = re.compile(r"^\s+- (.+)$")
JOB = re.compile(r"^(?P<id>\S+):\s*When I .+, I want to .+, so that .+$")
COMMENT = re.compile(r"<!--.*?-->", re.S)
PERSONAS_LINE = re.compile(r"^[\s>*_-]*Personas:[*_]*\s*(?P<ids>.*)$")
JOB_REF = re.compile(r"\b[a-z][a-z0-9-]*\.J\d+\b")


@dataclass
class Persona:
    line: int
    fields: dict[str, str] = field(default_factory=dict)
    items: dict[str, list[tuple[int, str]]] = field(default_factory=dict)


def parse(text: str) -> list[Persona]:
    """Return one Persona for each `##` section. Skip HTML comments and code blocks."""
    text = COMMENT.sub(lambda match: "\n" * match.group().count("\n"), text)
    personas: list[Persona] = []
    current_field = ""
    in_code = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.startswith("## "):
            personas.append(Persona(number))
            current_field = ""
        elif personas and (match := FIELD_LINE.match(line)):
            current_field = match.group(1)
            personas[-1].fields[current_field] = match.group(2).strip()
            personas[-1].items.setdefault(current_field, [])
        elif personas and current_field and (match := ITEM_LINE.match(line)):
            personas[-1].items[current_field].append((number, match.group(1).strip()))
    return personas


def check_file(path: Path, label: str) -> tuple[list[Finding], set[str], set[str]]:
    """Test the format. Return the findings, the persona IDs, and the job story IDs."""
    findings: list[Finding] = []
    persona_ids: set[str] = set()
    job_ids: set[str] = set()

    def add(line: int, message: str) -> None:
        findings.append(Finding(label, line, CHECK, message))

    personas = parse(path.read_text(encoding="utf-8"))
    if not personas:
        add(1, "The file has no persona. Add one '##' section for each persona.")
    for persona in personas:
        missing = [name for name in FIELDS if name not in persona.fields]
        if missing:
            add(persona.line, f"The persona has no {', '.join(missing)}. Add the missing fields.")
        pid = persona.fields.get("id", "")
        if "id" in persona.fields and not SLUG.match(pid):
            add(persona.line, f"The id '{pid}' is not a slug. Use lowercase letters, digits, "
                              "and hyphens, for example 'analyst'.")
        if pid and pid in persona_ids:
            add(persona.line, f"The id '{pid}' is used two times. Give each persona its own id.")
        if pid:
            persona_ids.add(pid)
        if "who" in persona.fields and not persona.fields["who"]:
            add(persona.line, "The 'who' field is empty. Write one line about the persona.")
        if "jobs" in persona.fields:
            findings.extend(_check_jobs(persona, pid, job_ids, label))
        if "limits" in persona.fields:
            given = {item.split(":", 1)[0].strip(): item.split(":", 1)[-1].strip()
                     for _, item in persona.items["limits"] if ":" in item}
            for limit in LIMITS:
                if not given.get(limit):
                    add(persona.line, f"The limits have no '{limit}'. Add '  - {limit}: <value>'.")
        evidence = persona.fields.get("evidence")
        if evidence is not None and re.split(r"[\s(,:]", evidence, maxsplit=1)[0] not in EVIDENCE:
            add(persona.line, f"The evidence '{evidence}' is not valid. Start it with "
                              f"{' or '.join(sorted(EVIDENCE))}.")
    return findings, persona_ids, job_ids


def _check_jobs(persona: Persona, pid: str, job_ids: set[str], label: str) -> list[Finding]:
    findings: list[Finding] = []
    jobs = persona.items["jobs"]
    if not JOBS_MIN <= len(jobs) <= JOBS_MAX:
        findings.append(Finding(label, persona.line, CHECK,
                                f"The persona has {len(jobs)} job stories. Write {JOBS_MIN} to "
                                f"{JOBS_MAX}."))
    for line, job in jobs:
        match = JOB.match(job)
        if not match:
            message = ("The job story does not have the form '<id>.J<n>: When I ..., I want to "
                       "..., so that ...'. Rewrite it.")
        elif not re.fullmatch(re.escape(pid) + r"\.J\d+", match.group("id")):
            message = f"The job story ID '{match.group('id')}' does not have the form '{pid}.J<n>'."
        elif match.group("id") in job_ids:
            message = f"The job story ID '{match.group('id')}' is used two times. Renumber it."
        else:
            job_ids.add(match.group("id"))
            continue
        findings.append(Finding(label, line, CHECK, message))
    return findings


def plan_files(root: Path) -> list[Path]:
    """Return the plan files, or none if the config path is not valid (K19 reports it)."""
    try:
        return specs.plan_files(root, ".md")
    except specs.SpecError:
        return []


def check_plans(root: Path, persona_ids: set[str] | None, job_ids: set[str]) -> list[Finding]:
    """Each persona ID and job story ID in a plan must be in the personas file.

    `persona_ids` is None when the personas file does not exist.
    """
    findings: list[Finding] = []
    for path in plan_files(root):
        label = path.relative_to(root.resolve()).as_posix()
        in_code = False
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            for name, kind in _references(line):
                if persona_ids is None:
                    message = (f"The plan names the {kind} '{name}', but {PERSONAS_FILE} does "
                               "not exist. Write the personas file first.")
                elif name in (persona_ids if kind == "persona" else job_ids):
                    continue
                else:
                    message = (f"The {kind} '{name}' is not in {PERSONAS_FILE}. Fix the ID, or "
                               "add it to the personas file.")
                findings.append(Finding(label, number, CHECK, message))
    return findings


def _references(line: str) -> list[tuple[str, str]]:
    found = [(job, "job story") for job in JOB_REF.findall(line)]
    match = PERSONAS_LINE.match(line)
    if match:
        for token in re.split(r"[,\s]+", match.group("ids")):
            token = token.strip("`*_.;")
            if token and token.lower() != "none" and not JOB_REF.fullmatch(token):
                found.append((token, "persona"))
    return found


def run(root: Path) -> list[Finding]:
    """K18. Each finding is an error. The warning period ended early (D53)."""
    path = root / PERSONAS_FILE
    if not path.exists():
        return check_plans(root, None, set())
    findings, persona_ids, job_ids = check_file(path, str(PERSONAS_FILE))
    return findings + check_plans(root, persona_ids, job_ids)
