---
name: cornerstone-setup
description: "Set up a repo for the Cornerstone workflow: run project-setup as the Shape step, survey the repo, ask only for missing facts, write .cornerstone/config.yaml, then run stone render and stone check. Use when asked to set up Cornerstone, onboard a repo to the agent workflow framework, write or update the Cornerstone repo config, or render the role files, hooks, and CI checks. Triggers: 'set up cornerstone', 'cornerstone-setup', 'run stone render for this repo'."
disable-model-invocation: true
---

# cornerstone-setup

The entry skill for Cornerstone. It collects the repo facts and writes the repo config. The `stone`
CLI writes all other files. Do not write role files, hooks, or CI workflows by hand.

## 0. Find the framework and the CLI

1. Find a local clone of `brawblan/ai-workflow`. Ask the user for the path if you cannot find it.
   If there is no clone, ask before you clone it.
2. Use the framework at the tag that the repo config pins (`framework_version`). For a new config,
   use the latest tag, or `main` if the user says so.
3. Run `stone --version`. If the command is missing, install it: `pip install <clone>/stone`.
4. Read `<clone>/framework/customization.md`, section "Repo config". It is the source of truth for
   the config fields. Do not copy fields from memory.

## 1. Shape: run project-setup

Run the `project-setup` skill first. It writes `AGENTS.md`, `CLAUDE.md`, and `constitution/`.

- If these files exist and the user says that they are current, skip this step.
- The survey and the answers from `project-setup` are inputs to step 2. Do not ask again.

## 2. Survey the repo (read only)

Fill a fact sheet for each config field. Read before you ask.

| Field | Where to look |
| --- | --- |
| `harness` | The tool that runs this session. The name must be a file in `<clone>/framework/adapters/`. |
| `model_profile` | `<clone>/framework/adapters/<harness>/models/`. Prefer `status: active`. Tell the user if none is active. |
| `profiles` | Default `[single-ticket]`. `stone render` skips a profile with a role that the adapter has no file for. |
| `branches` | `gh repo view --json defaultBranchRef`, `AGENTS.md`, branch protection |
| `commands` | `AGENTS.md`, `CONTRIBUTING*`, `Makefile`, `package.json` scripts, `pyproject.toml`, CI steps. Copy each command exactly. |
| `paths` | The folder layout. `tests` and `checks` become protected paths for the implementer. |
| `limits` | The defaults in `customization.md`, unless `AGENTS.md` or the profile is stricter |
| `owners.default` | `CODEOWNERS`, `gh api user --jq .login`, then ask |
| `owners.solo` | Ask. True only if one person fills all human roles. |
| `modes_allowed` | Default: all three modes |
| `writing` | `AGENTS.md`, a style guide, or a dictionary file in the repo |

`stone render` needs `commands.install`, `commands.test_unit`, `commands.all_checks`, `paths.tests`,
and `paths.checks`. Look for these first.

## 3. Interview for missing facts only

- Ask 4 questions or fewer at a time. Put the survey answer first when you have one.
- If the user does not know an answer, write `TODO(<owner>): <question>` as the value. Continue.
- Do not guess a command, a path, or an owner.

- Ask: "Will the team adopt this now, or only you?" If only the user, set `delivery: local`.
  Otherwise leave `delivery` out. Keep `paths.plans` and `paths.reports` out of `.claude/`,
  `.cornerstone/`, and the test and check paths.

- Ask: "Do the roles commit, or do you? Does the repo have a commit message format?" Set
  `commits.by` and `commits.message_format`. If trailers must stay out of the history, set
  `commits.trailers` to `notes` or `none`, and tell the user what K6 loses.

- Ask: "Will each contributor use Cornerstone, or only some PRs?" If only some, set
  `adoption: opt-in`. Tell the user that an unmarked PR gets no checks.

- Ask: "Is the ticket a GitHub issue, or a file (for example from Jira)?" If a file, set
  `tickets.source: file` and `tickets.path` with `{id}`, for example `docs/tickets/{id}.txt`.
- Ask: "Does the repo have specialist review agents or skills, for example accessibility or
  security?" If yes, add them to `specialists`, with the trigger and `blocks`. Ask for an `eval`
  plan for each one.

## 4. Write the config

1. Write `.cornerstone/config.yaml` with the fields in `customization.md`, in the same order.
2. If the file exists, change only the fields with new facts. Keep the human's comments.
3. Show the diff to the user before step 5.

## 5. Render and check

Run from the repo root:

```bash
stone render --framework <clone>/framework --dry-run
stone render --framework <clone>/framework
stone check --framework <clone>/framework
```

If `delivery` is `local`, show the ignore lines that `render` prints. Tell the user to add them to
`.git/info/exclude`, and to run `stone gate` before the PR.

| Result | Action |
| --- | --- |
| `render` exit 1 | An input is not valid. Nothing was written. Fix the field that the message names, or ask the user for it. Run again. |
| `render` exit 2 (`drift <path>`) | A person changed a generated file. Do not delete it. Show the diff and ask the user: restore it, or move the change to the config. |
| `check` findings | Fix each finding in the config. Run both commands again. |

The render output is in protected paths. Commit it alone, with the trailers `Role: generator` and
`Actor: agent`. Otherwise check K6 counts the commit as an implementer commit and fails.

## 6. Report

Report:

1. Each file that `render` wrote, from its `wrote` lines.
2. Each open `TODO(` line: `grep -rn "TODO(" .cornerstone/`.
3. The manual steps that the generator cannot do: make the `cornerstone-checks` job a required
   status check (G3), and require a PR review (G4).

Offer to open a PR with the `dev-pr` skill.

## Eval

See [references/eval.md](references/eval.md).
