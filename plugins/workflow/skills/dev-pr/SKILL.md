---
name: dev-pr
description: Create a branch from the current work, commit it, and open a PR into the repo's integration branch (default `dev`), following the repo's branch model and PR conventions. Use when the user asks to branch/commit/open a PR for the current changes, or says "ship this", "open a PR into dev", or invokes /dev-pr directly.
---

# dev-pr

Ships the current uncommitted work as a PR into the repo's integration branch.

## Repo conventions

Read the repo's own rules first, and follow them over anything below where they conflict:

- `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, and any PR workflow doc they name (for example
  `docs/agent-pr-workflow.md`).
- `.github/pull_request_template.md`, if it exists.
- The CI workflows in `.github/workflows/`, for the checks that apply to each path.

From these, find the **integration branch** (the branch that PRs target). If the docs do not
name one, use `dev` if it exists on `origin`. Otherwise use the default branch from
`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`. The steps below call it
`<base>`.

## 0. Sanity checks

- `git status --short` — confirm there's actually something to ship (staged, unstaged, or
  untracked files). If the tree is clean, stop and ask the user what should go into the PR.
- If unfamiliar/unexpected files show up in `git status` that don't look related to the work
  just discussed in the conversation, flag them and ask before including them — don't silently
  sweep up unrelated changes.
- `git branch --show-current` and `git fetch origin <base>` — check how far the current branch
  is behind `origin/<base>` (`git rev-list --left-right --count origin/<base>...HEAD`).

## 1. Branch

- Name it `feature/<slug>`, `fix/<slug>`, or `chore/<slug>` unless the repo uses another
  convention — pick the prefix based on the nature of the change, and a short kebab-case slug
  describing it.
- If already sitting on an existing short-lived feature branch (not `<base>` or a release
  branch such as `staging`/`main`) with uncommitted work, ask whether to reuse it or cut a new
  one rather than assuming.
- `git checkout -b <branch-name>` from the current HEAD. Do this *before* committing — creating
  the branch first carries any uncommitted working-tree changes with it automatically, so there's
  no need to stash/pop.

## 2. Commit

- Stage only the files relevant to this change — check `git status` and add specific paths,
  never a blind `git add -A`/`git add .`. Don't sweep in unrelated in-progress edits.
- If the repo has a formatter or lint command that its docs say to run before a commit, run it.
- Write a commit message that explains *why*, not just *what* (match the repo's usual style —
  check `git log` for tone/format if unsure).
- If the repo uses role trailers (it has `.cornerstone/config.yaml`, or its docs say so), add
  `Role: <role>` and `Actor: agent|human` to each commit. A commit with no `Role:` trailer counts
  as an implementer commit, and check K6 fails if it changes a test, check, or CI path.
  If `commits.trailers` in the config is `notes` or `none`, do not add trailers to the message.
  If `commits.by` is `human`, do not commit: give the message.
- End the message with a `Co-Authored-By: Claude <model name> <noreply@anthropic.com>` line.
  Use the name of the model that does the work, for example `Claude Opus 5.5`. If the harness
  gives an exact attribution line, use that line.

## 3. Sync with the base branch

- `git rebase origin/<base>`. Resolve any conflicts faithfully — if a conflict's resolution
  isn't obvious from context, stop and ask rather than guessing.
- After rebasing (or resolving conflicts), re-run validation (step 4) again before pushing —
  don't rely on a pre-rebase test run.

## 4. Validate locally

Run whatever's relevant to what actually changed, mirroring the repo's CI required checks:

- Find the checks for each touched path in the repo docs and in `.github/workflows/`.
- If the repo has a root pre-push or check script (for example `npm run pre-push`) and the change
  is cross-cutting, run it.

If a relevant check can't be run locally, say so explicitly in the PR rather than skipping it
silently.

## 5. Push and open the PR

- `git push -u origin <branch-name>`
- Open the PR **into `<base>`** — never directly into a release or production branch (for example
  `staging` or `main`) unless the repo docs say that `<base>` is that branch.
- If the repo has `.cornerstone/config.yaml`, put a `Profile: <id>` line at the top of the PR
  body. Check K7 reads this line to find the size limit. Without it, K7 uses the smallest limit
  of the selected profiles. Find the id as follows:
  - If `profiles` in the config has one id, use it.
  - If it has more than one, use the profile that the ticket or the plan names.
  - If neither names one, ask the user. Do not guess.
- If the repo has the K7 script (for example `.cornerstone/checks/change_size.py`), run it before
  you open the PR: `python <script> origin/<base> --body <file with the PR body>`.
- If the diff is over the limit, tell the user. Split the PR, or add a `Waiver (P10)` section
  with the reason, the owner, and the end date. Write the waiver only if the user approves it.
- If the repo has a PR template, use all of its sections. Otherwise use these sections, in this
  order: **Summary**, **Why this change**, **Validation run**, **Risks**, **Rollback plan**,
  then the four evidence sections below. Add **Environment/config changes** or **Follow-up
  issues** after **Confidence** only if they apply. Keep scope focused to one concern; call out
  any deliberately-deferred follow-up work as an issue rather than folding it into this PR.
- Add the evidence sections (check K14), also when the repo template does not have them. Put
  them after **Rollback plan**, in this order. Use the exact heading names, for example
  `## Confidence`:

  | Section | Content |
  | --- | --- |
  | **Evidence** | Each acceptance criterion, its status, and the test or command output that proves it. With no ticket: each check command and its result. |
  | **Decision log** | A link to the decision log, or a list: decision, options, choice, reason. |
  | **Review findings** | The findings of the reviewer session, with severity. Write who reviewed, or that no review ran. |
  | **Confidence** | High, medium, or low, with the reason and the open risks. |

  K14 fails on an empty section. If a section does not apply, write `None` and the reason.
  Do not fill **Evidence** or **Review findings** from your own reading of code that you wrote.
  Use the `ticket-delivery` skill to collect them.
- If the repo has a writing style guide (for example `docs/style/ste.md`), write the PR body with
  it. Use `Closes #<n>` only in the PR that completes the issue; otherwise use `Related #<n>`.
- End the PR body with the same `Co-Authored-By: Claude <model name> <noreply@anthropic.com>`
  line as the commit. If the harness gives other attribution lines for PR bodies, add them after it.

## 6. Wrap up

- Check CI status on the new PR (`gh pr checks <number>`) and report the result.
- Fast-forward local `<base>` to `origin/<base>`
  (`git checkout <base> && git pull --ff-only origin <base>`). Only do this if it's a clean
  fast-forward — if local `<base>` has diverged, stop and flag it instead of forcing anything.
- Report back: branch name, PR URL, CI status, and anything that needs the user's attention
  (e.g. unrun checks, flagged risks).

## Guardrails

- Never force-push, never rewrite already-pushed/shared branch history.
- Never open a PR directly against a release or production branch unless the repo docs make it
  the integration branch.
- Never bypass branch protections or skip a status check that applies to the touched area.
- If there's nothing clearly in-scope to ship, ask rather than guessing at what belongs in
  the PR.
