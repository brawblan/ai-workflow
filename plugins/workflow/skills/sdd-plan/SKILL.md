---
name: sdd-plan
description: "Plan a GitHub issue as an OpenSpec change: triage, explore, propose, validate, and an optional docs PR. Planning only; no code. Needs OpenSpec in the repo. Use when asked to plan an issue, write a spec or proposal for an issue, or put an issue on the backlog as a change. Triggers: 'plan issue #123', 'propose a change for #123', 'spec this issue'."
---

# sdd-plan

Run these steps in order. The repo rules come from `openspec/config.yaml` and `CLAUDE.md` or
`AGENTS.md`. Do not repeat them here. If the repo has a workflow doc for spec-driven development,
follow it.

If `openspec/` does not exist, stop. Tell the user to run `openspec init` first.

1. **Read the issue.** Get the repo with `gh repo view --json nameWithOwner -q .nameWithOwner`.
   Run `gh issue view <n> --repo <owner>/<repo> --json title,body,labels,comments`.
2. **Triage.** If the repo docs name a backlog file, find the backlog item and the requirement
   for this issue there. If they do not exist, ask the user: assign them now, or record
   `Requirement: none (<reason>)`. Set the change ID with the repo's naming rule. If the repo has
   no rule, use `issue-<n>-<slug>`.
3. **Find input.** If the repo docs name older planning input for this item (for example a frozen
   spec folder), read it as input. Do not edit it.
4. **Explore.** Run `/opsx:explore` with the issue and that input. Ask the user each open question.
5. **Propose.** Run `/opsx:propose <change-id>`.
6. **Validate.** Run `openspec validate <change-id> --strict`. Fix all findings.
7. **Hand off.** Show the user the artifacts in one short summary. Ask which flow to use:
   - Plan ahead: open a docs PR with the `dev-pr` skill. Stop.
   - Build now: continue with the `sdd-build` skill.

Do not write code in this skill.
