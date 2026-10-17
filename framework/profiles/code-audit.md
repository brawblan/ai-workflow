---
id: code-audit
name: Code audit
version: 0.1.0
purpose: Find defects, risks, and improvements in one area of the code, and turn approved findings into tickets.
triggers: [command, schedule:monthly]
stages: [intake, shape, review, learn]
roles: [investigator, reviewer]
plan_form: none
gates:
  G1: human
  G2: skip
  G3: skip
  G4: human
  G5: if-needed
checks: []
limits: {}
outputs: [report]
---

# Code audit

This profile does not change code. It writes a findings report. A human selects which findings
become tickets.

## Use when

- You need a structured view of the health of an area (for example before a refactor).
- A recurring scan for drift from the repo principles.

## Do not use when

- You already know the defect. Use [debugging](debugging.md).

## Flow

1. A human sets the scope: the paths, the dimensions, and a time box (G1).
2. Run the deterministic tools first: complexity (K9), fitness (K8), mutation score (K10), CRAP
   score, secret scan (K13). Save the raw output.
3. Start one investigator for each dimension in a fresh session. Default dimensions: correctness,
   security, architecture drift, test strength, maintainability.
4. Each investigator writes findings with file paths and evidence. It uses the tool output first.
5. Start the reviewer in a fresh session. It tries to refute each finding. It removes findings
   without evidence.
6. Write the report in this order: defects, risks, then improvements. Give each finding a severity
   (High, Medium, Low) and a fix.
7. A human selects the findings that become tickets (G4).

## Exit criteria

- Each finding has evidence (a file path and a line, or a tool result).
- A human made a decision on each High finding.

## Failure handling

| Failure | Action |
| --- | --- |
| Too many findings to review | Report only High and Medium. Put the rest in an appendix. |
| A finding needs a check that does not exist | Add a ticket to create the check (P6). |

## Evidence

Dossier IDs: B7, B13, C3–C6, C9, E6, B11.
