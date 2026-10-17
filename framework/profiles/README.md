# Profiles

A profile configures the [workflow model](../workflow-model.md) for one type of work. Each profile
file has YAML frontmatter that the generator reads, and a body that people read.

## Profile matrix

| Profile | Scope | Plan form | Gates | Changes code | Key checks beyond the baseline |
| --- | --- | --- | --- | --- | --- |
| [full-project](full-project.md) | A new product or a major area | Plan artifact for each slice | G1 G2 G3 G4 G5 | yes, through slices | K4 K5 K8 |
| [app-slice](app-slice.md) | One vertical feature through all layers | Plan artifact | G1 G2 G3 G4 | yes | K4 K5 K8 K10 |
| [single-ticket](single-ticket.md) | One small, clear change | Decision log | G1 (check) G3 G4 | yes | K5 if the ticket has UI behavior |
| [bug-triage](bug-triage.md) | Sort and confirm incoming bugs | none | G4 (labels) | no | — |
| [debugging](debugging.md) | Find and fix the root cause of one defect | Decision log | G1 (check) G3 G4 | yes | K12 (bisect) |
| [code-audit](code-audit.md) | Find defects, risks, and improvements in an area | none | G1 (scope) G4 (findings) | no | Reads K8 K9 K10 results |
| [refactor-migration](refactor-migration.md) | Change structure, keep behavior | Plan artifact | G1 G2 G3 G4 | yes | K8 K10 K12 |
| [dependency-upgrade](dependency-upgrade.md) | Upgrade one dependency | Decision log | G3 G4 | yes | K4 K5 |
| [spike](spike.md) | Answer one question with throwaway code | none | G1 (question) G4 (findings) | throwaway only | K16 |

Baseline checks for each profile that changes code: K1 K2 K3 K6 K7 K9 K13 K14. See
[checks.md](../checks.md).

## Profile template

Copy [`_template.md`](_template.md) to add a profile. A new profile MUST:

1. Use only the stages, roles, gates, and checks in the workflow model.
2. Declare `plan_form` and `gates` (P7).
3. Have an eval set before it is used on real work (P5).
