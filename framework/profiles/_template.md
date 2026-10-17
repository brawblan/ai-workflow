---
id: <kebab-case-id>
name: <Name>
version: 0.1.0
purpose: <One sentence.>
triggers: [command]                 # command | label:<name> | schedule:<cron> | ci:<event>
stages: [intake, shape, plan, build, test, verify, review, deliver, learn]
roles: [shaper, planner, implementer, tester, reviewer]
plan_form: plan-artifact            # plan-artifact | decision-log | none
mode: hybrid                        # agent-centric | hybrid | human-centric (default preset, see modes.md)
gates:
  G1: human                         # human | check | skip
  G2: human                         # human | skip
  G3: required                      # required | skip (skip only if no code can merge)
  G4: human                         # human | skip
  G5: if-needed                     # always | if-needed (never skip, see gates.md rule 2)
checks: [K1, K2, K3, K6, K7, K9, K13, K14, K17]
limits:
  pr_changed_lines: 600
outputs: [pr]                       # pr | report | labels | plan
---

# <Name>

## Use when

- <condition>

## Do not use when

- <condition> Use [<other profile>](<other>.md) instead.

## Flow

1. <step>

## Exit criteria

- <criterion>

## Failure handling

| Failure | Action |
| --- | --- |
| <failure> | <action> |

## Evidence

Dossier IDs: <IDs>.
