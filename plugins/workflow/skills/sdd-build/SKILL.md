---
name: sdd-build
description: "Build an OpenSpec change for a GitHub issue: apply, verify, archive, and open a PR. Needs OpenSpec in the repo. Use when asked to implement or build an issue or a change, or when a planned change is ready to build. Triggers: 'implement issue #123', 'build issue #123', 'build change e1-2-foo'."
---

# sdd-build

Run these steps in order. The repo rules come from `openspec/config.yaml` (apply and archive
guidance) and `CLAUDE.md` or `AGENTS.md`. Do not repeat them here. If the repo has a workflow doc
for spec-driven development, follow it.

1. **Find the change.** Run `openspec list --json`. Match the change ID to the issue.
   If no change exists, run the `sdd-plan` skill through step 6 first.
2. **Get approval.** Show the user the scope, the task groups, and the verify plan. Wait for a yes.
3. **Apply.** Run `/opsx:apply <change-id>`.
4. **Verify.** Run `/opsx:verify <change-id>`. Fix each finding.
5. **Archive.** Run `/opsx:archive <change-id>`. If owner-only tasks are still open, run
   `/opsx:sync` instead, and archive in a later PR.
6. **Open the PR.** Use the `dev-pr` skill.

If the scope changes during the build, stop. Update the change with `/opsx:update` first.
