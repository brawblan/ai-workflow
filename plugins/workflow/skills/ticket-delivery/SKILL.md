---
name: ticket-delivery
description: "Collect the evidence that a ticket's acceptance criteria (COAs) are met: the tester's tests, the check output, and the reviewer's findings, each from its own session. Then open the PR with the dev-pr skill, with the evidence sections filled. It does not verify its own work. If no ticket exists, summarize the work instead. Use when asked to verify a ticket, check COAs, confirm acceptance criteria, collect evidence, summarize completed work, or deliver a ticket as a PR."
---

# Ticket Delivery

A delivery pass on finished work. This skill collects evidence. It does not make it. The session
that wrote the code cannot judge it (P2), so the tests and the review come from other sessions.

## 1. Find the delivery basis

- Find the ticket in the conversation, the branch name, the linked issue, or the plan files.
- Extract each acceptance criterion (COA). The COAs are the source of truth.
- If there is no ticket, go to step 5. Do not invent criteria.

## 2. Check that the independent work exists

Each item must come from a session other than the one that wrote the code:

| Evidence | Made by | Where to find it |
| --- | --- | --- |
| Tests for each COA, and a test report | tester | Test commits (trailer `Role: tester`), a PR comment, or a report file |
| Review findings, confidence, and open risks | reviewer | A PR review, a PR comment, or a report file |
| Decision log | implementer | `docs/plans/<id>.decisions.md`, or the path in the repo config |

If the tester or the reviewer has not run, stop. Tell the user to start that role in a new session
with the ticket and the diff. Use the repo's role file if it has one (for example
`.claude/agents/tester.md`). Do not write the tests or the review in this session.

## 3. Run the checks

- Run the repo's check command from `AGENTS.md` or `.cornerstone/config.yaml` (`commands.all_checks`).
- Checks are programs, so this session can run them. Record each command and its result.
- If a check fails, stop. Report the output. The implementer fixes it, not this skill.
- If the plan has a spec delta (`<plans>/<id>.spec.md`, where `<plans>` is `paths.plans` in
  `.cornerstone/config.yaml`, default `docs/plans/`) with no `apply_order`, run
  `stone spec apply <id>`. Commit its output alone, with the trailers `Role: generator` and
  `Actor: agent`. Then run the checks again.

## 4. Map the evidence to each COA

Mark each COA with one status:

| Status | When |
| --- | --- |
| `met` | A tester test covers the COA, the test passes, and the reviewer has no open finding on it. |
| `not met` | A test for the COA fails, or the reviewer has an open finding on it. |
| `no evidence` | No tester test covers the COA, or the reviewer did not check it. |

Give the evidence for each status: the test name, the command and its result, or the finding. Do
not mark a COA `met` from your own reading of the code.

## 5. Fallback when no ticket exists

Summarize the work from the diff: what changed, which checks ran and their results, and what is not
verified. Say that no COAs exist, so the PR has no COA evidence.

## 6. Open the PR

Follow the `dev-pr` skill. Fill its evidence sections from steps 2 to 5:

- **Profile line:** if the repo has `.cornerstone/config.yaml`, put `Profile: <id>` at the top of
  the PR body. Check K7 uses it to pick the size limit. If `profiles` has one id, use it. If it
  has more, use the profile in the ticket. If the ticket names none, ask the user.
- **Waiver (P10):** if the diff is over the K7 limit, tell the user. The user splits the PR, or
  approves a `Waiver (P10)` section with the reason, the owner, and the end date.
- **Evidence:** the COA table from step 4, or the summary from step 5.
- **Decision log:** the link or the list from step 2.
- **Review findings:** the reviewer's findings, or "None" with the reviewer's report link.
- **Confidence:** the reviewer's confidence and open risks. Add each `not met` or `no evidence` COA
  as a risk.

Add `Closes #<n>` only if all COAs are `met`. Otherwise use `Related #<n>`.

## Response shape

1. COA status table, or the work summary
2. Check results
3. Missing evidence, and who must make it
4. PR status and link

## Guardrails

- Never mark a COA `met` without a test from the tester and a passing result.
- Never write tests or a review for code that this session wrote.
- Never discard unrelated local changes to make a clean branch.
- If a branch or PR step is blocked (auth, remotes, conflicts, unrelated work), say what is blocked.
  Choose the safest non-destructive path.
