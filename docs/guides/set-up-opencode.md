# Set up Cornerstone with OpenCode

Use this guide to run the Cornerstone roles on OpenCode in a repo, with its CI triggers. The repo can
be private. OpenCode is the second harness adapter (D118). The Claude Code steps are in
[Add Cornerstone to a repo](add-to-a-repo.md).

| | |
| --- | --- |
| Profile | [single-ticket](../../framework/profiles/single-ticket.md), as an example. Any profile works. |
| Status | Works today. The rendered CI workflows are not yet proven on a runner (see [Limits](#limits)). |
| Time | About 20 minutes, with an OpenCode plan already active |

## What you get

| Item | Result |
| --- | --- |
| Role files | `stone render` writes `.opencode/agents/<role>.md` for each role of your profiles |
| Project config | `stone render` merges `opencode.json`. It denies an edit of the harness paths. |
| Checks and G3 | The shared checks K6, K7, K15, K16, and K22, and the G3 workflow (D123) |
| CI triggers | One workflow for each label, `ci:issue-opened`, or schedule trigger (D119) |
| Token report | `stone usage` reads your OpenCode sessions (D122) |

## Before you start

1. Install OpenCode. The tests of the adapter used version 2.2.6. Run `opencode --version` to see yours.
2. Log in to your plan with `opencode auth login`.
3. Keep `~/.config/opencode` empty. A run also reads it.
4. Clone this repo and install the CLI:

   ```bash
   git clone https://github.com/brawblan/ai-workflow.git ~/Repos/ai-workflow
   pip install ~/Repos/ai-workflow/stone
   ```

5. Make sure that the repo has a test command, and that CI runs it.

The Claude Code plugin is not needed. OpenCode does not read `CLAUDE.md`. Put your rules in
`AGENTS.md`.

## Steps

### 1. Select the harness

1. Make a branch:

   ```bash
   git switch -c chore/cornerstone-opencode
   ```

2. Make `.cornerstone/config.yaml`. Start from the example in
   [customization.md](../../framework/customization.md#repo-config-cornerstoneconfigyaml). Set these
   fields:

   ```yaml
   framework_version: <tag>          # the latest tag of this repo. The OpenCode adapter needs 1.8.0 or later.
   harness: opencode
   model_profile: opencode-default
   profiles: [single-ticket]
   ```

3. Fill in `commands.all_checks` and the `paths` fields. They decide what a role can change. See
   the table in [Add Cornerstone to a repo](add-to-a-repo.md#steps).

### 2. Render

1. Show what render will write:

   ```bash
   stone render --dry-run
   ```

2. Write the files:

   ```bash
   stone render
   ```

3. Run `stone check`. It must pass.

For `single-ticket`, render writes these files:

| File | What it is |
| --- | --- |
| `.opencode/agents/<role>.md` | A role file for the shaper, implementer, tester, and reviewer |
| `.opencode/agents/shaper-ci.md` | The read-only copy of the first role. The label workflow runs it. |
| `opencode.json` | The project permission rules |
| `.cornerstone/` | The manifest, the checks, and the config |
| `.github/workflows/cornerstone-single-ticket-label.yml` | The label trigger |
| `.github/workflows/cornerstone-checks.yml` | The G3 workflow |

### 3. Add the plan key

1. Get the API key of your OpenCode plan.
2. Add it as the repository secret `OPENCODE_API_KEY`:

   ```bash
   gh secret set OPENCODE_API_KEY
   ```

   `gh` asks for the value. Do not put the key in a file or on the command line.
3. Do not add the key to a role file or to `opencode.json`. The workflow gives it to one step only.

### 4. Add the trigger label

The label name comes from the profile. For `single-ticket`, it is `agent-ready`.

```bash
gh label create agent-ready --description "Start the Cornerstone role"
```

If two profiles use one label, also make a label `profile:<id>` for each. Add the `profile:<id>`
label first, then the trigger label.

### 5. Commit the result

Make two commits. K6 needs the render output in its own commit.

1. The docs and `AGENTS.md`. Use the trailers `Role: implementer` and `Actor: agent`.
2. `.cornerstone/`, `.opencode/`, `opencode.json`, and `.github/workflows/`. Use the trailers
   `Role: generator` and `Actor: agent`.

Open the PR. Turn on the gates in the GitHub settings of the repo:

1. Make the `cornerstone-checks` job a required status check (G3).
2. Require a PR review before a merge (G4).

### 6. Try it

1. Open an issue that meets the Definition of Ready.
2. Add the label `agent-ready`.
3. Wait for the workflow. It posts a comment on the issue.

## Which roles run where

OpenCode has no hook before a file edit. So the CI copy of a role has only the `read`, `grep`, and
`glob` tools. A role with the shell could read the plan key from the process environment (D39).

| Where | Roles | Why |
| --- | --- | --- |
| In CI | Only the first role of a profile. It reads, then posts a report. | The CI copy has no shell and no edit. It can read and report only. |
| Locally | All roles, with the full role file | They run tests and change files. They need the shell and `edit`. |

Each trigger starts the first role of its profile:

| Profile | Trigger | Role in CI |
| --- | --- | --- |
| single-ticket, app-slice | `label:agent-ready` | shaper. It checks the readiness of the ticket only. |
| debugging | `label:agent-ready` | investigator |
| bug-triage | `ci:issue-opened`, `schedule:daily` | investigator |
| code-audit | `schedule:monthly` | investigator |
| adapter-refresh | `schedule:weekly` | investigator |
| dependency-upgrade | `schedule:weekly` | investigator. The `ci:dependency-pr` trigger gives no file on OpenCode. |

To run a role locally, start it in its own session (P2):

```bash
opencode run --agent tester "Write tests for ticket 123."
```

Use one session for each role. [Run the roles](run-the-roles.md) shows the same steps for each role
and the paths that each role can change.

## Pick a model for each role

`stone render` writes the `model` of each role file from `defaults.role_models` of the model
profile. The profile `opencode-default` gives `opencode-go/beam-free` to every role. That model is
the baseline.

The picks come from the model matrix of [Compare models with evals](compare-models.md) (D120):

| Pick | Use it when | Rule |
| --- | --- | --- |
| Baseline | You want no change, or the role has no pick | The role model of the profile |
| Economy | You run the role often, and a lower cost matters most | The lowest cost for each passing run. Its pass rate is the same as the baseline, within 1 standard error. |
| Quality | The role decides the result, and a mistake costs more than the model | The highest pass rate. Its cost for each passing run is not above the baseline. |

The picks are in the table "Model picks" of the [OpenCode adapter](../../framework/adapters/opencode.md#model-picks-d120).
If the table has no row for a role, use the baseline. A pick needs 3 trials for each scenario.

A pick changes no role model. A human decides that at G4. To use a pick on one local run, pass the
model:

```bash
opencode run --agent tester --model opencode-go/<pick> "Write tests for ticket 123."
```

A CI run uses the model in the rendered role file.

## Limits

- The rendered workflows have run only in unit tests and golden files. The #325 spike proved the
  same install, run command, and key in a private repo. Run one trigger in a test repo first.
- A role in CI cannot use the shell or the code index. A step of a profile that needs the shell
  does not run, and the role says so in the report.
- A path rule limits the file tools, not the shell (D39). K6 in CI finds a shell write in the PR.
- OpenCode has no cost limit. The step cap (30 in CI) and the 20-minute job limit are the only
  controls. Each `ci:issue-opened` run costs plan usage, and anyone can start it.
- A `schedule` trigger can fire in a DeepSeek peak window. Render prints a `WARNING` if it does.
- The CI install pins OpenCode 2.2.6 and checks its SHA-256. A later version needs a change in
  `values.py`.

## Keep it current

- Do not edit a generated file. Change `.cornerstone/config.yaml`, and run `stone render` again.
- To use a new framework version, run `stone upgrade --apply`.
- To see the cost of your sessions, run `stone usage`. The cost is an estimate from
  [rates.yaml](../../framework/adapters/opencode/rates.yaml).

## Next

Pick the work: [a small change](small-change.md), [a bug](fix-a-bug.md), or
[triage reports](bug-triage.md).
