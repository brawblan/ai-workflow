# Make a small change

Use this guide for one small, clear change in one area of the code. You can describe it in one or
two sentences.

| | |
| --- | --- |
| Profile | [single-ticket](../../framework/profiles/single-ticket.md) |
| Default mode | agent-centric: ticket in, PR out |
| Gates | G1 (a check on the ticket fields), G3, G4 |
| Status | Works today. You start each role by hand. |

Do not use this guide if the change crosses several layers or needs a design decision. Use
[Build a feature](build-a-feature.md). If you do not know the cause of a defect, use
[Fix a bug](fix-a-bug.md).

## Flow

```mermaid
flowchart LR
  T[Ticket] -->|G1| I[implementer] --> TE[tester] --> C[checks] -->|G3| R[reviewer] --> PR[PR] -->|G4| M[Merge]
  C -. fail, 3 times max .-> I
```

Caption: each box after the ticket is a new session.

## Today

### 1. Write the ticket (G1)

The ticket meets the Definition of Ready when it has these fields:

```markdown
## Goal
Show the last sync time on the settings page.

## Acceptance criteria
1. The settings page shows "Last sync: <date and time>" under the sync button.
2. If no sync has happened, it shows "Last sync: never".

## Non-goals
- No change to how the sync works.

## Test oracle
Open the settings page after a sync. The time matches the sync log.

Personas: farmer
```

Write `Personas: none` if the change does not affect users. If a field is missing, start the shaper
(`claude --agent shaper`) with the issue number. It asks you for the missing fields.

Add the label `agent-ready` to ask for a readiness check. The G1 check passes when no field is
missing.

`stone render` also writes
the workflow `cornerstone-single-ticket-label.yml`. The label starts the shaper in CI. No human is
in that job, so the shaper does not interview anyone (D41). It has read-only tools. It checks the
ticket against the Definition of Ready and posts the missing fields on the issue. It does not
start another role.

Before the first run, add the repository secret
`CLAUDE_CODE_OAUTH_TOKEN` and the label. See the
[adapter](../../framework/adapters/claude-code.md#trigger-workflows).
If the repo selects more than one profile with the label `agent-ready`, add the label
`profile:<id>` before it.

### 2. Run the roles

Follow [Run the roles](run-the-roles.md). Each step is a new session.

1. Make a branch, for example `feature/last-sync-time`.
2. Start the implementer with the issue number. It changes the code and writes the decision log.
3. Start the tester with the issue number and the branch. It writes one test or more for each
   acceptance criterion.
4. Run `commands.all_checks`. If a check fails, give the output to a new implementer session.
5. Start the reviewer with the issue, the branch, the check output, and the decision log.

### 3. Open the PR (G4)

Run `/workflow:ticket-delivery`. It maps each acceptance criterion to its evidence and opens the PR.
A human approves the PR.

The PR body needs these parts:

- The line `Profile: single-ticket`. Check K7 reads it to find the size limit (600 changed lines).
- The sections Evidence, Decision log, Review findings, and Confidence. Check K14 tests them.

To test the body before you push, run K14 on it:

```bash
gh pr view <number> --json body --jq .body | stone check-evidence -
```

The G3 workflow runs K6, K7, and K14. Make the job `cornerstone-checks` a required status check.
K7 and K14 block (D45, D49).

## Change the mode

| If you want to | Do this |
| --- | --- |
| Write the code yourself | Use human-centric mode. Commit with `Role: implementer` and `Actor: human`. Then start the tester and the reviewer as above. |
| Approve each edit of the agent | Use a `pair` session for the Build stage: `STONE_ROLE=implementer claude --agent implementer`, in manual permission mode. |
| Run with no human at the terminal | Add `-p` to each role command. See [Run the roles](run-the-roles.md#start-a-role). |

The gates do not change with the mode. The tester is always a different session from the
implementer.

## Not built yet

- A run script that starts each role in order, for agent-centric mode on your computer.
- A CI workflow that runs the implementer, the tester, and the reviewer. The label workflow starts
  the first role only.
