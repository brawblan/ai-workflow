# ai-workflow

The home of **Cornerstone**, a tool-neutral framework for agent-assisted software delivery, and
its `stone` CLI. The repo also has the `workflow` plugin skills, my personal agent rules, and tips.

Read the docs at [brawblan.github.io/ai-workflow](https://brawblan.github.io/ai-workflow/).

Cornerstone says how a human and an agent deliver software together. It sets who does each stage,
which gates stop the work, and which checks decide that work is done. The core never names a tool.
Adapters turn the core into files for one harness. `stone render` writes those files into a target
repo.

## Why Cornerstone exists

Models change. A rule, a skill, or a planning step that helps one model can hurt the next model.
So each part of the workflow has a reason, an eval, and a review date. When the evidence goes, the
part goes. The evidence is in the [research dossier](docs/research/dossier.md).

Four principles do most of the work:

- **Checks decide (P1).** CI output, not an agent claim, shows that work is done.
- **Separate the writer from the judge (P2).** The implementer does not write its tests or approve
  its own change. Each role runs in a fresh session.
- **Judgment goes into the inputs (P3).** A human makes the ticket ready. Then the prompt can be
  simple.
- **Ceremony scales with risk (P7).** A profile sets the plan form and the gates for each type of
  work.

All 12 principles are in [framework/principles.md](framework/principles.md).

## Status

Draft v0. The framework is complete enough to use on one profile. Other parts are design only.

| Part | State |
| --- | --- |
| [Framework](framework/README.md): principles, workflow model, gates, checks, modes, 10 profiles | Draft v0 |
| [Harness adapter](framework/adapters/claude-code.md) and [model profile](framework/adapters/claude-code/models/claude-5.yaml) | First adapter. The model profile evals are not written yet. |
| [`stone`](stone/README.md) 0.7 | `stone check`, `stone check-writing` (K17), `stone check-evidence` (K14), `stone spec apply` and `sync`, `stone render` for the single-ticket and app-slice profiles, and `stone eval` |
| [`workflow` plugin](plugins/workflow/) 0.6.0 | Six skills. `cornerstone-setup` is the entry skill. |
| This repo | Uses Cornerstone on itself: [`.cornerstone/config.yaml`](.cornerstone/config.yaml) and CI in [`stone.yml`](.github/workflows/stone.yml) |

The next steps are in the [roadmap](framework/README.md#roadmap). The design decisions (D1, D2, ...)
are in the [decisions table](framework/README.md#decisions).

## How the parts fit

```mermaid
flowchart LR
  subgraph Repo[This repo]
    P[Principles] --> M[Workflow model<br/>stages, roles, gates, checks]
    M --> PR[Profiles and modes]
    PR --> A[Adapters and<br/>model profiles]
    S[cornerstone-setup skill]
  end
  S -- writes --> C[.cornerstone/config.yaml]
  A --> R[stone render]
  C --> R
  R -- writes --> T[(Target repo<br/>roles, hooks, CI checks,<br/>manifest)]
  K[stone check] -. validates .-> Repo
```

Caption: the setup skill collects the repo facts. `stone render` combines them with the framework
and writes the generated files.

| Concept | What it is | Read more |
| --- | --- | --- |
| Stages | Intake, Shape, Plan, Build, Test, Verify, Review, Deliver, Learn | [workflow-model.md](framework/workflow-model.md) |
| Roles | Shaper, planner, implementer, tester, reviewer, investigator | [workflow-model.md](framework/workflow-model.md#roles) |
| Gates | G1 Ready, G2 Plan approved, G3 Checks pass, G4 Change approved, G5 Release approved | [gates.md](framework/gates.md) |
| Checks | K1 to K19. Programs that run in CI, outside the agent session. | [checks.md](framework/checks.md) |
| Profiles | One configuration for each type of work, for example single-ticket, debugging, or spike | [profiles/](framework/profiles/README.md) |
| Modes | Who drives each stage: agent-centric, hybrid, or human-centric | [modes.md](framework/modes.md) |
| Adapters | The only place for harness, vendor, model, and spec-tool details | [adapters/](framework/adapters/contract.md) |

## Set up a repo with Cornerstone

The [guides](docs/guides/README.md) cover each situation: a new project, an existing repo, a
migration from another framework, and the daily work after the setup. This section is the short
version.

You need Python 3.11 or later, `git`, the GitHub CLI (`gh`), and Claude Code. Claude Code is the
only harness adapter at this time.

1. Clone this repo and install the CLI:

   ```bash
   git clone https://github.com/brawblan/ai-workflow.git
   pip install ./ai-workflow/stone
   ```

2. Install the `workflow` plugin (see [Install the plugin](#install-the-plugin-for-claude-code)).
3. In the target repo, run `/workflow:cornerstone-setup`.

The skill runs `project-setup` first. That skill writes `AGENTS.md`, `CLAUDE.md`, and
`constitution/`. Then `cornerstone-setup` asks only for the facts that it cannot find in the repo.
It writes `.cornerstone/config.yaml`, and runs `stone render` and `stone check`.

For the single-ticket profile, `stone render` writes:

```text
.claude/agents/            shaper, implementer, tester, and reviewer roles
.cornerstone/hooks/        a hook that stops the implementer from changing tests and checks
.claude/settings.json      the hook entry (other keys stay as they are)
.cornerstone/checks/       check K6 (protected paths), for CI
.github/workflows/         the G3 CI workflow
.cornerstone/manifest.yaml what stone render owns, with a hash for each file
```

For the app-slice profile, it also writes the planner role. A second run changes only the files
whose input changed. The repo config fields are in
[customization.md](framework/customization.md).

## The skills

The plugin skills are the first harness implementation of parts of the framework. `stone render`
writes the planner, tester, and reviewer roles, so the plugin has no skill for them (D14, D18).

| Skill | What it does |
| --- | --- |
| `cornerstone-setup` | Set up a repo for Cornerstone. It runs `project-setup`, writes `.cornerstone/config.yaml`, and runs `stone render` and `stone check`. |
| `project-setup` | Set up a repo for agents: `constitution/` (with personas and job stories), and `AGENTS.md`. It asks only for facts the repo does not have. |
| `ticket-delivery` | Collect the tester, reviewer, and check evidence for each acceptance criterion. Then open the PR with `dev-pr`. |
| `dev-pr` | Branch, commit, rebase, validate, and open a PR into the integration branch, with the evidence sections. |
| `backlog-sequencer` | Sync a `status:blocked` label from "Depends on #N" text. Suggest priority labels. |
| `ste-writing` | Write with Simplified Technical English rules, and add diagrams. |

`cornerstone-setup` needs the `stone` CLI and a clone of this repo. The other skills need only `git`
and `gh`.

## Install the plugin for Claude Code

1. In Claude Code, add the marketplace:

   ```
   /plugin marketplace add brawblan/ai-workflow
   ```

2. Install the plugin:

   ```
   /plugin install workflow@brawblan
   ```

3. Restart Claude Code. The skills have the `workflow:` prefix, for example `/workflow:dev-pr`.

To get updates, run `/plugin marketplace update brawblan`. You can also turn on auto-update for
the marketplace in the `/plugin` menu.

## Use the skills with other agents

The skills use the open `SKILL.md` format. `stone render` has no adapter for other harnesses yet.

1. Copy a folder from `plugins/workflow/skills/` into your agent's skills folder.
   See [docs/tips/other-tools.md](docs/tips/other-tools.md) for each tool.
2. To set up a repo without the plugin, tell your agent:

   ```text
   Follow plugins/workflow/skills/project-setup/SKILL.md from github.com/brawblan/ai-workflow.
   Use the templates next to it.
   ```

3. If you want my writing rules, copy [`global/AGENTS.md`](global/AGENTS.md) into your
   `AGENTS.md` or your tool's instructions file.

## Repo map

| Path | What it has |
| --- | --- |
| [`framework/`](framework/README.md) | Cornerstone: principles, workflow model, gates, checks, modes, profiles, lifecycle, writing standard, generator design |
| [`framework/adapters/`](framework/adapters/contract.md) | Harness adapters, model profiles, spec-tool adapters, and the templates for `stone render` |
| [`stone/`](stone/README.md) | The `stone` CLI (Python 3.11+, PyYAML only) and its tests |
| [`plugins/workflow/skills/`](plugins/workflow/skills/) | The plugin skills, and the `project-setup` templates |
| [`docs/research/`](docs/research/dossier.md) | The cited evidence for the framework |
| [`docs/guides/`](docs/guides/README.md) | How to use Cornerstone, one situation at a time |
| [`docs/tips/`](docs/tips/README.md) | How I work with agents, and why |
| [`website/`](website/), [`mkdocs.yml`](mkdocs.yml) | The [docs site](https://brawblan.github.io/ai-workflow/), built with MkDocs Material |
| [`global/`](global/README.md) | My personal agent rules and settings, and how I sync them across devices |
| [`AGENTS.md`](AGENTS.md) | How agents work in this repo: commands, rules, branches, and writing |

## Contribute

Read [AGENTS.md](AGENTS.md) and [framework/README.md](framework/README.md) before you change the
framework. Run all checks before a push:

```bash
python -m unittest discover -s stone/tests && stone check && stone check-writing --diff origin/main
```

This repo is public. Read each `git diff` before you push.

- Do not commit secrets, tokens, `settings.local.json`, or MCP credentials.
- Do not commit employer code, employer names, or private project details.
- Keep skills generic. Put repo-specific facts in that repo's `CLAUDE.md` or `AGENTS.md`.
- Keep harness, vendor, model, and spec-tool names out of the framework core (P12).

## License

[MIT](LICENSE)
