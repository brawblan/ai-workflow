---
id: single-ticket
name: Single ticket
version: 0.2.0
purpose: Deliver one small, clear change as one PR.
triggers: [command, label:agent-ready]
stages: [intake, shape, build, test, verify, review, deliver, learn]
roles: [shaper, implementer, tester, reviewer]
plan_form: decision-log
mode: agent-centric
gates:
  G1: check
  G2: skip
  G3: required
  G4: human
  G5: if-needed
checks: [K1, K2, K3, K6, K7, K9, K13, K14, K17, K18, K20]
limits:
  pr_changed_lines: 600
outputs: [pr]
---

# Single ticket

## Use when

- The ticket has testable acceptance criteria.
- A person can describe the change in one or two sentences.
- The change is in one area of the code.

## Do not use when

- The change crosses several layers or needs a design decision. Use [app-slice](app-slice.md).
- The cause of a defect is not known. Use [debugging](debugging.md).

## Flow

1. Read the ticket. Run the G1 check for the Definition of Ready fields.
2. If a field is missing, run the shaper with the ticket author. Stop until the fields are complete.
3. Start the implementer in a fresh session. Give it the ticket only.
4. The implementer changes the code and writes the decision log.
5. Start the tester in a fresh session. Give it the ticket and the diff.
6. The tester writes tests for each acceptance criterion and writes the test report. If the ticket
   names personas, the tester writes the acceptance tests from their job stories.
7. Run the checks (G3). If a check fails, send the output to the implementer. Stop after 3 loops.
8. Start the reviewer in a fresh session. Give it the ticket, the diff, the check output, and the
   decision log.
9. Open the PR with the evidence, the decision log, the review findings, and a confidence statement.
10. A human approves or rejects the PR (G4).

## Exit criteria

- Each acceptance criterion has a test from the tester, and the test passes.
- All checks pass.
- A human approved the PR.

## Failure handling

| Failure | Action |
| --- | --- |
| The tester and the implementer disagree on behavior | Stop. Ask the ticket author. Add the answer to the ticket. |
| 3 failed Build–Verify loops | Stop. Report the last check output. A human decides. |
| The diff is over the size limit | Stop. Split the ticket, or record a waiver. |
| The implementer changes a protected path | K6 fails. Revert that change. Tell the tester. |

## Evidence

Dossier IDs: B1, B10, B15, D1, D3, D4, D13, E12, H4.
