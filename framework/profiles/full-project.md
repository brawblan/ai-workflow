---
id: full-project
name: Full project
version: 0.1.0
purpose: Start a new product or a major area, and break it into app slices.
triggers: [command]
stages: [intake, shape, plan, verify, review, deliver, learn]   # the walking skeleton runs as an app-slice
roles: [shaper, planner, reviewer]
plan_form: plan-artifact
mode: hybrid
gates:
  G1: human
  G2: human
  G3: required
  G4: human
  G5: always
checks: [K1, K2, K3, K4, K5, K6, K7, K8, K9, K13, K14, K15, K17]
limits:
  pr_changed_lines: 600
outputs: [plan, pr]
---

# Full project

This profile does not build features. It makes the foundation and the backlog. Each feature then
runs as an [app-slice](app-slice.md).

## Use when

- A repo is new, or a large new area starts.

## Do not use when

- The work fits in one feature. Use [app-slice](app-slice.md).

## Flow

1. Run the shaper with the human. Write the project foundation: mission, non-goals, principles,
   tech stack, and roadmap.
2. A human approves the foundation (G1).
3. Start the planner in a fresh session. It writes:
   - The architecture rules as fitness checks (K8), not as prose.
   - The walking skeleton: the smallest app that builds, deploys, and runs one end-to-end test.
   - A backlog of app slices, in order. Each slice has acceptance criteria and a test oracle.
4. A human approves the architecture and the backlog (G2).
5. Build the walking skeleton as the first app slice. Its checks become the baseline for all later
   slices.
6. Run the generator for the repo. It writes the instruction file, roles, hooks, and CI checks.
7. A human approves the setup PR (G4).
8. Start each later slice with the [app-slice](app-slice.md) profile.

## Exit criteria

- The walking skeleton passes all baseline checks in CI.
- The backlog has at least the first 3 slices with complete Definition of Ready fields.
- The instruction file is under the line limit (K15).

## Failure handling

| Failure | Action |
| --- | --- |
| A principle cannot be a check | Keep it as an instruction. Fill `why_not_a_check` in the manifest. |
| The first slices are vague | Stop. The first tickets set the pattern for all others. Shape them again. |

## Evidence

Dossier IDs: C3, C7, D10, D11, A7, A10, H2.
