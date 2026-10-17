# Customization

The core stays generic. Each repo, profile, and task adds specificity through set files. This file
defines where specificity goes and which layer wins.

## Layers

| Order | Layer | Where | Example content |
| --- | --- | --- | --- |
| 1 | Framework core | `framework/` in this repo | Principles, gates, profiles |
| 2 | Adapter | `framework/adapters/<name>.md` and its templates | File paths and formats for one harness |
| 3 | Repo config | `.ai-workflow/config.yaml` in the target repo | Commands, paths, limits, owners |
| 4 | Profile override | `.ai-workflow/profiles/<profile>.yaml` in the target repo | Extra checks, a different size limit |
| 5 | Task | The ticket fields | Acceptance criteria, non-goals, a waiver |

A later layer wins over an earlier layer, with these limits:

1. A later layer MAY add a gate, a check, or a protected path.
2. A later layer MAY tighten a limit.
3. A later layer MUST record a waiver to remove a gate, remove a check, or loosen a limit. A waiver
   has a reason, an owner, and an end date.
4. No layer can remove G3 or G5 (see [gates.md](gates.md)).

## Repo config (`.ai-workflow/config.yaml`)

```yaml
framework_version: 0.1.0           # tag of brawblan/ai-workflow
harness: <harness-adapter-name>    # a file name in framework/adapters/
spec_tool: plain                   # plain, or a spec-tool adapter name
profiles: [single-ticket, bug-triage, debugging]
branches:
  integration: dev
  main: main
commands:                          # exactly as a person types them
  install: <command>
  lint: <command>
  typecheck: <command>
  test_unit: <command>
  test_acceptance: <command>
  all_checks: <command>
paths:
  source: [src/]
  tests: [tests/]                  # protected for the implementer
  checks: [.github/workflows/, .ai-workflow/checks/]
  plans: docs/plans/
limits:
  pr_changed_lines: 400
  function_lines: 60
  cyclomatic: 10
  mutation_score_changed_code: 0.6
owners:
  default: <github-username>
waivers: []
```

The generator fills the facts that it can find. It asks a human for the rest. It writes
`TODO(<owner>)` for an unknown value. It does not guess.

## Profile override (`.ai-workflow/profiles/<profile>.yaml`)

```yaml
extends: single-ticket
checks_add: [K8]
limits:
  pr_changed_lines: 250
waivers:
  - gate: G4
    reason: <reason>
    owner: <github-username>
    until: 2027-01-31
```

## Hand-written components

A repo can add its own rules, skills, roles, or hooks. Put them in `.ai-workflow/local/`. Add each one
to the manifest with `source: repo`. The lifecycle rules apply to them too.
