"""K21: report a Definition of Ready field that is missing or empty (framework/checks.md, P3, G1)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from stone.evidence_check import FENCE, headings, is_empty, section_body
from stone.findings import Finding

CHECK = "K21"
SECTION = "definition of ready"
PROFILE_LINE = re.compile(r"^\s*Profile:\s*([a-z0-9-]+)\s*$", re.I | re.M)
FIELD_LINE = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*|__)?([A-Za-z][A-Za-z -]*?)(?:\*\*|__)?\s*:(.*)$")
VAGUE = {"?", "none"}  # "none" passes only where the field allows it (personas)


@dataclass(frozen=True)
class Field:
    name: str  # the label that the shaper writes (SHAPER_FORM in render.py)
    labels: tuple[str, ...]  # the lowercase labels and headings that count
    allow_none: bool = False


PROBLEM = Field("Problem", ("problem", "goal", "problem or goal", "why this change"))
CRITERIA = Field("Acceptance criteria", ("acceptance criteria",))
NON_GOALS = Field("Non-goals", ("non-goals", "non goals"))
ORACLE = Field("Test oracle", ("test oracle",))
REPRODUCTION = Field("Reproduction", ("reproduction", "reproduction steps", "steps to reproduce"))
TIME_BOX = Field("Time box", ("time box", "timebox"))
PERSONAS = Field("Personas", ("personas",))
PERSONAS_OR_NONE = Field("Personas", ("personas",), allow_none=True)

BUILD = (CRITERIA, NON_GOALS, ORACLE)
# The "Definition of Ready (default)" table in framework/workflow-model.md, for each profile.
# A profile that names its own G1 fields uses them (D82).
PROFILE_FIELDS: dict[str, tuple[Field, ...]] = {
    "adapter-refresh": (PROBLEM, *BUILD),
    "app-slice": (PROBLEM, *BUILD, PERSONAS),
    "bug-triage": (PROBLEM, REPRODUCTION),
    "code-audit": (PROBLEM, TIME_BOX),
    "debugging": (PROBLEM, REPRODUCTION, PERSONAS_OR_NONE),  # step 1 of profiles/debugging.md
    "dependency-upgrade": (PROBLEM, *BUILD),
    "full-project": (PROBLEM,),
    "refactor-migration": (PROBLEM, *BUILD),
    "single-ticket": (PROBLEM, *BUILD, PERSONAS_OR_NONE),
    "spike": (PROBLEM, *BUILD, TIME_BOX),
}


def find_profile(text: str) -> str | None:
    """Return the ID on the first `Profile: <id>` line, or None."""
    match = PROFILE_LINE.search(text)
    return match.group(1).lower() if match else None


def _scope(lines: list[str]) -> tuple[list[str], int]:
    """Return the lines of the `Definition of Ready` section and the offset of its first line.
    With no such section, return all lines."""
    found = headings(lines)
    for heading in found:
        if heading.name == SECTION:
            body = section_body(lines, heading, found, set()).splitlines()
            return body, heading.line
    return lines, 0


def _field_values(lines: list[str], offset: int, known: set[str]) -> dict[str, tuple[int, str]]:
    """Return {label: (line, value)} for each `Label: value` line with a known label.
    The value goes on until the next known label, a heading, or the end."""
    values: dict[str, tuple[int, str]] = {}
    current: str | None = None
    fence: str | None = None
    for number, line in enumerate(lines, offset + 1):
        marker = FENCE.match(line)
        if marker:
            fence = None if fence == marker.group(1) else fence or marker.group(1)
            continue
        if fence:
            continue
        if line.lstrip().startswith("#"):
            current = None
            continue
        match = FIELD_LINE.match(line)
        label = match.group(1).strip().lower() if match else None
        if label in known and label not in values:
            current = label
            values[label] = (number, match.group(2).strip())
        elif current:
            line_number, text = values[current]
            values[current] = (line_number, f"{text}\n{line.strip()}".strip())
    return values


def _heading_values(lines: list[str], known: set[str]) -> dict[str, tuple[int, str]]:
    """Return {heading name: (line, body)} for each heading with a known label."""
    found = headings(lines)
    names = {heading.name for heading in found} & known
    values: dict[str, tuple[int, str]] = {}
    for heading in found:
        if heading.name in names and heading.name not in values:
            values[heading.name] = (heading.line, section_body(lines, heading, found, names))
    return values


def _empty(value: str, field: Field) -> bool:
    text = value.strip().strip("*_`.: ").lower()
    if field.allow_none and text == "none":
        return False
    return is_empty(value) or text in VAGUE or bool(re.fullmatch(r"<[^<>]*>", text))


def check_text(text: str, path: str, profile: str) -> list[Finding]:
    """Return a K21 finding for each field of the profile that is missing or empty."""
    fields = PROFILE_FIELDS[profile]
    known = {label for field in fields for label in field.labels}
    lines = text.splitlines()
    scope, offset = _scope(lines)
    values = {**_heading_values(lines, known), **_field_values(scope, offset, known)}
    findings: list[Finding] = []
    for field in fields:
        hits = [values[label] for label in field.labels if label in values]
        if not hits:
            findings.append(Finding(path, 1, CHECK,
                                    f"The ticket has no '{field.name}' field. The profile "
                                    f"{profile} needs it. Add a line '{field.name}: <value>' "
                                    "under '## Definition of Ready'."))
        elif all(_empty(value, field) for _, value in hits):
            findings.append(Finding(path, hits[0][0], CHECK,
                                    f"The '{field.name}' field is empty or vague. Fill it before "
                                    "work starts."))
    return findings
