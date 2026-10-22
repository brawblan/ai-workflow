# Gates

A gate stops the work until its approver passes it. The framework has a fixed set of gates. Each
profile selects gates from this set. A repo can add gates. To remove a gate, a repo records a
waiver with a reason.

| Gate | Name | Position | Approver | Passes when |
| --- | --- | --- | --- | --- |
| G1 | Ready | After Shape | human, or a check for low-risk profiles | The ticket meets the Definition of Ready. |
| G2 | Plan approved | After Plan | human | A human approves the plan artifact. |
| G3 | Checks pass | After Verify | checks only | All checks for the profile pass in CI. |
| G4 | Change approved | After Review | human | A human approves the PR after the agent review. |
| G5 | Release approved | Before Deliver, or before any destructive action | human | A human approves the release or the action. |

## Rules

1. G3 is always on for each profile that changes code on a branch that can merge. No waiver can
   remove G3. With `adoption: opt-in`, G3 runs only for a marked PR (D58). Spike code never merges (check K16), so G3 does not apply to it. With
   `delivery: local`, G3 stays on, but a person runs it on a machine with `stone gate` (D56).
2. G5 is always on for each destructive action, in each profile. See P9.
3. A gate approver cannot be the role that made the work. An agent cannot approve G1, G2, G4, or G5.
   The only exception is the [solo developer](modes.md#solo-developer) rule for G4.
4. A gate decision is recorded where the work is: a label, a PR review, or a CI status.
5. Before a human passes G2 or G4, the agent states its confidence and the open risks (P11).
6. The [mode](modes.md) does not change the gates. Only the profile and recorded waivers change them.
7. A specialist review with `blocks: true` and a high finding stops G4 until a human decides (D59).
   Check K20 enforces this in G3 (D66).

## Gate selection by profile

| Profile | G1 | G2 | G3 | G4 | G5 |
| --- | --- | --- | --- | --- | --- |
| [full-project](profiles/full-project.md) | human | human | yes | human | always |
| [app-slice](profiles/app-slice.md) | human | human | yes | human | if needed |
| [single-ticket](profiles/single-ticket.md) | check | — | yes | human | if needed |
| [bug-triage](profiles/bug-triage.md) | — | — | — | human (label decisions) | if needed |
| [debugging](profiles/debugging.md) | check | — | yes | human | if needed |
| [code-audit](profiles/code-audit.md) | human (scope) | — | — | human (which findings become tickets) | if needed |
| [refactor-migration](profiles/refactor-migration.md) | human | human | yes | human | if needed |
| [dependency-upgrade](profiles/dependency-upgrade.md) | — | — | yes | human (a repo waiver MAY skip it for patch versions) | if needed |
| [adapter-refresh](profiles/adapter-refresh.md) | — | — | yes | human | if needed |
| [spike](profiles/spike.md) | human (question and time box) | — | — | human (reads findings) | if needed |

"If needed" means: G5 applies when the work includes a release or a destructive action. G5 is never
skipped (rule 2).

Profile frontmatter values: `human`, `check`, `skip`, `required` (G3), `always`, `if-needed` (G5).
