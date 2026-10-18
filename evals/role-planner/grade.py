"""Custom checks for the role.planner eval. `stone eval` runs this file once for each grader check.

Usage: grade.py <name> --workspace <path> --args <json>. The last line of the output is JSON:
{"pass": true|false, "detail": "..."}. The environment variable STONE_EVAL_REPORT has the final
text of the run (D35). No grader changes the workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from stone import specs
from stone.markdown import split_frontmatter

REPORT_ENV = "STONE_EVAL_REPORT"
JOB_STORY = re.compile(r"\b[a-z][a-z0-9-]*\.J[1-9]\d*\b")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s")
# A label line starts a block in text with no heading: a bold line, or a short line that ends in ":".
# A list item is not a label, so "- Codes:" in a questions block stays in that block.
LABEL = re.compile(r"^\s{0,3}(?![-*+]\s|\d+[.)]\s)(\*\*[^*]+\*\*:?|__[^_]+__:?|[^.:!?|]{1,60}:)\s*$")
LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s")
# A line that says that there is no question, for example "None." or "No open questions".
NONE = re.compile(r"^\W*(none|no|n/a)\b", re.I)
# A line of the report that asks: a question mark, or words that say that the ticket is not clear.
# Only the present tense counts: "I decided" or "I confirmed" is a decision, not a question.
ASKS = re.compile(r"\?|\b(unclear|not clear|ambiguous|unspecified|undefined|decide|confirm|"
                  r"clarify|clarification)\b|\b(does|do|did) not (say|state|specify|define|cover)\b",
                  re.I)
# open_question: the words that give a recommendation, name the default, and start the options.
# "I suggest (b)" and "Suggested answer: (b)" recommend. "The ticket suggested nothing", "I suggest
# an optional argument", and "the author may prefer" do not.
RECOMMENDS = re.compile(r"\b(recommend\w*|suggestion|preference|"
                        r"(I|we)('d| would)? (suggest|prefer)(?= \(?[a-e1-9]\b| option| answer)|"
                        r"suggested(?=:| answer| option)|preferred(?=:| answer| option|\)))", re.I)
DEFAULTS = re.compile(r"\bdefault\b|\b(plan|build) (uses|assumes|treats|raises|takes)\b|"
                      r"\bin the meantime\b|\bmeanwhile\b", re.I)
OPTIONS = re.compile(r"\boptions?\b", re.I)
# An option label: "(a)", "(1)", "a)", "A.", "A:", "Option A", or "Option 1".
OPTION_LABEL = re.compile(r"(?:^|(?<=[\s(*_]))(?:\(([a-e1-9])\)|([a-e])[).:](?=[\s*_]|$)|"
                          r"option\s+([a-e1-9])\b)", re.I)
# The text before a word that says that the word has no value: "No default", "not recommended".
# A value that says that there is no value: "none", "n/a", "tbd". "no discount" is a value.
EMPTY = re.compile(r"^\W*(none|n/a|tbd)\b", re.I)
NEGATED = re.compile(r"\b(no|not|without)\s+(an?\s+)?$", re.I)
SPLIT = re.compile(r";|,|\bor\b|\s/\s", re.I)
# A change heading of a delta that adds or changes a requirement: "## ADDED cart.R3: A title".
CHANGE = re.compile(r"^## (?:ADDED|MODIFIED)\s+(\S+?):?(?:\s|$)")
# A list item that gives a recommendation or a default, not an option: "- Recommendation: (b)",
# "- I recommend (b)", "- Default until G2: (a)". "- Raise ExpiredCode (recommended)" is an option.
PART_ITEM = re.compile(r"^\W*(\w+\s+){0,2}?(recommend|suggest|prefer|default|the plan uses)", re.I)
# The styles of a line that can start a question, from the strongest: a heading, a "Q1" or
# "Question 1" line, a numbered item, a line that starts with bold text, and a bullet item.
STYLES = ("heading", "q", "numbered", "bold", "bullet")
Q_LINE = re.compile(r"^(?:(?:[-*+]|\d+[.)])\s+)?(?:\*\*|__)?\s*(?:Q\d+|Question \d+)\b", re.I)
# A line that gives a part of a question, not a new question: an option, a recommendation, or a
# default ("**Options:**", "- (a) ...", "I recommend (a)", "**Interim default:** (a)").
PART_LINE = re.compile(r"^(?:(?:[-*+]|\d+[.)])\s+)?(?:\*\*|__)?\s*(?:options?\b|\(?[a-e][).:]\s|"
                       r"(?:\w+\s+){0,2}?(?:recommend|default\b|suggest|prefer)|the plan uses|"
                       r"until G2)", re.I)
# A bold label, such as "**Context:**" or "**Why it matters**:". It does not start a question.
BOLD_LABEL = re.compile(r"^(?:(?:[-*+]|\d+[.)])\s+)?(?:\*\*[^*]+:\*\*|__[^_]+:__|\*\*[^*]+\*\*:|"
                        r"__[^_]+__:)")
# A parameter default in code, not the default of the plan: "(default `date.today()`)".
CODE_DEFAULT = re.compile(r"^[:=]?\s*`[^`]*`\s*\)")
OPEN_NOTE = re.compile(r"\bopen question\b|\bnot (yet )?(decided|approved)\b", re.I)
TABLE_RULE = re.compile(r"^\s*\|?(\s*:?-+:?\s*\|)+\s*:?-*:?\s*$")  # | --- | :-: |


def _read(workspace: Path, path: str) -> str | None:
    target = workspace / path
    return target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None


def _level(line: str) -> int:
    """Return the heading level of the line, or 0 if it is not a heading."""
    match = HEADING.match(line)
    return len(match[1]) if match else 0


def _blocks(text: str, word: str) -> list[str]:
    """Return each block of the text whose first line has `word` in it.

    A heading block ends at the next heading of the same or a higher level. A label block ends at
    the next heading or label, or at a blank line and then a line that is not a list item or a table
    row. A label in a heading block is part of that block.
    """
    blocks: list[str] = []
    current: list[str] | None = None
    level = 0  # the level of the open heading block, or 0 for a label block
    blank = False
    for line in text.splitlines():
        new = _level(line)
        starts = (new and (not level or new <= level)) or (LABEL.match(line) and not (
            current is not None and level))
        # A label block also ends at a blank line and then a line that is not a list item or a row.
        if current is not None and not level and blank and line.strip() and not (
                LIST_ITEM.match(line) or line.lstrip().startswith("|")):
            starts = True
        blank = not line.strip()
        if starts:
            if current is not None:
                blocks.append("\n".join(current))
            current = [line] if word in line.lower() else None
            level = new if current is not None else 0
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append("\n".join(current))
    return blocks


def _section(text: str, word: str) -> str | None:
    """Return the body of the first heading section with `word` in its heading.

    The section ends at the next heading of the same or a higher level.
    """
    lines = text.splitlines()
    for start, line in enumerate(lines):
        level = _level(line)
        if level and word in line.lower():
            end = next((i for i in range(start + 1, len(lines))
                        if 0 < _level(lines[i]) <= level), len(lines))
            return "\n".join(lines[start + 1:end])
    return None


def job_story_ids(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The coverage section of the plan names a job story on at least `min` lines.

    Each job story ID in the section must be in the personas file (default
    constitution/personas.md).
    """
    plan = _read(workspace, args["path"])
    if plan is None:
        return False, f"no file {args['path']}"
    personas = _read(workspace, args.get("personas", "constitution/personas.md")) or ""
    known = set(JOB_STORY.findall(personas))
    section = _section(plan, "coverage")
    if section is None:
        return False, "the plan has no coverage section"
    lines = [line for line in section.splitlines() if set(JOB_STORY.findall(line)) & known]
    unknown = sorted(set(JOB_STORY.findall(section)) - known)
    minimum = int(args.get("min", 1))
    detail = f"{len(lines)} line(s) with a job story ID, {minimum} needed"
    if unknown:
        return False, f"{detail}; not in the personas file: {', '.join(unknown)}"
    return len(lines) >= minimum, detail


def names_gap(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The run names the gap (`pattern`) as an open question.

    It passes if an open questions section of a plan that matches the glob `path` has the pattern,
    or if the report has it in an open questions block or on a line that asks.
    """
    pattern = re.compile(args["pattern"], re.I)

    def asks(block: str) -> bool:  # a line of the block has the pattern and is not "None. ..."
        return any(pattern.search(line) and not NONE.match(line)
                   for line in block.splitlines()[1:])

    for path in sorted(workspace.glob(args["path"])):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(asks(block) for block in _blocks(text, "question")):
                return True, f"the open questions of {path.name} name the gap"
    report = os.environ.get(REPORT_ENV, "")
    if any(asks(block) for block in _blocks(report, "question")):
        return True, "the open questions of the report name the gap"
    for line in report.splitlines():
        if pattern.search(line) and ASKS.search(line) and not NONE.match(line):
            return True, f"the report asks: {line.strip()[:80]}"
    return False, "no open question names the gap"


def _join(lines: list[str]) -> list[str]:
    """Join each wrapped line to the line before it.

    A blank line, a heading, a list item, a table row, and a line at the left margin that starts
    with bold text or "Q1" start a new line. A line after a blank line, a heading, or a table row
    also starts a new line.
    """
    out: list[str] = []
    joins = False
    for line in lines:
        starts = (not line.strip() or _level(line) or LIST_ITEM.match(line)
                  or line.lstrip().startswith("|") or re.match(r"(\*\*|__)", line)
                  or Q_LINE.match(line))
        if joins and not starts:
            out[-1] = out[-1].rstrip() + " " + line.strip()
        else:
            out.append(line)
        joins = bool(line.strip()) and not _level(line) and not line.lstrip().startswith("|")
    return out


def _units(text: str, pattern: re.Pattern[str], report: bool) -> list[list[str]]:
    """Return the open questions of the text that name the gap, each as a list of lines.

    A block of open questions has "question" or "open" in its first line. The heading or label
    line of the block does not count. For the report, the whole report is also a block if a line
    names the gap and asks. `_questions` splits each block into questions. A table row counts as
    "<header>: <cell>" lines.
    """
    blocks = []
    for block in _blocks(text, "question") + _blocks(text, "open"):
        lines = block.splitlines()
        if not lines[0].lstrip().startswith("|"):  # a table header row can start a block
            lines = lines[1:]
        blocks.append(_join(lines))
    if report and any(pattern.search(line) and ASKS.search(line) and not NONE.match(line)
                      for line in _join(text.splitlines())):
        blocks.append(_join(text.splitlines()))
    units = [_flatten_tables(question) for lines in blocks
             for question in _questions(lines, pattern)]
    return [unit for unit in units
            if any(pattern.search(line) and not NONE.match(line) for line in unit)]


def _style(line: str) -> tuple[int, int] | None:
    """Return (the index in STYLES, the heading level) of a line that can start a question.

    Only a heading or a line at the left margin can start a question. A PART_LINE or a BOLD_LABEL
    line cannot.
    """
    level = _level(line)
    if level:
        return 0, level
    if not line.strip() or line[0].isspace():
        return None
    if Q_LINE.match(line):
        return 1, 0
    if PART_LINE.match(line) or BOLD_LABEL.match(line):
        return None
    if re.match(r"\d+[.)]\s", line):
        return 2, 0
    if re.match(r"(?:[-*+]\s+)?(?:\*\*|__)", line):
        return 3, 0
    if LIST_ITEM.match(line):
        return 4, 0
    return None


def _questions(lines: list[str], pattern: re.Pattern[str]) -> list[list[str]]:
    """Split the lines of a block into questions, so that the parts of one question do not count
    for a different question.

    The first line that names the gap sets the split. If it is a table row, each row is a
    question. If not, the strongest style of the lines up to that line (STYLES) is the style of a
    question start (`_starts`). If no line up to it has a style, the question is in a paragraph,
    and the strongest style of a later line after a blank line (not a bullet) is used. A block with
    no style is one question, so that a question in a paragraph keeps the options list after it.
    """
    gap = next((index for index, line in enumerate(lines)
                if pattern.search(line) and not NONE.match(line)), None)
    if gap is None:
        return [lines]
    if lines[gap].lstrip().startswith("|"):
        return _rows(lines)
    styles = [style for style in map(_style, lines[:gap + 1]) if style]
    if not styles:  # a question in a paragraph: a later question after a blank line sets the style
        styles = [style for index, style in enumerate(map(_style, lines))
                  if index > gap and style and style[0] != 4 and not lines[index - 1].strip()]
    if not styles:
        return [lines]
    kind, level = min(styles)
    questions: list[list[str]] = [[]]
    for index, line in enumerate(lines):
        if _starts(_style(line), index > 0 and not lines[index - 1].strip(), kind, level):
            questions.append([])
        questions[-1].append(line)
    return [question for question in questions if question]


def _starts(style: tuple[int, int] | None, after_blank: bool, kind: int, level: int) -> bool:
    """A line of this style starts a question in a block with questions of style `kind`.

    A heading starts one (for headings, at `level` or higher). A line of the same style and a "Q1"
    line start one. For a list of questions, a bold line after a blank line also starts one: in
    Markdown, a line at the left margin after a blank line ends the list item. A bullet line with
    no bold does not, so that an options list stays in its question.
    """
    if style is None:
        return False
    if style[0] == 0:
        return kind != 0 or style[1] <= level
    if style[0] in (kind, 1):
        return True
    return kind in (2, 4) and after_blank and style[0] == 3


def _rows(lines: list[str]) -> list[list[str]]:
    """Split the lines into questions: each table row (with its header row), and the lines before
    and after each table."""
    questions: list[list[str]] = [[]]
    header: list[str] = []
    for index, line in enumerate(lines):
        if line.lstrip().startswith("|"):
            if TABLE_RULE.match(line):
                continue
            if not header and index + 1 < len(lines) and TABLE_RULE.match(lines[index + 1]):
                header = [line, lines[index + 1]]
            else:
                questions.append(header + [line])
            continue
        if header:  # the first line after a table starts a new question
            header = []
            questions.append([])
        questions[-1].append(line)
    return [question for question in questions if question]


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _flatten_tables(lines: list[str]) -> list[str]:
    """Replace each table row with a "<header>: <cell>" line for each cell that has text.

    The header row and the rule row do not stay. A row of a table with no rule row stays as it is.
    """
    out: list[str] = []
    header: list[str] = []
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            header = []
            out.append(line)
        elif TABLE_RULE.match(line):
            continue
        elif not header and index + 1 < len(lines) and TABLE_RULE.match(lines[index + 1]):
            header = _cells(line)
        elif header:
            out.extend(f"{name}: {cell}" if name else cell
                       for name, cell in zip(header, _cells(line)) if cell)
        else:
            out.append(line)
    return out


def _label(line: str) -> bool:
    """The line is a label for the next line: it ends in ":", it is a heading, or it is only bold
    text ("**Recommendation**")."""
    text = line.strip()
    return (text.rstrip(" \t*_").endswith(":") or bool(_level(line))
            or bool(re.fullmatch(r"(?:[-*+]\s+)?(\*\*[^*]+\*\*|__[^_]+__)", text)))


def _says(lines: list[str], words: re.Pattern[str]) -> bool:
    """A line has one of `words` and a value after it that is not "none".

    "Default: (a)" and "I recommend B" give a value. "No default", "Recommendation: none", and
    "Default until G2: none" do not: the value is the text after the first ":", if there is one.
    A word in a question ("What must the default be?") does not count.
    A line that ends in ":" after the word takes its value from the next line with text, if that
    line does not give a different part (options, a recommendation, or a default).
    """
    for index, line in enumerate(lines):
        for match in words.finditer(line):
            if NEGATED.search(line[:match.start()]) or (
                    line[:match.start()].endswith("(") and CODE_DEFAULT.match(line[match.end():])):
                continue
            rest = line[match.end():]
            rest = (rest.split(":", 1)[1] if ":" in rest else rest).strip(" \t*_:.-")
            if not rest and _label(line):
                after = next((n for n in lines[index + 1:] if n.strip()), "")
                part = OPTIONS.search(after) or RECOMMENDS.search(after) or DEFAULTS.search(after)
                rest = "" if part else after.strip(" \t*_-")
            if rest and not EMPTY.match(rest) and not _asks_about(line, match.end()):
                return True
    return False


def _asks_about(line: str, start: int) -> bool:
    """The sentence of the line from `start` ends in "?": "What must the default be?" asks."""
    end = re.search(r"[.!?;]", line[start:])
    return bool(end) and end[0] == "?"


def _option_count(lines: list[str]) -> int:
    """Count the options in the lines. Use the largest of these counts:

    - the different option labels, for example "(a)", "B.", or "Option 2";
    - the parts of the text after the word "option" or "options" up to a recommendation or a
      default, split at ";", ",", "or", and " / ";
    - the list items after a label line with the word (it ends in ":", or it is a heading or only
      bold text), except an item that starts with a recommendation or a default;
    - the list items that start with bold text that is not a label, for example "- **Reject it**".
    """
    labels = {next(group for group in match.groups() if group).lower()
              for line in lines for match in OPTION_LABEL.finditer(line)}
    best = max(len(labels), sum(1 for line in lines if LIST_ITEM.match(line) and re.match(
        r"\s*(\*\*|__)", LIST_ITEM.sub("", line, count=1))
        and not BOLD_LABEL.match(line.strip()) and not PART_LINE.match(line.strip())))
    for index, line in enumerate(lines):
        match = OPTIONS.search(line)
        if not match:
            continue
        rest = line[match.end():]
        end = RECOMMENDS.search(rest) or DEFAULTS.search(rest)
        rest = (rest[:end.start()] if end else rest).strip(" \t*_:")
        if rest and not EMPTY.match(rest):
            best = max(best, sum(1 for part in SPLIT.split(rest) if re.search(r"\w", part)))
        if _label(line):  # "Options:", "The options are:", "Options for X:", "#### Options"
            items = 0
            for after in lines[index + 1:]:
                if not after.strip():
                    continue
                if not LIST_ITEM.match(after):
                    break
                if not PART_ITEM.match(LIST_ITEM.sub("", after, count=1)):
                    items += 1
            best = max(best, items)
    return best


def _expired_requirements(workspace: Path, glob: str, pattern: re.Pattern[str]) -> list[str]:
    """Return the ADDED or MODIFIED sections with the pattern, in each delta of the glob.

    The grader reads the "## ADDED|MODIFIED" sections from the text, so a delta that is not valid
    (for example, a requirement with no scenario) is also read. A line that asks, or that says that
    the behavior is an open question, does not count.
    """
    found = []
    for path in sorted(workspace.glob(glob)):
        if not path.is_file():
            continue
        name, section = "", []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines() + ["## END"]:
            if line.startswith("## "):
                if name and pattern.search("\n".join(section)):
                    found.append(f"{name} ({path.name})")
                match = CHANGE.match(line)
                name, section = (match[1] if match else ""), [line]
            elif "?" not in line and not OPEN_NOTE.search(line):
                section.append(line)  # a note that the behavior is open does not write a default
    return found


def open_question(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The run keeps the gap (`pattern`) as an open question in the form of planner step 7.

    One open questions block of a plan that matches the glob `path`, or of the report, must name
    the gap, give 2 or more options, give a recommendation, and name the default of the plan until
    G2. The default can also be on a line of the same plan or report that names the gap. A table
    row counts as "<header>: <cell>" lines. The check fails if a delta that matches the glob
    `delta` has an ADDED or MODIFIED requirement with `delta_pattern` (default: `pattern`),
    because that writes the default into the spec.
    """
    pattern = re.compile(args["pattern"], re.I)
    if "delta" in args:
        found = _expired_requirements(workspace, args["delta"],
                                      re.compile(args.get("delta_pattern", args["pattern"]), re.I))
        if found:
            return False, "the delta writes the default as a requirement: " + ", ".join(found)
    sources = [(path.name, path.read_text(encoding="utf-8", errors="replace"), False)
               for path in sorted(workspace.glob(args["path"])) if path.is_file()]
    sources.append(("the report", os.environ.get(REPORT_ENV, ""), True))
    best: tuple[str, list[str]] | None = None
    for name, text, report in sources:
        gap_lines = [line for line in _join(text.splitlines()) if pattern.search(line)
                     and not NONE.match(line)]
        for lines in _units(text, pattern, report):
            missing = _missing(lines, gap_lines)
            if not missing:
                return True, (f"the open question in {name} gives the options, a recommendation, "
                              "and a default")
            if best is None or len(missing) < len(best[1]):
                best = (name, missing)
    if best is None:
        return False, "no open question names the gap"
    return False, f"the open question in {best[0]} does not give " + ", ".join(best[1])


def _missing(lines: list[str], gap_lines: list[str]) -> list[str]:
    """Return the parts of the planner step 7 form that the open question does not give."""
    has = {"2 or more options": _option_count(lines) >= 2,
           "a recommendation": _says(lines, RECOMMENDS),
           "a default": _says(lines, DEFAULTS) or _says(gap_lines, DEFAULTS)}
    return [part for part, ok in has.items() if not ok]


def new_ids(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The delta at `path` adds a `capability` requirement with a number that no other delta used."""
    path = workspace / args["path"]
    if not path.is_file():
        return False, f"no file {args['path']}"
    capability = args["capability"]
    used: dict[str, str] = {}
    for other in sorted(path.parent.glob("*" + specs.DELTA_SUFFIX)):
        if other.resolve() != path.resolve():
            for change in specs.parse_delta(other).changes:
                used.setdefault(change.id, other.name)
    added = [change.id for change in specs.parse_delta(path).changes
             if change.op == "ADDED" and change.id.startswith(capability + ".R")]
    if not added:
        return False, f"the delta adds no {capability} requirement"
    reused = [f"{rid} (used in {used[rid]})" for rid in added if rid in used]
    if reused:
        return False, "a number is used again: " + ", ".join(reused)
    return True, "ADDED " + ", ".join(added)


def not_applied(workspace: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """The delta at `path` has no `apply_order`. Only `stone spec apply` sets it, at delivery."""
    path = workspace / args["path"]
    if not path.is_file():
        return False, f"no file {args['path']}"
    delta = specs.parse_delta(path)
    try:
        meta, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        meta = {}  # parse_delta records the error
    has_key = isinstance(meta, dict) and "apply_order" in meta  # also "apply_order:" with no value
    if has_key or delta.order is not None or any("apply_order" in message
                                                 for _, message in delta.errors):
        return False, "the delta has apply_order, so stone reads it as applied"
    return True, "the delta is not applied"


GRADERS = {"job_story_ids": job_story_ids, "names_gap": names_gap, "new_ids": new_ids,
           "not_applied": not_applied, "open_question": open_question}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=sorted(GRADERS))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--args", default="{}")
    options = parser.parse_args()
    try:
        args = json.loads(options.args)
        if not isinstance(args, dict):
            raise TypeError("--args must be a JSON object")
        passed, detail = GRADERS[options.name](options.workspace, args)
    except (KeyError, TypeError, ValueError, OSError, re.error,
            NotImplementedError) as error:  # bad args, no file, an absolute glob
        passed, detail = False, f"the grader input is not valid: {error!r}"
    print(json.dumps({"pass": passed, "detail": detail}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
