# Agent guide

This repo holds my AI workflow: the `workflow` plugin (skills), personal settings, tips, and
Cornerstone, a tool-neutral framework for agent-assisted delivery with its `stone` CLI. Read
[framework/README.md](framework/README.md) before you change the framework.

## Repo map

| Path | What it is |
| --- | --- |
| `plugins/workflow/skills/` | Skills in the open `SKILL.md` format. Generic: no repo-specific facts. |
| `.claude-plugin/marketplace.json`, `plugins/workflow/.claude-plugin/plugin.json` | Plugin marketplace and plugin version |
| `global/` | The owner's personal rules and settings. `install.sh` links them into `~/.claude`. |
| `framework/` | Cornerstone: principles, modes, gates, checks, profiles, adapters, generator design |
| `framework/adapters/` | The only place for harness, vendor, model, and spec-tool details (P12) |
| `docs/research/dossier.md` | The cited evidence for the framework |
| `docs/tips/` | How the owner works, and why |
| `stone/` | The `stone` CLI (Python 3.11+, PyYAML only) and its tests |
| `mkdocs.yml`, `website/` | The docs site, https://brawblan.github.io/ai-workflow/. `website/content/` mirrors the repo folders with symlinks. |
| `.github/workflows/stone.yml` | CI: unit tests, `stone check`, and K17 |

## Commands

| Task | Command |
| --- | --- |
| Install the CLI | `pip install ./stone` |
| Unit tests | `python -m unittest discover -s stone/tests` |
| Unit tests, in parallel (about 3 times faster). Add `-q` to show only failures and the summary | `python stone/tests/run_parallel.py` |
| Validate the framework | `stone check` |
| Writing check (K17) on your changes | `stone check-writing --diff origin/dev` |
| Validate the plugin | `claude plugin validate .` |
| Preview the docs site | `pip install -r website/requirements.txt && mkdocs serve` |
| Try a skill before you push | `claude --plugin-dir plugins/workflow` |
| All checks before a push | `python stone/tests/run_parallel.py -q && stone check && stone check-writing --diff origin/dev` |

## Rules for every task

- This repo is public. Do not commit secrets, tokens, employer names, or private project details.
  Use a placeholder such as `[SECRET_NAME]`.
- If you are not sure of the direction, or you must make many assumptions, ask first. Ask 1 to 3
  questions. Give 2 to 4 options for each, and mark one as recommended.
- If the code and a doc disagree, stop and ask. Do not choose a side.
- Before a destructive action (delete, force push, overwrite, tag move), show a WARNING and get
  approval.
- Keep each PR under the size limit (P10). The limit is `limits.pr_changed_lines` in the profile, or
  the default in [customization.md](framework/customization.md). If a PR is larger, split it, or
  record a waiver in the PR body.

## Framework changes

Before you change `framework/`, read [framework/contributing.md](framework/contributing.md). The core stays
tool-neutral, and `stone check` fails on a vendor name in it.

## Skills

- Keep skills generic. Repo facts go in the target repo's `AGENTS.md`.
- If you change a skill, increase `version` in `plugins/workflow/.claude-plugin/plugin.json`.

## Code

- Python 3.11+, with type hints, clear function names, and idempotent operations.
- Use `unittest` for tests. Do not add a dependency without a reason in the PR body.
- In GitHub Actions, pin each action to a commit SHA and set minimum permissions.
- Pass event text (for example a PR body) to a step through `env`, not inline in `run`.

## Branches and PRs

- `dev` is the integration branch. `main` holds only released code. The default branch of the
  GitHub repo is still `main`.
- Branch from `dev`. Name branches `feature/<slug>`, `fix/<slug>`, or `chore/<slug>`.
- Open each PR into `dev`. Never push to `dev` or `main` directly. Never force-push a shared branch.
- A release is a PR from `dev` into `main`. Merge it, then tag the merge commit `vX.Y.Z`. The tag
  deploys the docs site. A push to `dev` or `main` does not. Steps:
  [versioning.md](framework/versioning.md#release-checklist).
- Commit messages: `type(scope): summary` (for example `feat(stone): ...`, `docs(framework): ...`).
  Explain why in the body.
- PR body: use the nine sections of the `ticket-delivery` skill, each under its own heading. K14 tests the
  last four. If a section does not apply, write `None` and the reason.

## Writing

- Human-facing text follows ASD-STE100 (K17 checks it). Scope: [framework/writing.md](framework/writing.md).
  Rules: [ste.md](plugins/workflow/skills/ste-writing/references/ste.md).
- Do not rewrite old text only for style. To keep a correct word that K17 flags, add
  `<!-- ste-ignore -->` at the end of that line.
- Diagrams in repo files use Mermaid.
