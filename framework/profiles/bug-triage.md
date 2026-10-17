---
id: bug-triage
name: Bug triage
version: 0.1.0
purpose: Sort new bug reports, confirm them, and make each confirmed bug ready for debugging.
triggers: [ci:issue-opened, schedule:daily, command]
stages: [intake, shape, review, learn]
roles: [investigator]
plan_form: none
mode: agent-centric
gates:
  G1: skip
  G2: skip
  G3: skip
  G4: human
  G5: if-needed
checks: []
limits: {}
outputs: [labels, report]
---

# Bug triage

This profile does not change code. It changes issue fields and writes a short report on each issue.

## Use when

- New bug reports arrive and must be sorted.

## Do not use when

- A bug is already confirmed and has reproduction steps. Use [debugging](debugging.md).

## Flow

1. Start the investigator in a fresh session for each new bug report.
2. Find duplicates. Search open and closed issues for the same symptom.
3. Try to reproduce the bug from the report. Use only a sandbox or a test environment.
4. Write the triage report as an issue comment:
   - Reproduced: yes, no, or not tried (with the reason)
   - Reproduction steps, expected result, and actual result
   - Suspected area of the code (file paths), with a confidence level
   - Suggested severity and labels, each with a one-sentence reason
   - Duplicate of: issue number, or none
5. A human approves the labels and the severity (G4). The investigator applies only approved labels.
6. If the bug is confirmed, mark the issue ready for the [debugging](debugging.md) profile.

> WARNING: The investigator reads untrusted text from bug reports. Do not give it production data or
> an outbound channel other than issue comments (P9, lethal trifecta).

## Exit criteria

- Each new report has a triage comment.
- Each confirmed bug has reproduction steps, and a human approved its severity.

## Failure handling

| Failure | Action |
| --- | --- |
| The bug cannot be reproduced | Label it "needs info". Ask the reporter for the missing facts. |
| The report has a secret or private data | Do not copy it into the comment. Tell the repo owner. |

## Evidence

Dossier IDs: F4, H4, D1.
