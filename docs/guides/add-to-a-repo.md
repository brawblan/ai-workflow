# Add Cornerstone to a repo

Use this guide when a repo has code but no agent framework. A repo with only an `AGENTS.md`,
`CLAUDE.md`, or other rule files also starts here. For Spec Kit, OpenSpec, or BMAD, read
[Migrate to Cornerstone](migrate.md) first.

| | |
| --- | --- |
| Profile | [single-ticket](../../framework/profiles/single-ticket.md), the default for a new config |
| Status | Works today |
| Time | About 30 minutes. Most of it is the interview. |

## What you get

| Before | After |
| --- | --- |
| Agent rules, if any, in one long file | A short `AGENTS.md`, and `constitution/` for the mission, personas, principles, stack, and roadmap |
| An agent that writes code and its own tests | The implementer, tester, and reviewer roles, each in its own session |
| "Done" when the agent says so | "Done" when CI passes (G3) and a human approves (G4) |
| No limit on what an agent can change | A hook and check K6 that stop the implementer from changing tests and checks |

## Before you start

1. Clone this repo and install the CLI:

   ```bash
   git clone https://github.com/brawblan/ai-workflow.git ~/Repos/ai-workflow
   pip install ~/Repos/ai-workflow/stone
   ```

2. Install the `cornerstone` plugin. See the [install steps](../../README.md#install-the-plugin-for-claude-code).
3. Make sure that the repo has a test command, and that CI runs it.

## Steps

1. Make a branch:

   ```bash
   git switch -c chore/cornerstone-setup
   ```

2. Start Claude Code in the repo, and run `/cornerstone:setup`.
3. Answer the questions. The skill reads the repo first, so it asks only for missing facts.

The skill does these steps in order:

| Step | What happens | You do |
| --- | --- | --- |
| Shape | `project-setup` shows a file map: which docs it moves, fills, or asks about | Approve the map |
| Interview | It asks for the facts that the repo does not have, 4 at a time or fewer | Answer, or say "I do not know". It writes a `TODO(<owner>)`. |
| Config | It writes `.cornerstone/config.yaml` and shows the diff | Read the commands and the protected paths |
| Render | It runs `stone render --dry-run`, then `stone render` | Read the list of files |
| Check | It runs `stone check` | Nothing, if it passes |

Check these config fields with care. They decide what the agent can change.

| Field | Why it matters |
| --- | --- |
| `commands.all_checks` | The roles run it. CI runs it for G3. |
| `paths.tests` | The implementer cannot change these paths. The tester can change only these paths. |
| `paths.checks` | The implementer and the tester cannot change these paths. Put your CI and lint config here. |
| `owners.solo` | Set `true` only if you are the only human. It allows the [solo developer rule](../../framework/modes.md#solo-developer). |

## Local-only adoption

Use this when you want the roles in a shared repo before the team agrees to the workflow. Other
contributors must see no change.

1. Set `delivery: local` in `.cornerstone/config.yaml`. The setup skill asks "Will the team adopt
   this now, or only you?" and sets it.
2. Keep `paths.plans` and `paths.reports` in folders such as `docs/plans/` and `docs/reports/`.
   Do not put them in `.cornerstone/` or `.claude/`: the hook blocks the roles there, and
   `stone check` fails.
3. Run `stone render`. It writes no workflow file. It prints the lines to add to
   `.git/info/exclude`. Add them. A file that git already tracks stays tracked.
4. Before you open the PR, run `stone gate --base origin/main`. Put its output in the Evidence
   section.

Limits:

- P1 is weaker. The evidence comes from your machine. No required status check stops a merge.
- K6 counts a commit with no `Role:` trailer as an implementer commit. Read the K6 result by hand
  if you keep trailers out of commits on a shared branch.
- To move to the team workflow, remove `delivery: local`, render again, and commit the result.

## Adopt in steps

A team can move from one developer to all contributors in three steps.

| Step | Config | What changes |
| --- | --- | --- |
| 1. Local only | `delivery: local` | One developer. No workflow file. See the section above. |
| 2. Opt-in | `adoption: opt-in` | The G3 workflow runs only for a PR with a `Profile: <id>` line or the label `cornerstone`. Other PRs pass as before. |
| 3. All | `adoption: all` (default) | Each PR is a Cornerstone PR. |

To go from step 1 to step 2, remove `delivery: local`, add `adoption: opt-in`, render, and commit
the result. In step 2, a marked PR gets all checks. An unmarked PR gets none of them, so review is
the only control for it. Turn on branch protection with a required human review for the base
branch. If the repo cannot use branch rules, a person reviews and approves each PR before the
merge, and the repo writes this rule in `AGENTS.md`. This control depends on a person. CI does not
enforce it. The marker is a line `Profile: <id>` with a profile of your config, or the label
`cornerstone`. A human who commits with `Actor: human` and no `Role:` is not an
implementer commit for K6.

## Commit the result

Make two commits. K6 needs the render output in its own commit.

1. The docs: `AGENTS.md`, `CLAUDE.md`, and `constitution/`. Use the trailers `Role: implementer` and
   `Actor: agent`.
2. The config and the render output: `.cornerstone/`, `.claude/`, and the CI workflow. Use the
   trailers `Role: generator` and `Actor: agent`.

Then open the PR with `/cornerstone:ticket-delivery`. Your approval of that PR is G4.

## Turn on the gates

In the GitHub settings of the repo:

1. Make the `cornerstone-checks` job a required status check (G3).
2. Require a PR review before a merge (G4).

## Keep it current

- Do not edit a generated file. Change `.cornerstone/config.yaml`, and run `stone render` again.
- If `stone render` exits with code 2, a person changed a generated file. Move the change into the
  config, or restore the file.
- To use a new framework version, update the clone and run `stone upgrade --apply`. It sets
  `framework_version` and `framework_commit`, and renders again.
- Each open `TODO(` in `.cornerstone/` is a fact that a role can need. Run
  `grep -rn "TODO(" .cornerstone/` to find them.

## Next

Pick the work: [a small change](small-change.md), [a bug](fix-a-bug.md), or
[a feature](build-a-feature.md).
