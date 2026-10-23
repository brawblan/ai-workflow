---
name: ticket-delivery
description: "Collect the evidence that a ticket's acceptance criteria are met, then branch, commit, and open the PR into the integration branch (default `dev`). Use when asked to verify a ticket, check COAs, deliver a ticket, ship the current changes, branch and commit, or open a PR into dev. With no ticket, it summarizes the work."
---

# Ticket Delivery

A delivery pass on finished work. This skill collects evidence, then ships the work as a PR. It does
not make the evidence. The session that wrote the code cannot judge it (P2), so the tests and the
review come from other sessions.

## 0. Repo conventions

Read the repo rules first. Follow them over this skill where they conflict:

- `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, and any PR workflow doc they name.
- `.github/pull_request_template.md`, if it exists.
- The CI workflows in `.github/workflows/`, for the checks that apply to each path.

Find the **integration branch** (the branch that PRs target). If the docs do not name one, use `dev`
if it exists on `origin`. Otherwise use the default branch from
`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`. The steps below call it `<base>`.

## 1. Find the delivery basis

- If the config has `tickets.source: file`, the ticket is the file `tickets.path`, with the ticket ID
  for `{id}`. Read it. Do not use the issue CLI.
- Find the ticket in the conversation, the branch name, the linked issue, or the plan files.
- Extract each acceptance criterion (COA). The COAs are the source of truth.
- If there is no ticket, go to step 6. Do not invent criteria.

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

## 3. Branch, commit, and sync

- Run `git status --short`. If the tree is clean and the branch has no commits to ship, stop and ask
  what goes into the PR.
- If a file in `git status` does not relate to the work, flag it and ask before you include it.
- Run `git fetch origin <base>`. Check how far the branch is behind `origin/<base>`
  (`git rev-list --left-right --count origin/<base>...HEAD`).
- Branch: name it `feature/<slug>`, `fix/<slug>`, or `chore/<slug>`, unless the repo uses another
  convention. If the session is on an existing short-lived feature branch with uncommitted work,
  ask whether to reuse it. Run `git checkout -b <branch-name>` before you commit.
- Commit: stage specific paths. Never run `git add -A` or `git add .`. Run the formatter or lint
  command that the repo docs name. Write a message that explains why, in the repo style.
- If the repo uses role trailers (it has `.cornerstone/config.yaml`, or its docs say so), add
  `Role: <role>` and `Actor: agent|human` to each commit. A commit with no `Role:` trailer counts as
  an implementer commit. Check K6 fails if such a commit changes a test, check, or CI path. If
  `commits.trailers` is `notes` or `none`, add no trailers. If `commits.by` is `human`, do not
  commit: give the message.
- End each commit message with the attribution line that the harness gives. If it gives none, use
  `Co-Authored-By: Claude <model name> <noreply@anthropic.com>`.
- Sync: run `git rebase origin/<base>`. If a conflict is not obvious, stop and ask. Do not guess.

## 4. Run the checks

Run the checks after the rebase. Do not use a result from before it.

- Run the repo's check command from `AGENTS.md` or `.cornerstone/config.yaml` (`commands.all_checks`).
  Also run each check that CI requires for the touched paths.
- Checks are programs, so this session can run them. Record each command and its result.
- If a check cannot run locally, say so in the PR. Do not skip it silently.
- If a check fails, stop. Report the output. The implementer fixes it, not this skill.
- If the plan has a spec delta (`<plans>/<id>.spec.md`, where `<plans>` is `paths.plans` in
  `.cornerstone/config.yaml`, default `docs/plans/`) with no `apply_order`, run
  `stone spec apply <id>`. Commit its output alone, with the trailers `Role: generator` and
  `Actor: agent`. Then run the checks again.

### Specialist reviews

If `.cornerstone/specialists.md` exists, run `stone specialists --base <integration branch> --ticket
<id> --labels <ticket labels> --personas <ticket persona IDs>`.

- Add a "Specialist findings" section to the PR evidence with its table.
- For a specialist with the status `missing`, stop. Tell the user to start its `run` command in a new
  session. Do not run the review in this session.
- For a status `blocking`, tell the user that G4 cannot pass until a human decides.
- Commit each findings report in the PR. Add the lines `Ticket: <id>` and `Personas: <IDs>` to the
  PR body. Check K20 in CI reads them, and fails on a blocking finding.

## 5. Map the evidence to each COA

Mark each COA with one status:

| Status | When |
| --- | --- |
| `met` | A tester test covers the COA, the test passes, and the reviewer has no open finding on it. |
| `not met` | A test for the COA fails, or the reviewer has an open finding on it. |
| `no evidence` | No tester test covers the COA, or the reviewer did not check it. |

Give the evidence for each status: the test name, the command and its result, or the finding. Do
not mark a COA `met` from your own reading of the code.

## 6. Fallback when no ticket exists

Summarize the work from the diff: what changed, which checks ran and their results, and what is not
verified. Say that no COAs exist, so the PR has no COA evidence.

## 7. Push and open the PR

- Run `git push -u origin <branch-name>`.
- Open the PR into `<base>`. Never open it into a release or production branch (for example
  `staging` or `main`), unless the repo docs say that `<base>` is that branch.
- **Profile line:** if the repo has `.cornerstone/config.yaml`, put `Profile: <id>` at the top of
  the PR body. Check K7 uses it to pick the size limit. If `profiles` has one id, use it. If it
  has more, use the profile in the ticket or the plan. If neither names one, ask the user. Do not
  guess. If the config has `adoption: opt-in`, this line (or the label `cornerstone`) turns the
  Cornerstone checks on for the PR.
- **Size:** if the repo has the K7 script (for example `.cornerstone/checks/change_size.py`), run
  `python <script> origin/<base> --body <file with the PR body>` before you open the PR. If the diff
  is over the limit, tell the user. The user splits the PR, or approves a `Waiver (P10)` section
  with the reason, the owner, and the end date. Write the waiver only after the user approves it.
- **Sections:** if the repo has a PR template, use all of its sections. Otherwise use these, in this
  order: **Summary**, **Why this change**, **Validation run**, **Risks**, **Rollback plan**, and the
  four evidence sections below. Add **Environment/config changes** or **Follow-up issues** after
  **Confidence** only if they apply. Keep the PR to one concern. Put deferred work in an issue.
- **Evidence sections** (check K14): add them also when the repo template does not have them. Put
  them after **Rollback plan**, in this order. Use the exact heading names, for example
  `## Confidence`:

  | Section | Content |
  | --- | --- |
  | **Evidence** | The COA table from step 5, or the summary from step 6. With no ticket: each check command and its result. |
  | **Decision log** | A link to the decision log, or a list: decision, options, choice, reason. |
  | **Review findings** | The findings of the reviewer session, with severity. Write who reviewed, or that no review ran. If the reviewer made a report, link it. |
  | **Confidence** | The reviewer's confidence (high, medium, or low) with the reason and the open risks. Add each `not met` or `no evidence` COA as a risk. |

  K14 fails on an empty section. If a section does not apply, write `None` and the reason.
- If the repo has a writing style guide (for example `docs/style/ste.md`), write the PR body with it.
- Add `Closes #<n>` only if all COAs are `met`, and only in the PR that completes the issue.
  Otherwise use `Related #<n>`.
- End the PR body with the attribution line that the harness gives. If it gives none, use the same
  `Co-Authored-By` line as the commit.

## 8. Wrap up

- Run `gh pr checks <number>` and report the result.
- Fast-forward local `<base>` to `origin/<base>`
  (`git checkout <base> && git pull --ff-only origin <base>`). Do this only if it is a clean
  fast-forward. If local `<base>` has diverged, stop and flag it.

## Response shape

1. COA status table, or the work summary
2. Check results
3. Missing evidence, and who must make it
4. PR status and link, and anything that needs the user's attention

## Guardrails

- Never mark a COA `met` without a test from the tester and a passing result.
- Never write tests or a review for code that this session wrote.
- Never force-push. Never rewrite the history of a pushed or shared branch.
- Never bypass a branch protection. Never skip a status check that applies to the touched area.
- Never discard unrelated local changes to make a clean branch.
- If a branch or PR step is blocked (auth, remotes, conflicts, unrelated work), say what is blocked.
  Choose the safest non-destructive path.
