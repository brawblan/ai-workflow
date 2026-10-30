---
id: app-slice
name: App slice
version: 0.3.0
purpose: Deliver one vertical feature through all layers (UI, API, data) as a small set of PRs.
triggers: [command, label:agent-ready]
stages: [intake, shape, plan, build, test, verify, review, deliver, learn]
roles: [shaper, planner, implementer, tester, reviewer]
plan_form: plan-artifact
mode: hybrid
gates:
  G1: human
  G2: human
  G3: required
  G4: human
  G5: if-needed
checks: [K1, K2, K3, K4, K5, K6, K7, K8, K9, K10, K13, K14, K17, K18, K19, K20, K22]
limits:
  pr_changed_lines: 600
outputs: [plan, pr]
---

# App slice

## Use when

- A user-visible feature touches more than one layer.
- The approach needs a decision that a human must approve.

## Do not use when

- The change is in one area and is clear. Use [single-ticket](single-ticket.md).
- The work is a new product or many features. Use [full-project](full-project.md).

## Flow

1. Run the shaper with the human until the ticket meets the Definition of Ready (G1). The ticket
   names the personas that the slice serves.
2. Start the planner in a fresh session. It writes the plan artifact and the progress file. The
   plan maps each acceptance criterion to a job story. If the slice changes a behavior, the
   planner also writes the spec delta (see [Specs](../workflow-model.md#specs)).
3. The progress file lists each task with its acceptance test steps. Each task starts with
   `passes: false`.
4. A human reads the plan and approves it (G2). The human edits the plan, not the code.
5. For each task in the progress file:
   1. Start the implementer in a fresh session. It does one task and updates the decision log.
   2. Start the tester in a fresh session. It writes the acceptance tests from the job stories, and
      the integration tests for the task.
   3. Run the checks (G3). If they pass, set `passes: true` for the task.
6. Start the reviewer in a fresh session. It compares the diff with the plan and reports scope drift.
7. Run `stone spec apply <id>` if the plan has a spec delta. Commit its output alone, with
   `Role: generator`. Open one PR for each group of tasks that stays under the size limit.
8. A human approves each PR (G4).

## Exit criteria

- All tasks in the progress file have `passes: true`.
- Acceptance tests run the feature end to end, as the persona does.
- Each acceptance criterion maps to a job story, and K18 passes.
- The spec delta is applied, and K19 passes.
- Fitness checks (K8) pass.

## Failure handling

| Failure | Action |
| --- | --- |
| The build needs a change that the plan does not have | Stop. Update the plan. Get G2 again for the change. |
| An end-to-end test cannot run in CI | Record a waiver. Add a manual verify step to the PR. |
| Scope drift in the review | Remove the extra change, or add it to a new ticket. |

## Evidence

Dossier IDs: B8, B9, C3, D2, D9, D10, D12, D13, E2, E3, E4, E8.
