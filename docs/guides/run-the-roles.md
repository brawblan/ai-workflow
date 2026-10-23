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
| planner | `claude --agent planner` | The ready ticket. Answer its open questions. App-slice only. |
| implementer | `claude --agent implementer` | The ticket, and the plan if one exists |
| tester | `claude --agent tester` | The ticket and the branch name. It reads the diff. |
| reviewer | `claude --agent reviewer` | The ticket, the branch, the check output, and the decision log |
| investigator | `claude --agent investigator` | The ticket or the bug report, and the question to answer. It writes a report. |

The protected-path hook finds the role of the session in this order:

1. The role file that the harness loaded. With `--agent`, or in a subagent, the hook input names it.
2. The environment variable `STONE_ROLE`, for example `STONE_ROLE=tester claude`.
3. `implementer`, if neither names a role.

If the hook blocks a tester or a planner edit with an implementer message, your harness version
does not send the role. Then start the role with `STONE_ROLE=<role> claude --agent <role>`.

The role sets which paths the session can change:

| Role | Can change |
| --- | --- |
| planner | The plans path only. Not the specs path. |
| implementer | All paths except tests, checks, CI, `.claude/`, and `.cornerstone/` |
| tester | The test paths only |
| reviewer | No path |
| investigator | The reports path only (`paths.reports`, default `docs/reports/`). On a `spike/` branch, all paths except `.claude/` and `.cornerstone/`. |

A session with no role is an implementer for the hook. It cannot change `.claude/` or
`.cornerstone/`. Change those files with `stone render`.

The investigator is the only role with a branch rule. Code on a `spike/` branch never merges (K16).
See [K16 and the spike branch](../../framework/checks.md#k16-and-the-spike-branch).

To run a role with no human at the terminal, add `-p` and the prompt:

```bash
claude --agent tester -p "Write the tests for issue #42 on branch fix/login-timeout."
```

## Keep the cost low

- Do one ticket in a session. When the role finishes, end the session. Run `/clear` or start a new one.
- Run the tester and then the reviewer for one ticket. Do not run the roles of many tickets at once.
- Run 2 or 3 sessions at the same time at most. Each session pays the full cost of the always-on context.
- Use a stronger model only for the roles that reason: the shaper, the planner, and the reviewer. The
  model profile sets the model of each role (`defaults.role_models`).
- Show only failures and a summary when a role runs the checks. For example, run
  `python stone/tests/run_parallel.py -q`.

## Start a role as a subagent

Use this path if you cannot start a session with `--agent`, for example in the desktop app.

1. Start a session with no role.
2. Ask it to start the role as a subagent. For example: "Use the tester subagent. Write the tests for
   issue #42 on branch fix/login-timeout."
3. Start a new session for the next role.

The subagent has a fresh context, and the hook uses the role of the subagent. This path is weaker
for P2, because the lead session starts the subagent and gives it its prompt. These are the limits:

- Start a role subagent only from a session with no role. If an implementer session starts a tester
  subagent, the hook lets the subagent change the tests. No check finds this. The reviewer and G4
  are the control.
- The lead can change the prompt of the subagent. Give the lead the same ticket text that you give
  a role session.
- The subagent commits with its own `Role:` trailer. If the lead commits the files of the subagent,
  use the trailer of the subagent role.

## Commit with trailers

The repo config can change this. With `commits.by: human`, the implementer and the tester do not
commit. They end with a proposed message, and you commit it. With `commits.trailers: notes`, the
role goes in a git note, not in the message. With `commits.trailers: none`, nothing records the
role, and there is no K6. See [Commits](../../framework/customization.md#commits-commits).

Check K6 reads two trailers on each commit. The agent roles add them. Add them to your own commits
too:

```bash
git commit -m "fix(auth): renew the token before it expires" \
  --trailer "Role: implementer" --trailer "Actor: human"
```

| Trailer | Values |
| --- | --- |
| `Role:` | `implementer`, `tester`, `investigator`, `generator` (output of `stone render`, `stone spec apply`, or `stone spec sync`), or another role from the workflow model |
| `Actor:` | `human` or `agent` |

A commit with no `Role:` trailer counts as an implementer commit. K6 fails if an implementer commit
changes a test or a check.

## A ticket from another tracker

The roles need the ticket text, not a GitHub issue. Save the ticket in a file, for example
`.claude/prompts/PROJ-123.txt`. Set `tickets.source: file` and `tickets.path:
docs/tickets/{id}.txt` in `.cornerstone/config.yaml`, and render again. The shaper then writes the
Definition of Ready fields into the file, in the section `## Definition of Ready`. The other roles
read the ticket from the same path. See [Tickets as files](../../framework/customization.md#tickets-as-files-tickets).

## Run the checks

Run `commands.all_checks` from `.cornerstone/config.yaml` before you open the PR. CI runs the same
checks again (G3). The CI result is the evidence, not a statement from an agent (P1). With `delivery: local`, there
is no CI job. Run `stone gate` and put its output in the PR.

## Open the PR

Run `/cornerstone:ticket-delivery` in a new session. It collects the tester, reviewer, and check
evidence for each acceptance criterion. Then it opens the PR. It does not
write tests or a review itself. If one is missing, it tells you which role to start.

Put a `Profile: <id>` line in the PR body, for example `Profile: single-ticket`. Check K7 reads it
to find the size limit.

A human approves the PR (G4). A solo developer can approve their own human-centric work only under
the [solo developer rule](../../framework/modes.md#solo-developer).

## If a role stops

| Stop reason | Action |
| --- | --- |
| The hook blocked an edit to a protected path | The role must not change that path. If the change is necessary, start the role that owns the path. |
| The checks failed 3 times | Stop the loop. You decide the next step. Record it in the decision log. |
| The tester and the implementer disagree on expected behavior | You decide from the ticket. Add the answer to the ticket, so the next run has it. |
