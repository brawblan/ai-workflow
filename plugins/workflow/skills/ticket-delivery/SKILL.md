---
name: ticket-delivery
description: "Check whether a ticket's COAs or acceptance criteria are met, or if no ticket context exists, summarize the work completed. After the work is verified, create a branch from the repo's integration branch (default dev), organize commits into logical groups, and open a PR into it. Use when asked to verify a ticket, check COAs, confirm acceptance criteria, summarize completed work, create a branch, organize commits, or open a PR."
---

# Ticket Delivery

Use this skill when the user wants a delivery pass on current work before it is handed off in git.

## Goals

- Decide whether the current work satisfies the ticket's COAs or acceptance criteria.
- If there is no ticket context, provide a short work summary from the current diff and recent validation.
- Only after verification, prepare the git history and open a PR.

## Workflow

### 1. Identify the delivery basis

- If the conversation, branch, files, or linked docs contain ticket details, extract the COAs or acceptance criteria first.
- Treat COAs and acceptance criteria as the source of truth for verification.
- If no ticket context is available, switch to a concise work-done summary instead of inventing criteria.

### 2. Verify the work

- Compare each COA against the actual code, tests, and command results.
- Mark each item as `met`, `not met`, or `unknown`.
- For `not met` or `unknown`, explain the missing behavior, missing test coverage, or missing evidence.
- Prefer executable verification over inspection alone: run the narrowest relevant tests, checks, or build commands first.
- Do not create branches, commits, or PRs until the current state has been verified or the user explicitly accepts the risk.

### 3. Fallback when no ticket exists

- Summarize the work in a short list based on the current diff, touched files, and recent validation.
- Keep that summary factual: what changed, what was validated, and what remains unverified.

### 4. Prepare delivery after verification

- Default the base branch to the repo's integration branch unless the user names another target.
  Find it in `CLAUDE.md`, `AGENTS.md`, or `CONTRIBUTING.md`. If the docs do not name one, use `dev` if it
  exists on `origin`. Otherwise use the repo's default branch.
- Create a new branch from the base branch when the worktree allows it.
- If the worktree is already dirty on another branch, avoid destructive cleanup. Preserve local changes, then choose the safest path: create a new branch from the current state, or commit and rebase/cherry-pick onto the base branch.
- Organize commits by logical unit, not by file count. Typical groups are behavior change, test coverage, and tooling/docs.
- Keep commit messages short and specific.

### 5. Open the pull request

- Push the branch and open a PR into the chosen target branch, defaulting to the base branch.
- The PR description should include:
  - `Closes #<issue number>` (when resolving a ticket/issue)
  - A short summary of the change
  - COA status or the fallback work summary
  - Validation that was run
  - Any remaining risks, gaps, or follow-up work

## Response shape

When using this skill, structure the result in this order:

1. COA status or fallback work summary
2. Verification results
3. Branch and commit plan
4. PR status and link

## Guardrails

- Never claim a COA is met without code or command evidence.
- Never discard unrelated local changes just to create a clean branch.
- If branch creation or PR creation is blocked by auth, remotes, conflicts, or uncommitted unrelated work, say exactly what is blocked and choose the safest non-destructive alternative.
