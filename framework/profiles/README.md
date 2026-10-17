# Profiles

A profile configures the [workflow model](../workflow-model.md) for one type of work. Each profile
file has YAML frontmatter that the generator reads, and a body that people read.

## Profile matrix

| Profile | Scope | Default mode | Plan form | Gates | Changes code | Key checks beyond the baseline |
| --- | --- | --- | --- | --- | --- | --- |
| [full-project](full-project.md) | A new product or a major area | hybrid | Plan artifact for each slice | G1 G2 G3 G4 G5 | yes, through slices | K4 K5 K8 |
| [app-slice](app-slice.md) | One vertical feature through all layers | hybrid | Plan artifact | G1 G2 G3 G4 | yes | K4 K5 K8 K10 |
| [single-ticket](single-ticket.md) | One small, clear change | agent-centric | Decision log | G1 (check) G3 G4 | yes | K5 if the ticket has UI behavior |
| [bug-triage](bug-triage.md) | Sort and confirm incoming bugs | agent-centric | none | G4 (labels) | no | — |
| [debugging](debugging.md) | Find and fix the root cause of one defect | hybrid | Decision log | G1 (check) G3 G4 | yes | K12 (bisect) |
| [code-audit](code-audit.md) | Find defects, risks, and improvements in an area | agent-centric | none | G1 (scope) G4 (findings) | no | Reads K8 K9 K10 results |
| [refactor-migration](refactor-migration.md) | Change structure, keep behavior | hybrid | Plan artifact | G1 G2 G3 G4 | yes | K8 K10 K12 |
| [dependency-upgrade](dependency-upgrade.md) | Upgrade one dependency | agent-centric | Decision log | G3 G4 | yes | K4 K5 |
| [adapter-refresh](adapter-refresh.md) | Update a model profile after a vendor release (framework repo only) | agent-centric | Decision log | G3 G4 | yes, adapter files only | Evals with and without each idiom |
| [spike](spike.md) | Answer one question with throwaway code | human-centric | none | G1 (question) G4 (findings) | throwaway only | K16 |

Baseline checks for each profile that changes code: K1 K2 K3 K6 K7 K9 K13 K14. See
[checks.md](../checks.md).

Each profile can run in each mode. The default mode is a starting point. See [modes.md](../modes.md)
for the stage drivers of each mode, and [customization.md](../customization.md) to change the mode.

### How to read a flow in each mode

- A flow step says "Start the <role>". The mode decides the actor. If the stage driver is `human`
  or `pair`, the human does that step.
- "In a fresh session" applies only when an agent drives the stage.
- The separation rule applies in all modes: the implementer never writes the tests.

## Profile template

Copy [`_template.md`](_template.md) to add a profile. A new profile MUST:

1. Use only the stages, roles, gates, and checks in the workflow model.
2. Declare `plan_form`, `gates` (P7), and a default `mode`.
3. Have an eval set before it is used on real work (P5).
