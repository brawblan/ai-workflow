"""Template values that belong to the OpenCode adapter.

OpenCode has no hook before a file edit. So each role file ends with `edit` rules that give the
same paths as the protect-paths hook of the reference adapter (#326). The last rule that matches
wins. A `*` in a rule also matches `/`, so a glob rule can cover more paths than check K6.
"""

from __future__ import annotations

import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from stone.render import CORE_PROTECTED, FOLDER_DEFAULTS
from stone.specs import TICKET_ID

COMPONENTS = Path(__file__).resolve().parent / "components.yaml"


CASE_WORD = re.compile(r"(?:\[(?:A[a]|B[b]|C[c]|D[d]|E[e]|F[f]|G[g]|H[h]|I[i]|J[j]|K[k]|L[l]|M[m]|N[n]|"
                       r"O[o]|P[p]|Q[q]|R[r]|S[s]|T[t]|U[u]|V[v]|W[w]|X[x]|Y[y]|Z[z])\])+")


def case_forms(path: str) -> list[str]:
    """Return each form of a path with each word of case classes in upper case or in lower case.

    `[Aa][Gg][Ee][Nn][Tt][Ss].[Mm][Dd]` gives AGENTS.MD, AGENTS.md, agents.MD, and agents.md.
    """
    words = CASE_WORD.findall(path)
    parts = CASE_WORD.split(path)
    forms = []
    for cases in itertools.product((str.upper, str.lower), repeat=len(words)):
        text = parts[0]
        for case, word, part in zip(cases, words, parts[1:]):
            text += case(word[1::4]) + part  # the first letter of each class
        forms.append(text)
    return forms


def variants(path: str) -> list[str]:
    """Return the OpenCode forms of one repo path glob.

    OpenCode has no `[...]` class, so a word of classes of one letter in two cases gives the
    upper-case and the lower-case word. A `**/` start gives the root form and the form in any folder.
    """
    forms = case_forms(path.replace(TICKET_ID, "*").rstrip("/"))
    if any("[" in form for form in forms):
        print(f"warning: the path '{path}' has a [...] class that OpenCode cannot match. "
              "Its OpenCode rule keeps the class as text, so it can cover fewer paths.",
              file=sys.stderr)
    if forms[0].startswith("**/"):
        forms = [form for item in forms for form in (item[3:], "*/" + item[3:])]
    return forms


def resources(paths: list[str]) -> list[str]:
    """Return the rule resources for repo paths: the path, and each path under it."""
    out: list[str] = []
    for path in paths:
        for base in variants(str(path)):
            for item in (base, base + "/*"):
                if item and item not in out:
                    out.append(item)
    return out


def edit_rules(effect: str, paths: list[str]) -> list[dict[str, str]]:
    return [{"action": "edit", "resource": item, "effect": effect} for item in resources(paths)]


def rule_lines(rules: list[dict[str, str]]) -> str:
    """Return rules as lines of the `permissions` list in a role file."""
    return "\n".join(f"  - action: {rule['action']}\n    resource: {json.dumps(rule['resource'])}\n"
                     f"    effect: {rule['effect']}" for rule in rules)


def _list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    return [str(item) for item in value] if isinstance(value, list) else [str(value)]


def harness_paths(config: dict[str, Any]) -> list[str]:
    """Return the folders that no role changes: the adapter folders and `.cornerstone/` (D76)."""
    registry = yaml.safe_load(COMPONENTS.read_text(encoding="utf-8")) or {}
    paths = _list(registry.get("protected_dirs")) + CORE_PROTECTED
    if config.get("protect_instruction_files") is True:  # D87
        paths += _list(registry.get("instruction_files"))
    return paths


def role_edit_rules(config: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Return the `edit` rules of each role that edits files, in the order of the hook checks."""
    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    folder = {key: _list(paths.get(key)) or [default] for key, default in FOLDER_DEFAULTS.items()}
    tests, checks = _list(paths.get("tests")), _list(paths.get("checks"))
    harness = harness_paths(config)
    protected = tests + checks + harness + folder["specs"]
    deny_all = [{"action": "edit", "resource": "*", "effect": "deny"}]
    return {
        "implementer": edit_rules("deny", protected),
        "tester": deny_all + edit_rules("allow", tests) + edit_rules("deny", harness),
        "planner": deny_all + edit_rules("allow", folder["plans"]) + edit_rules("deny", protected),
        "investigator": (deny_all + edit_rules("allow", folder["reports"])
                         + edit_rules("deny", harness)),
    }


def shaper_rules(config: dict[str, Any]) -> list[dict[str, str]]:
    """Return the shaper rules. A file ticket also needs an edit of the ticket file."""
    section = config.get("tickets")
    section = section if isinstance(section, dict) else {}
    actions = ["read", "grep", "glob", "shell"]
    rules = [{"action": "*", "resource": "*", "effect": "deny"}]
    rules += [{"action": action, "resource": "*", "effect": "allow"} for action in actions]
    if section.get("source") == "file" and section.get("path"):
        rules.append({"action": "edit", "resource": str(section["path"]).replace(TICKET_ID, "*"),
                      "effect": "allow"})
    return rules


def config_rules(config: dict[str, Any]) -> list[dict[str, str]]:
    """Return the project rules for a session with no role: no edit of a harness path, no outside path."""
    return ([{"action": "external_directory", "resource": "*", "effect": "deny"}]
            + edit_rules("deny", harness_paths(config)))


def values(config: dict[str, Any]) -> dict[str, str]:
    """Return the permission rules of the role files and the project config."""
    out = {f"{role}_edit_rules": rule_lines(rules)
           for role, rules in role_edit_rules(config).items()}
    out["shaper_permissions"] = json.dumps(shaper_rules(config))
    out["config_permissions_json"] = json.dumps(config_rules(config))
    return out
