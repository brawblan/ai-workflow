# Agent guide

<!-- Guide: Every AI coding tool loads this file on every task, so keep it short (under ~120 lines).
It says HOW to work in this repo. WHAT to build and WHY is in constitution/. Do not copy the
constitution here; link to it. Remove each Guide comment when you fill the file. -->

<One sentence: what this repo is.> Read [constitution/](constitution/README.md) before you plan a
feature.

## Repo map

| Path | What it is |
| --- | --- |
| `<path>` | <purpose> |
| `constitution/` | Mission, principles, tech stack, and roadmap |

## Commands

| Task | Command |
| --- | --- |
| Install | `<command>` |
| Run locally | `<command>` |
| Lint and format | `<command>` |
| Typecheck | `<command>` |
| Unit tests | `<command>` |
| All checks before push | `<command>` |

## Rules for every task

<!-- Guide: Only the rules that apply to small tasks too (a quick fix, a doc edit). The full MUST
list is in the principles. -->

- Follow the [principles](constitution/principles.md). They apply to every change.
- Keep each change in the folder that owns it. Ownership is in
  [tech-stack.md](constitution/tech-stack.md#ownership).
- Each change adds or updates unit tests.
- Run <lint command> before each commit.
- If the code and a doc disagree, stop and ask. Do not choose a side.

## Planning features

<!-- Guide: Remove this section if the repo does not use spec-driven development. -->

- Plan feature work before the build: <Cornerstone plans in docs/plans/ / Spec Kit / other>.
- Workflow: <link, for example docs/sdd.md>.
- Small fixes and docs edits do not need a spec.

## Branches and PRs

- Default branch: `<branch>`. Branch from it. Name branches `feature/<slug>`, `fix/<slug>`, or `chore/<slug>`.
- Open each PR into `<branch>`. Use [the PR template](.github/pull_request_template.md) if it exists.
- <promotion rule, for example: dev → staging → main, one PR per step>
- Never force-push a shared branch.

## Writing

- <style rule or link, for example docs/style/ste.md>
- Diagrams in repo files use Mermaid.

## Folder guides

<!-- Guide: List folder-level AGENTS.md files, if the repo has them. Remove the section if not. -->

- [`<path>/AGENTS.md`](<path>/AGENTS.md) — <scope>
