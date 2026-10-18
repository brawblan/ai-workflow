# Run the roles

Each role runs in its own session (P2). The session that writes the code does not write its tests
or review it. This page shows how to start each role today, after `stone render` wrote the role
files into your repo.

Checked with Claude Code 2.1.302. The `--agent` flag loads one role file from `.claude/agents/`.

## Before you start

1. Make sure that the repo has `.claude/agents/` and `.cornerstone/manifest.yaml`. If not, follow
   [Add Cornerstone to a repo](add-to-a-repo.md).
2. Make a branch for the ticket, for example `fix/<slug>`.
3. Have the ticket ready: an issue number, or the ticket text in a file.

## Start a role

Start each role in a new terminal session. Do not reuse a session from an earlier role.

| Role | Command | Give it |
| --- | --- | --- |
| shaper | `claude --agent shaper` | The ticket. Answer its questions until the ticket is ready. |
| planner | `STONE_ROLE=planner claude --agent planner` | The ready ticket. Answer its open questions. App-slice only. |
| implementer | `STONE_ROLE=implementer claude --agent implementer` | The ticket, and the plan if one exists |
| tester | `STONE_ROLE=tester claude --agent tester` | The ticket and the branch name. It reads the diff. |
| reviewer | `STONE_ROLE=reviewer claude --agent reviewer` | The ticket, the branch, the check output, and the decision log |

`STONE_ROLE` tells the protected-path hook which paths the session can change:

| Role | Can change |
| --- | --- |
| planner | The plans path only |
| implementer | All paths except tests, checks, CI, `.claude/`, and `.cornerstone/` |
| tester | The test paths only |
| reviewer | No path |

If `STONE_ROLE` is not set, the hook uses `implementer`.

To run a role with no human at the terminal, add `-p` and the prompt:

```bash
STONE_ROLE=tester claude --agent tester -p "Write the tests for issue #42 on branch fix/login-timeout."
```

## Commit with trailers

Check K6 reads two trailers on each commit. The agent roles add them. Add them to your own commits
too:

```bash
git commit -m "fix(auth): renew the token before it expires" \
  --trailer "Role: implementer" --trailer "Actor: human"
```

| Trailer | Values |
| --- | --- |
| `Role:` | `implementer`, `tester`, `generator`, or another role from the workflow model |
| `Actor:` | `human` or `agent` |

A commit with no `Role:` trailer counts as an implementer commit. K6 fails if an implementer commit
changes a test or a check.

## Run the checks

Run `commands.all_checks` from `.cornerstone/config.yaml` before you open the PR. CI runs the same
checks again (G3). The CI result is the evidence, not a statement from an agent (P1).

## Open the PR

Run `/workflow:ticket-delivery` in a new session. It collects the tester, reviewer, and check
evidence for each acceptance criterion. Then it opens the PR with `/workflow:dev-pr`. It does not
write tests or a review itself. If one is missing, it tells you which role to start.

A human approves the PR (G4). A solo developer can approve their own human-centric work only under
the [solo developer rule](../../framework/modes.md#solo-developer).

## If a role stops

| Stop reason | Action |
| --- | --- |
| The hook blocked an edit to a protected path | The role must not change that path. If the change is necessary, start the role that owns the path. |
| The checks failed 3 times | Stop the loop. You decide the next step. Record it in the decision log. |
| The tester and the implementer disagree on expected behavior | You decide from the ticket. Add the answer to the ticket, so the next run has it. |
