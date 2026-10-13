---
name: backlog-sequencer
description: "Review open GitHub issues for the current repo: sync the status:blocked label from each issue's own \"Depends on #N\"/\"blocked by #N\"/\"Dependencies: #N\" text, optionally mirror that onto a Blocked field on a GitHub Project board, and suggest a priority label for any issue that has none — using this session's own judgment, not an external API call. Use when asked to sequence the backlog, sync blocked status, update the project board, or suggest issue priorities."
---

# Backlog Sequencer

Keeps the backlog's blocked state and priorities current, interactively. This skill *is* the
judgment layer: you review priority yourself and act with the user's own Claude usage, not a
separate billed API key.

## Configuration

Read the config before step 1:

- If `.github/backlog-sequencer-rules.json` exists, use its values (`projectOwner`,
  `projectNumber`, `blockedLabel`, `priorityLabels`, `prioritySuggestionMarker`) rather than
  hardcoding them.
- If it does not exist, use these defaults: `blockedLabel` = `status:blocked`,
  `priorityLabels` = `priority:P0`, `priority:P1`, `priority:P2`. Ask the user for the Project
  owner and number only if they want step 3. Offer to save the answers in that file.
- If the repo also has a scheduled workflow that does the same sync (for example
  `.github/workflows/backlog-sequencer.yml`), read its script and match its rules exactly.
  Consistency with the scheduled run matters more than catching more cases.

## Workflow

### 1. Gather open issues

```
gh issue list --repo <owner>/<repo> --state open --limit 200 \
  --json number,title,body,labels,url
```

Use the current repo's `owner/repo` (from `gh repo view --json nameWithOwner -q .nameWithOwner`
or `git remote`; ask if ambiguous). Always pass `--repo` explicitly.

### 2. Sync the blocked label (deterministic — do this exactly, no judgment)

For each issue, scan its own `body` **one line at a time** for the keywords
`depends on`, `blocked by`, `dependencies:` (case-insensitive). On a matching
line, collect every `#N` reference **after** the keyword on that same line —
never pull references from other bullets (e.g. a separate "Powers #10" line
is not a blocker).

An issue is **blocked** if at least one referenced issue is still open.

- If blocked and missing the label: `gh issue edit <n> --repo <owner>/<repo> --add-label "<blockedLabel>"` (create the label first with `gh label create` if it doesn't exist yet — ignore the "already exists" error).
- If not blocked and has the label: `gh issue edit <n> --repo <owner>/<repo> --remove-label "<blockedLabel>"`.

### 3. Sync the Project board (optional — needs `PROJECT_TOKEN`)

Skip this step if no Project owner and number are configured.

Check whether `PROJECT_TOKEN` is set in the environment (`echo "${PROJECT_TOKEN:+set}"`).
If it's **not** set, skip this step and tell the user in your summary that Project sync was
skipped. Tell them to create a fine-grained token with Projects read/write access and export it
as `PROJECT_TOKEN`. Do not suggest `gh auth login`/`gh auth refresh` as an alternative; that
would broaden the shared `gh` CLI credential across every org the user belongs to.

If it **is** set, call the GitHub GraphQL API with that token explicitly
scoped to the call — never touch the stored `gh auth` login:

```
GH_TOKEN="$PROJECT_TOKEN" gh api graphql -f query='...'
```

Find (or create) a single-select `Blocked` field (options `Yes`/`No`) on
`user(login: <projectOwner>) { projectV2(number: <projectNumber>) }` (use `organization(login:)`
if the owner is an org), add each issue as a project item (`addProjectV2ItemById` — idempotent,
safe to call even if already added; needs the issue's GraphQL node id, from
`gh issue view <n> --repo <owner>/<repo> --json id -q .id`), and set the field to match the
blocked state computed in step 2. Never modify item position — the team's manual drag order in
the board stays theirs.

### 4. Suggest priorities (this is the judgment step — actually think about each one)

For every open issue with **no** label from `priorityLabels`, read its title
and body yourself and decide: `priority:P0` (critical, launch-blocking),
`priority:P1` (high-priority, near-term), or `priority:P2` (important, not
blocking). Base it on the issue's own content — urgency language, what it
blocks, whether it's scoped as a stretch goal, its milestone — the same way
you'd triage it if the user asked you directly.

Present your suggestions to the user as a short list (issue, suggested
label, one-sentence reason) **before applying anything**. Once the user
confirms (all, some, or none), apply the approved ones with
`gh issue edit <n> --repo <owner>/<repo> --add-label "priority:PX"`. Do not
comment-and-leave the way an unattended workflow would — you have the user
right here, so get a real decision instead of a suggestion nobody reads.

If the user says "just apply your best guess" (or similar) for a bulk run,
you may skip the per-issue confirmation and apply directly — but still list
what you did afterward so it's auditable.

### 5. Summarize

End with a compact table: issue, action taken (`blocked`, `unblocked`,
`project-synced`, `priority-applied`), and detail. If the repo has a scheduled
workflow that writes a summary, use the same shape.

## Guardrails

- Never widen `gh` CLI auth scope (`gh auth login`/`refresh -s ...`) to make
  Project sync work. If `PROJECT_TOKEN` is missing, skip Project sync and say
  so; don't work around it.
- Before any write to an issue number, confirm the number belongs to this repo
  (`gh issue view <n> --repo <owner>/<repo> --json title`). `--search` results can
  include issues from other repos.
- Don't invent blocking relationships beyond the deterministic `#N` scan in
  step 2 — an index issue's "X blocked by Y" prose about *other* issues is
  out of scope.
- Never apply a priority label without either explicit per-issue confirmation
  or an explicit "apply your best guess to all of them" from the user in
  this conversation.
