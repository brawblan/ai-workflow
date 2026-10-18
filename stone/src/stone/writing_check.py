"""K17: test the measurable rules of the writing standard (framework/writing.md)."""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from stone.findings import Finding
from stone.markdown import Block, prose_blocks, table_rows

CHECK = "K17"
DEFAULT_RULES = Path("plugins/workflow/skills/ste-writing/references/ste.md")
DEFAULT_DICTIONARY = Path("docs/style/ste.md")
# Agent-facing text is out of scope (writing.md, "Scope"). Golden files are rendered templates.
DEFAULT_EXCLUDE = ["*SKILL.md", "*/skills/*", "AGENTS.md", "*/AGENTS.md", "CLAUDE.md",
                   "*/CLAUDE.md", ".claude/*", "*/.claude/*", "*/templates/*",
                   "golden/*", "*/golden/*",
                   ".git/*"]
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’/_-]*")
PROGRESSIVE = re.compile(r"\b(?:am|is|are|was|were|be|been)\s+([a-z]+ing)\b", re.I)
NOT_VERBS = {"thing", "string", "nothing", "something", "anything", "everything", "during",
             "morning", "evening", "ring", "king", "spring", "ceiling", "missing"}
PASSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+([a-z]+(?:ed|en))\b", re.I)
NOT_PARTICIPLES = {"open", "often", "even", "ten", "token"}


@dataclass
class Rules:
    vague_words: set[str] = field(default_factory=set)
    banned_terms: dict[str, str] = field(default_factory=dict)  # banned term -> approved term
    max_procedure: int = 20
    max_description: int = 25
    max_paragraph: int = 6


def load_rules(rules_path: Path, dictionary_path: Path | None) -> Rules:
    """Read the vague words and the dictionary from ste.md and the project dictionary."""
    text = rules_path.read_text(encoding="utf-8")
    rules = Rules()
    match = re.search(r"Do not use vague words:([^\n]+)", text)
    if match:
        words = match.group(1).replace("etc.", "").rstrip(".")
        rules.vague_words = {w.strip().lower() for w in words.split(",") if w.strip()}
    shared = text.split("## Dictionary", 1)[-1]
    shared = re.sub(r"### Project dictionary.*?(?=\n### |\Z)", "", shared, flags=re.S)
    sources = [shared]
    if dictionary_path and dictionary_path.exists():
        sources.append(dictionary_path.read_text(encoding="utf-8"))
    rows = [row for source in sources for row in table_rows(source)
            if len(row) >= 3 and row[0] not in {"Term"}]
    approved = {row[0].strip("`").lower() for row in rows}
    for row in rows:
        for term in row[2].split(","):
            term = term.strip().lower()
            # A term with a qualifier, or a term that is approved in another row,
            # depends on context. Only the writing skill and the reviewer can judge it.
            if term and "(" not in term and term not in approved:
                rules.banned_terms[term] = row[0]
    return rules


def _sentences(block: Block) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    offset = 0
    for part in SENTENCE_END.split(block.text):
        start = block.text.find(part, offset)
        offset = start + len(part)
        if part.strip():
            result.append((block.line_at(start), part.strip()))
    return result


def check_text(path: str, text: str, rules: Rules) -> list[Finding]:
    findings: list[Finding] = []

    def add(line: int, rule: str, message: str, severity: str = "error") -> None:
        findings.append(Finding(path, line, CHECK, f"Rule {rule}: {message}", severity))  # type: ignore[arg-type]

    for block in prose_blocks(text):
        sentences = _sentences(block)
        limit = rules.max_procedure if block.kind == "procedure" else rules.max_description
        kind = "procedure" if block.kind == "procedure" else "description"
        for line, sentence in sentences:
            lower = sentence.lower()
            count = len(WORD.findall(sentence))
            if count > limit:
                add(line, "8", f"The sentence has {count} words. The limit for a {kind} is "
                    f"{limit}. Split the sentence.")
            for word in sorted(rules.vague_words):
                if re.search(rf"\b{re.escape(word)}\b", lower):
                    add(line, "5", f"'{word}' is a vague word. Use a precise word, or remove it.")
            for term, approved in sorted(rules.banned_terms.items()):
                if re.search(rf"\b{re.escape(term)}\b", lower):
                    add(line, "1", f"Do not use '{term}'. Use '{approved}'.")
            for match in PROGRESSIVE.finditer(sentence):
                if match.group(1).lower() not in NOT_VERBS:
                    add(line, "2", f"'{match.group(0)}' looks like a progressive verb. "
                        "Use a simple tense.", "warning")
            if block.kind == "procedure":
                for match in PASSIVE.finditer(sentence):
                    if match.group(1).lower() not in NOT_PARTICIPLES:
                        add(line, "11", f"'{match.group(0)}' looks passive. Use the active "
                            "voice in a procedure.", "warning")
        if block.kind == "paragraph" and len(sentences) > rules.max_paragraph:
            add(block.start, "13", f"The paragraph has {len(sentences)} sentences. The limit is "
                f"{rules.max_paragraph}. Split the paragraph.")
    return findings


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout


def changed_lines(base: str, root: Path) -> dict[str, set[int]]:
    """Return the added or changed line numbers of each Markdown file since `base`.

    The diff starts at the merge base of `base` and HEAD, and ends at the working tree. Thus it
    includes commits, staged changes, unstaged changes, and untracked files. In a clean tree
    (for example in CI), the result is the same as `git diff base...HEAD`.
    """
    merge_base = _git(root, "merge-base", base, "HEAD").strip()
    diff = _git(root, "diff", "--unified=0", "--no-color", merge_base, "--", "*.md")
    result: dict[str, set[int]] = {}
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("@@") and current:
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match:
                start, count = int(match.group(1)), int(match.group(2) or "1")
                result.setdefault(current, set()).update(range(start, start + count))
    # git diff does not show untracked files. Each line of a new file is a changed line.
    for name in _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--",
                     "*.md").split("\0"):
        if name:
            count = len((root / name).read_text(encoding="utf-8").splitlines())
            result[name] = set(range(1, count + 1))
    return result


def excluded(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def run(root: Path, paths: list[str], base: str | None, rules: Rules,
        exclude: list[str]) -> list[Finding]:
    """Test the given paths in full, and the changed lines since `base`."""
    files: dict[str, tuple[Path, set[int] | None]] = {}
    if base:
        for name, lines in changed_lines(base, root).items():
            files[name] = (root / name, lines)
    for name in paths:
        target = Path(name) if Path(name).is_absolute() else root / name
        for path in sorted(target.rglob("*.md")) if target.is_dir() else [target]:
            try:
                display = str(path.relative_to(root))
            except ValueError:
                display = str(path)  # a file outside the repo, for example a PR body
            files[display] = (path, None)
    findings: list[Finding] = []
    for display, (path, lines) in sorted(files.items()):
        if excluded(display, exclude) or not path.exists():
            continue
        for finding in check_text(display, path.read_text(encoding="utf-8"), rules):
            if lines is None or finding.line in lines:
                findings.append(finding)
    return findings
