"""Checks for rules that this repo states in prose (P6, D78, D97, D98, D100): action pins, version
bump, event text in `run`, commit message format, and complexity caps (K9).

These checks are for the repo of the framework. `stone render` does not write them for a target repo.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

import yaml

from stone.findings import Finding

PIN_CHECK = "R1"
BUMP_CHECK = "R2"
ENV_CHECK = "R3"
COMMIT_CHECK = "R4"
COMPLEXITY_CHECK = "K9"
CONFIG = ".cornerstone/config.yaml"
DEFAULT_LIMITS = {"cyclomatic": 10, "function_lines": 60}
DEFAULT_SOURCE = ("src/",)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_BRANCHES = (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
             ast.match_case)
_HUNK = re.compile(r"^@@ -\S+ \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")
COMMIT_TYPES = ("build", "chore", "ci", "docs", "feat", "fix", "perf", "refactor", "revert", "style",
                "test")
WORKFLOWS = ".github/workflows"
TEMPLATES = "framework/adapters/*/templates/workflows"
SKILLS = "plugins/cornerstone/skills/"
PLUGIN_FILE = "plugins/cornerstone/.claude-plugin/plugin.json"

_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<value>[^#\n]*?)\s*(?:#.*)?$")
_ACTION_PIN = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
_IMAGE_PIN = re.compile(r"^docker://\S+@sha256:[0-9a-f]{64}$")
_RUN = re.compile(r"^(?P<indent>\s*(?:-\s+)?)run:(?:\s+(?P<value>.*?))?\s*$")
_BLOCK = re.compile(r"^[|>](?:[+-]?[1-9]?|[1-9][+-])(?:\s+#.*)?$")
_EXPRESSION = re.compile(r"\$\{\{(?P<body>.*?)(?:\}\}|$)")
_EVENT_TEXT = re.compile(
    r"(?<![\w.])github\s*(?:\.\s*(?:event|head_ref)\b|\[\s*['\"](?:event|head_ref)['\"]\s*\])",
    re.IGNORECASE)
_GIT_SUBJECT = re.compile(r'^(?:Revert|Reapply) ".*"$')
_SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^()\s]+)\))?!?: \S")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def is_pinned(value: str) -> bool:
    """A local action, an image with a digest, or an action at a full commit SHA passes."""
    if value.startswith("./"):
        return True
    return bool(_ACTION_PIN.match(value) or _IMAGE_PIN.match(value))


def check_pins(root: Path) -> list[Finding]:
    """R1: each `uses:` in a workflow file must be pinned to a full commit SHA."""
    findings: list[Finding] = []
    folder = root / WORKFLOWS
    files = sorted(p for pattern in ("*.yml", "*.yaml") for p in folder.glob(pattern))
    for path in files:
        rel = path.relative_to(root).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = _USES.match(line)
            if not match:
                continue
            value = _unquote(match.group("value"))
            if value and not is_pinned(value):
                findings.append(Finding(
                    rel, number, PIN_CHECK,
                    f"'uses: {value}' is not pinned to a commit. Replace the tag or branch with "
                    "the 40-character commit SHA, and keep the tag in a comment."))
    return findings


def _workflow_files(root: Path, folders: tuple[str, ...]) -> list[Path]:
    paths = {p for folder in folders for pattern in ("*.yml", "*.yaml")
             for p in root.glob(f"{folder}/**/{pattern}")}
    return sorted(paths)


def run_lines(text: str) -> list[tuple[int, str]]:
    """Return (line number, text) for each line of a `run` value. A pattern, not a YAML parser.

    The value is the text after `run:`, and each next line that is blank or indented more than
    the `run` key. This covers a block (`|` or `>`) and a plain or quoted value on more than one
    line. A `run:` with no value and no `- ` before it is a mapping key (for example a job named
    `run`, or `defaults: run:`), so it gives no line.
    """
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        match = _RUN.match(lines[index])
        index += 1
        if not match:
            continue
        value = match.group("value") or ""
        if value.startswith("#"):
            value = ""
        if not value and "-" not in match.group("indent"):
            continue
        if value and not _BLOCK.match(value):
            found.append((index, value))
        key_indent = len(match.group("indent"))
        while index < len(lines):
            line = lines[index]
            if line.strip() and len(line) - len(line.lstrip()) <= key_indent:
                break
            index += 1
            found.append((index, line))
    return found


def check_event_text(root: Path,
                     folders: tuple[str, ...] = (WORKFLOWS, TEMPLATES)) -> list[Finding]:
    """R3: a `run` value must not hold `github.event` or `github.head_ref` in a `${{ }}`."""
    findings: list[Finding] = []
    for path in _workflow_files(root, folders):
        rel = path.relative_to(root).as_posix()
        for number, line in run_lines(path.read_text(encoding="utf-8")):
            for expression in _EXPRESSION.finditer(line):
                body = expression.group("body").strip()
                if _EVENT_TEXT.search(body):
                    findings.append(Finding(
                        rel, number, ENV_CHECK,
                        f"'${{{{ {body} }}}}' is inline in 'run'. Event text can hold shell code. "
                        "Give it to the step in 'env', and use the variable in 'run' (for "
                        "example \"$TITLE\", not ${{ env.TITLE }})."))
    return findings


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout


def _version(text: str) -> str | None:
    try:
        value = json.loads(text).get("version")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def check_version_bump(root: Path, base: str, skills: str = SKILLS,
                       plugin_file: str = PLUGIN_FILE) -> list[Finding]:
    """R2: a change under `skills` needs a new `version` in `plugin_file`.

    The diff starts at the merge base of `base` and HEAD, and ends at HEAD. In CI, the result is
    the same as `git diff base...HEAD`.
    """
    merge_base = _git(root, "merge-base", base, "HEAD").strip()
    names = _git(root, "diff", "--name-only", merge_base, "HEAD", "--", skills).splitlines()
    if not names:
        return []
    old = _git_show(root, merge_base, plugin_file)
    new = _git_show(root, "HEAD", plugin_file)
    if new is None and old is not None:
        return []  # The plugin file left this tree (a rename or a removal). No version to bump.
    if new is None or _version(new) is None:
        return [Finding(plugin_file, 1, BUMP_CHECK,
                        "The file is missing or has no string 'version'. Add one, because a "
                        "skill changed.")]
    if old is not None and _version(old) == _version(new):
        return [Finding(plugin_file, 1, BUMP_CHECK,
                        f"{len(names)} file(s) under {skills} changed (first: {names[0]}), but "
                        f"'version' is still {_version(new)}. Increase 'version'.")]
    return []


def subject_problem(subject: str) -> str | None:
    """Return why `subject` is not `type(scope): summary`, or None. The scope is optional.

    A subject that `git revert` writes (`Revert "..."` or `Reapply "..."`) passes.
    """
    if _GIT_SUBJECT.match(subject):
        return None
    match = _SUBJECT.match(subject)
    if not match:
        return "It does not have the form 'type(scope): summary'"
    if match.group("type") not in COMMIT_TYPES:
        return f"The type '{match.group('type')}' is not one of: {', '.join(COMMIT_TYPES)}"
    return None


def check_commit_format(root: Path, base: str) -> list[Finding]:
    """R4: the subject of each commit from the merge base to HEAD is `type(scope): summary`.

    A merge commit is not tested, because git writes its subject.
    """
    merge_base = _git(root, "merge-base", base, "HEAD").strip()
    log = _git(root, "log", "--no-merges", "--format=%H%x1f%s%x1e", f"{merge_base}..HEAD")
    findings: list[Finding] = []
    for entry in log.split("\x1e"):
        sha, _, subject = entry.strip().partition("\x1f")
        problem = subject_problem(subject) if sha else None
        if problem:
            findings.append(Finding(
                f"commit {sha[:12]}", 1, COMMIT_CHECK,
                f"{problem}: '{subject}'. Reword the commit, for example 'fix(stone): "
                "<summary>'. On a branch that other people use, ask first: AGENTS.md forbids a "
                "force-push of a shared branch."))
    return findings


def cyclomatic(function: ast.AST) -> int:
    """Return the cyclomatic complexity of `function`: 1, plus 1 for each decision point.

    A decision point is an `if` or `elif`, a conditional expression, a `for` or `while`, an
    `except`, a `case`, the `for` and each `if` of a comprehension, and each `and` or `or` after
    the first operand. A nested function or class is not counted here: it has its own count.
    """
    count = 1
    pending = list(ast.iter_child_nodes(function))
    while pending:
        node = pending.pop()
        if isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
            continue
        if isinstance(node, _BRANCHES):
            count += 1
        elif isinstance(node, ast.comprehension):
            count += 1 + len(node.ifs)
        elif isinstance(node, ast.BoolOp):
            count += len(node.values) - 1
        pending.extend(ast.iter_child_nodes(node))
    return count


def changed_lines(diff: str) -> dict[str, set[int]]:
    """Return the new-file line numbers that each file of a `git diff -U0` adds or changes."""
    found: dict[str, set[int]] = {}
    path = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
            continue
        match = _HUNK.match(line)
        if path and match:
            start, count = int(match.group("start")), int(match.group("count") or 1)
            found.setdefault(path, set()).update(range(start, start + count))
    return found


def old_paths(diff: str) -> dict[str, str]:
    """Return the old path of each file that a `git diff` moved, by its new path."""
    found: dict[str, str] = {}
    old = ""
    for line in diff.splitlines():
        if line.startswith("--- "):
            old = line[6:] if line.startswith("--- a/") else ""
        elif line.startswith("+++ b/") and old and old != line[6:]:
            found[line[6:]] = old
    return found


def complexity_limits(root: Path) -> tuple[dict[str, int], tuple[str, ...]]:
    """Return the K9 limits and the source folders from the repo config, or the defaults."""
    path = root / CONFIG
    config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    config = config if isinstance(config, dict) else {}
    given = config.get("limits") if isinstance(config.get("limits"), dict) else {}
    limits = {key: given[key] if isinstance(given.get(key), int) else value
              for key, value in DEFAULT_LIMITS.items()}
    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    source = paths.get("source") or DEFAULT_SOURCE
    return limits, (source,) if isinstance(source, str) else tuple(source)


def function_metrics(text: str) -> dict[str, list[tuple[range, int]]]:
    """Return the lines and the cyclomatic complexity of each function, by its qualified name.

    A name can have more than one function, for example a property and its setter. The list
    keeps them in the order of the file.
    """
    found: dict[str, list[tuple[range, int]]] = {}
    pending: list[tuple[ast.AST, str]] = [(ast.parse(text), "")]
    while pending:
        parent, prefix = pending.pop()
        for node in ast.iter_child_nodes(parent):
            name = prefix
            if isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
                name = f"{prefix}{node.name}."
            if isinstance(node, _FUNCTIONS):
                span = range(node.lineno, (node.end_lineno or node.lineno) + 1)
                found.setdefault(name[:-1], []).append((span, cyclomatic(node)))
            pending.append((node, name))
    return found


def limit_problem(name: str, key: str, value: int, old_value: int | None, limit: int) -> str | None:
    """Return why `value` of function `name` breaks the limit `key`, or None.

    If the function was over the limit at the merge base (`old_value`), and the value did not
    increase, it passes: the change did not add complexity (D100).
    """
    was_over = old_value is not None and old_value > limit
    if value <= limit or (was_over and value <= (old_value or 0)):
        return None
    what = f"a cyclomatic complexity of {value}" if key == "cyclomatic" else f"{value} lines"
    was = f" (it was {old_value})" if was_over else ""
    return f"'{name}' has {what}, more than the limit {limit}{was}"


def _old_metrics(old_text: str | None) -> dict[str, list[tuple[range, int]]]:
    try:
        return function_metrics(old_text) if old_text else {}
    except SyntaxError:
        return {}  # The old file does not parse, so each function counts as new.


def _in_file_order(metrics: dict[str, list[tuple[range, int]]]
                   ) -> list[tuple[range, int, str, int]]:
    """Return (lines, complexity, name, index for the name) of each function, by first line."""
    functions = [(span, score, name, index) for name, found in metrics.items()
                 for index, (span, score) in enumerate(found)]
    return sorted(functions, key=lambda function: function[0].start)


def function_problems(text: str, lines: set[int], limits: dict[str, int],
                      old_text: str | None = None) -> list[tuple[int, str]]:
    """Return (line, problem) for each function that has a changed line and breaks a limit.

    `old_text` is the file at the merge base. A function that is not in it counts as new. If a
    name has more than one function, the first new one pairs with the first old one, and so on.
    """
    old = _old_metrics(old_text)
    found: list[tuple[int, str]] = []
    for span, score, name, index in _in_file_order(function_metrics(text)):
        if not lines.intersection(span):
            continue
        olds = old.get(name, [])
        before = olds[index] if index < len(olds) else None
        for key, value, old_value in (
                ("cyclomatic", score, before[1] if before else None),
                ("function_lines", len(span), len(before[0]) if before else None)):
            problem = limit_problem(name, key, value, old_value, limits[key])
            if problem:
                found.append((span.start, problem))
    return found


def check_complexity(root: Path, base: str) -> list[Finding]:
    """K9: a function that the diff adds or changes must be in the complexity caps (D100).

    Only Python files under `paths.source` of the repo config are tested. A function that the
    diff does not touch is not tested. A function that was over a limit at the merge base passes
    if the change does not increase the value.
    """
    limits, source = complexity_limits(root)
    merge_base = _git(root, "merge-base", base, "HEAD").strip()
    diff = _git(root, "-c", "core.quotePath=false", "diff", "-U0", "--no-color", "--no-ext-diff",
                "--find-renames", "--src-prefix=a/", "--dst-prefix=b/", merge_base, "HEAD", "--",
                *source)
    moved = old_paths(diff)
    findings: list[Finding] = []
    for path, lines in sorted(changed_lines(diff).items()):
        text = _git_show(root, "HEAD", path) if path.endswith(".py") else None
        if text is None:
            continue
        try:
            old_text = _git_show(root, merge_base, moved.get(path, path))
            problems = function_problems(text, lines, limits, old_text)
        except SyntaxError as error:
            problems = [(error.lineno or 1, f"The file does not parse ({error.msg})")]
        findings += [Finding(path, number, COMPLEXITY_CHECK,
                             f"{problem}. Split the function.")
                     for number, problem in problems]
    return findings


def _git_show(root: Path, rev: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True,
                            text=True)
    return result.stdout if result.returncode == 0 else None


def run(root: Path, base: str | None, skills: str = SKILLS,
        plugin_file: str = PLUGIN_FILE, complexity: bool = True) -> list[Finding]:
    """Run R1 and R3. With `base`, also run R2, R4, and K9. `complexity` false skips K9 (D103)."""
    findings = check_pins(root) + check_event_text(root)
    if base:
        findings += check_version_bump(root, base, skills, plugin_file)
        findings += check_commit_format(root, base)
        if complexity:
            findings += check_complexity(root, base)
    return findings
