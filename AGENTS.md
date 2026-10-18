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
| `.github/workflows/stone.yml` | CI: unit tests, `stone check`, and K17 |

## Commands

| Task | Command |
| --- | --- |
| Install the CLI | `pip install ./stone` |
| Unit tests | `python -m unittest discover -s stone/tests` |
| Validate the framework | `stone check` |
| Writing check (K17) on your changes | `stone check-writing --diff origin/main` |
| Validate the plugin | `claude plugin validate .` |
| Try a skill before you push | `claude --plugin-dir plugins/workflow` |
| All checks before a push | `python -m unittest discover -s stone/tests && stone check && stone check-writing --diff origin/main` |

## Rules for every task

- This repo is public. Do not commit secrets, tokens, employer names, or private project details.
  Use a placeholder such as `[SECRET_NAME]`.
- If you are not sure of the direction, or you must make many assumptions, ask first. Ask 1 to 3
  questions. Give 2 to 4 options for each, and mark one as recommended.
- If the code and a doc disagree, stop and ask. Do not choose a side.
- Before a destructive action (delete, force push, overwrite, tag move), show a WARNING and get
  approval.
- Keep each PR under 600 changed lines (P10). If it is larger, split it, or record a waiver in the
  PR body.

## Framework changes

- Keep the core neutral. Put each harness, vendor, model, or spec-tool name in `framework/adapters/`.
  `stone check` fails on a vendor name in the core.
- When you change a profile, update the gates table in `framework/gates.md` in the same PR.
- Record each design decision in the "Decisions" table of `framework/README.md` (D1, D2, ...).
- Support each new rule with evidence. Add the source to the dossier and cite its ID.
- Give each new component (rule, skill, role, hook, check) an eval plan and a review date (P5).

## Skills

- Keep skills generic. Repo facts go in the target repo's `AGENTS.md`.
- If you change a skill, increase `version` in `plugins/workflow/.claude-plugin/plugin.json`.

## Code

- Python 3.11+, with type hints, clear function names, and idempotent operations.
- Use `unittest` for tests. Do not add a dependency without a reason in the PR body.
- In GitHub Actions, pin each action to a commit SHA and set minimum permissions.
- Pass event text (for example a PR body) to a step through `env`, not inline in `run`.

## Branches and PRs

- Default branch: `main`. Branch from it. Name branches `feature/<slug>`, `fix/<slug>`, or
  `chore/<slug>`.
- Open each PR into `main`. Never push to `main` directly. Never force-push a shared branch.
- Commit messages: `type(scope): summary` (for example `feat(stone): ...`, `docs(framework): ...`).
  Explain why in the body.
- PR body sections: Summary, Why this change, Validation run, Risks, Rollback plan.

## Writing

- Human-facing text (docs, PR bodies, commits, reports) follows ASD-STE100. See
  [framework/writing.md](framework/writing.md) for the scope and
  [ste.md](plugins/workflow/skills/ste-writing/references/ste.md) for the rules.
- Do not rewrite old text only for style.
- If K17 flags a correct use of a word, add `<!-- ste-ignore -->` at the end of that line.
- Diagrams in repo files use Mermaid.
