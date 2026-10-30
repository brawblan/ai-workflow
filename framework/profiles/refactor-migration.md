---
id: refactor-migration
name: Refactor or migration
version: 0.1.0
purpose: Change the structure of the code, or move it to a new library or platform, with no change in behavior.
triggers: [command]
stages: [intake, shape, plan, build, test, verify, review, deliver, learn]
roles: [shaper, planner, tester, implementer, reviewer]
plan_form: plan-artifact
mode: hybrid
gates:
  G1: human
  G2: human
  G3: required
  G4: human
  G5: if-needed
checks: [K1, K2, K3, K6, K7, K8, K9, K10, K12, K13, K14, K17, K20, K22]
limits:
  pr_changed_lines: 600
outputs: [plan, pr]
---

# Refactor or migration

The rule: structure changes and behavior changes never go in the same commit.

## Use when

- The goal is a better structure, a new library, or a new platform, with the same behavior.

## Do not use when

- The behavior must change too. Do the refactor first with this profile. Then change the behavior
  with [single-ticket](single-ticket.md) or [app-slice](app-slice.md).

## Flow

1. Run the shaper. The ticket states the target structure and the behavior that must not change.
2. Start the tester in a fresh session. It writes characterization tests for the current behavior.
   The tests MUST pass on the current code.
3. Start the planner in a fresh session. It writes the plan artifact and the progress file. Each task
   is one small structural step. It writes the new fitness rules (K8) for the target structure as
   text in the plan. The planner changes only `paths.plans`, so it cannot write the K8 config. A
   human adds the rules to the K8 config (D51).
4. A human approves the plan (G2).
5. For each task, start the implementer in a fresh session. It makes one structural step. All
   characterization tests MUST pass after each step.
6. For a migration, run differential tests (K12). The old and the new code get the same inputs. They
   must give the same outputs.
7. For many files with the same change, fan out one session for each file or group. Test the
   prompt on 2 or 3 files first.
8. Start the reviewer in a fresh session. It checks that no behavior changed.
9. Open PRs under the size limit. A human approves each PR (G4).

## Exit criteria

- All characterization tests pass with no change to their assertions.
- The new fitness rules pass.
- Mutation score on the changed code is at or above the limit.

## Failure handling

| Failure | Action |
| --- | --- |
| A characterization test must change | Stop. That is a behavior change. A human decides. |
| The differential test finds a difference | Stop. Record the input. Find which side is correct. |

## Evidence

Dossier IDs: B5, B13, B14, C3, C9, D2, E13.
