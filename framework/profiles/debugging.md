---
id: debugging
name: Debugging
version: 0.1.0
purpose: Find the root cause of one confirmed defect, prove it with a failing test, and fix it.
triggers: [command, label:agent-ready]
stages: [intake, shape, build, test, verify, review, deliver, learn]
roles: [investigator, tester, implementer, reviewer]
plan_form: decision-log
mode: hybrid
gates:
  G1: check
  G2: skip
  G3: required
  G4: human
  G5: if-needed
checks: [K1, K2, K3, K6, K7, K9, K12, K13, K14]
limits:
  pr_changed_lines: 200
outputs: [pr]
---

# Debugging

The tester writes the failing test before the fix. So the test comes from the bug report, not from
the fix.

## Use when

- A defect is confirmed and has reproduction steps.

## Do not use when

- The report is not confirmed. Use [bug-triage](bug-triage.md).

## Flow

1. Run the G1 check: the issue has reproduction steps, an expected result, and an actual result.
2. Start the tester in a fresh session. It writes a test that reproduces the defect. The test MUST
   fail on the current code.
3. Run the test. If it passes, stop. The defect is not reproduced. Send the issue back to triage.
4. Start the investigator in a fresh session. It finds the root cause:
   1. If a known good commit exists, run `git bisect run` with the failing test.
   2. Read the code path. Write the cause and the evidence in the decision log.
5. Start the implementer in a fresh session. Give it the issue, the failing test, and the decision
   log. It fixes the root cause, not the symptom.
6. Run the checks (G3). The new test and all old tests MUST pass.
7. Start the reviewer in a fresh session. It checks that the fix addresses the root cause and does
   not hide the error.
8. Open the PR. A human approves it (G4).

## Exit criteria

- A test fails before the fix and passes after the fix.
- The decision log names the root cause with evidence.
- No error is suppressed (no empty catch, no skipped test).

## Failure handling

| Failure | Action |
| --- | --- |
| The defect cannot be reproduced in a test | Stop. Record what was tried. A human decides. |
| The fix needs a design change | Stop. Open an [app-slice](app-slice.md) or [refactor-migration](refactor-migration.md) ticket. |
| The fix weakens or deletes an assertion | K6 fails or the reviewer flags it. Reject the change. |

## Evidence

Dossier IDs: B5, B12, B14, E3, E5.
