---
id: spike
name: Spike or prototype
version: 0.1.0
purpose: Answer one question with throwaway code in a fixed time box.
triggers: [command]
stages: [intake, shape, build, review, learn]
roles: [shaper, investigator]
plan_form: none
mode: human-centric
gates:
  G1: human
  G2: skip
  G3: skip
  G4: human
  G5: if-needed
checks: [K13, K16]
limits: {}
outputs: [report]
---

# Spike or prototype

The output is an answer, not code. The code stays on a spike branch and never merges.

## Use when

- A decision needs facts that only a quick build can give (for example "Can library X do Y?").

## Do not use when

- The code is meant to stay. Use [app-slice](app-slice.md).

## Flow

1. Run the shaper. Write the question, the time box, and what counts as an answer (G1).
2. Create a branch with the `spike/` prefix.
3. Start the investigator in a fresh session. It builds the smallest code that answers the question.
   It can skip tests.
4. Stop at the time box, also if the answer is not complete.
5. Write the findings report: the answer, the evidence, the limits, and a recommendation.
6. A human reads the report and decides the next step (G4).

> CAUTION: K16 blocks a PR from a `spike/` branch to the main branch. To keep spike code, rebuild it
> with a profile that has a Build stage and gate G3.

## Exit criteria

- The report answers the question, or says why it cannot.

## Evidence

Dossier IDs: E10, D4.
