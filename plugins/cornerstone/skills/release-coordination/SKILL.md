---
name: release-coordination
description: "Run a coordinator session that drives a release across many child sessions at low token cost. Use when asked to coordinate a release, run a wave of tickets, open child sessions, or merge the PRs of several sessions."
---

# release-coordination

A coordinator session opens child sessions, answers them, and merges their PRs. It makes no change
of its own. Its cost grows with each call, because each call reads the full context again. After an
idle gap longer than the cache length, the next call writes the full context again. So keep the
context small, and keep the state outside it.

## Rules

1. **Keep the state in a file.** Put the release state in the tracking issue or in a state file.
   Include the wave, the status of each ticket, the PR links, and the owner decisions. Update it
   after each merge and after each owner decision. Read it first when you start.
2. **Give each child a short prompt.** Link to the issue. Do not copy the issue text into the
   prompt. Add only what the issue does not hold: the branch rule, the files to leave alone, and
   the report form.
3. **Ask for a short report.** Each child sends a report of 10 lines or fewer. The report has the
   PR link, the check result, and the open questions.
4. **Pick the model of the work.** Use the role model of the model profile for build work with a
   clear plan. Use the stronger model for design and eval work.
5. **End or compact at the end of a wave.** Update the state. Then end the session, or compact it.
   Start the next wave in a new coordinator session that reads the state first.
6. **Reset before an idle gap.** If you expect an idle gap longer than the cache length, compact or
   end the session first. Find the cache length and the compact command in the adapter doc of your
   harness.

## Procedure

1. Read the state. If no state file exists, write one from the tracking issue.
2. Pick the tickets of the next wave. A ticket is ready if its status is `todo` and the tickets in
   its `After` column are `done`.
3. Open one child session for each ticket (rule 2 and rule 4).
4. Wait for the reports. Do not poll. Do not read a child transcript, unless a report is unclear.
5. For each report, check the PR checks. Merge the PR if the checks pass and the repo rules allow it.
   Update the state.
6. If a child asks a question, answer from the issue and the state. If you cannot, ask the owner
   one question with 2 to 4 options. Record the answer in the state.
7. When the wave is done, do rule 5.

## Limits

- Do not write code, tests, or review findings in this session. A child does that (P2).
- Do not paste a child report or a diff into the state. Keep a PR link and a status.
- Repo facts stay in the repo `AGENTS.md`. This skill names no repo, branch, or issue number.
