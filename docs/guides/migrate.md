# Migrate to Cornerstone

Use this guide when a repo already uses an agent framework. Each section compares the concepts one
to one, and gives a prompt to start the migration. The steps are the same as in
[Add Cornerstone to a repo](add-to-a-repo.md). Only the prompt is different.

Checked on 2026-10-18 against the README of each project. These tools change often. Compare the
names with your version before you start.

## What kind of migration is it?

| From | Kind | You keep | You replace |
| --- | --- | --- | --- |
| [Spec Kit](#spec-kit) | Replace the build loop | The constitution and the old specs, as history | The implement step |
| [OpenSpec](#openspec) | Add to it | All of OpenSpec. It is a spec-tool adapter. | The apply step |
| [BMAD](#bmad) | Map the concepts | The documents: brief, PRD, architecture, stories | The agent personas and the agent workflows |
| [Rule files only](#rule-files-only) | Restructure | The facts in the rules | Rules that a check can enforce |

The largest change is the same for each one. In Cornerstone, the session that writes the code does
not write its tests or review it (P2). A check, not an agent, decides that work is done (P1).

## Spec Kit

| Spec Kit | Cornerstone | Change |
| --- | --- | --- |
| `.specify/memory/constitution.md` | `constitution/principles.md`, plus `mission.md` and `tech-stack.md` | `project-setup` finds it and moves it |
| Specify step (`spec.md`) | A ticket with the [Definition of Ready](../../framework/workflow-model.md#definition-of-ready-default) fields | Add non-goals, a test oracle, and persona IDs |
| Clarify step | The shaper role | Same purpose. The shaper stops at G1. |
| Plan step (`plan.md`) | The plan artifact, `docs/plans/<id>.md` | Six fixed sections |
| Tasks step (`tasks.md`) | The progress file, `docs/plans/<id>.progress.json` | Each task has a `passes` field |
| Implement step | The implementer, tester, and reviewer, each in its own session | The largest change |
| Analyze and checklist steps | The checks (G3) and the reviewer | A program decides, not a prompt |

Prompt:

```text
/workflow:cornerstone-setup
This repo uses Spec Kit. Move .specify/memory/constitution.md into constitution/.
Keep specs/ as history. Do not convert the old specs.
New work uses Cornerstone tickets, plans, and roles.
```

After the setup, stop using the implement command in this repo.

## OpenSpec

OpenSpec is a supported spec tool. Keep it, and set `spec_tool: openspec` in the repo config.

| OpenSpec | Cornerstone | Change |
| --- | --- | --- |
| `openspec/config.yaml` context | `constitution/principles.md` points to it | `project-setup` writes the pointer |
| `openspec/specs/` | The spec of record | No change |
| A change: `proposal.md`, `design.md`, spec deltas | The plan artifact | No change. See [spec-tools.md](../../framework/adapters/spec-tools.md#openspec). |
| `tasks.md` | The progress file | Add `progress.json` for the pass state |
| Propose step | Plan, then G2 | A human approves the change PR |
| Apply step | The implementer and the tester, in separate sessions | The largest change |
| Verify step | The checks (G3) and the reviewer | Add the reviewer session |
| Archive step | Deliver | No change |

Prompt:

```text
/workflow:cornerstone-setup
This repo uses OpenSpec. Keep openspec/ as it is, and set spec_tool to openspec.
Wire openspec/config.yaml into constitution/principles.md as a pointer.
```

Plan with `/workflow:sdd-plan`. Do not build with `/workflow:sdd-build` yet. It builds and tests in
one session. Build with [the roles](run-the-roles.md).

## BMAD

BMAD gives each agent a persona, for example an analyst, a product manager, or an architect.
Cornerstone gives agents roles, not personas. A persona in a prompt does not improve results
(D15, dossier E14). In Cornerstone, personas describe the users of the product.

| BMAD | Cornerstone | Change |
| --- | --- | --- |
| Analyst and project brief | `constitution/mission.md` and `constitution/personas.md` | Move the brief. Write the user personas. |
| Product manager and PRD | `mission.md`, `roadmap.md`, and the backlog of tickets | Split the PRD by concept |
| Architect and architecture document | `tech-stack.md`, and architecture rules as fitness checks (K8) | Make each rule a check where you can (P6) |
| Scrum master and stories | Tickets with the Definition of Ready fields | Add a test oracle and persona IDs |
| Developer agent | The implementer role | Fresh session for each ticket |
| QA agent | The tester role, and the reviewer role | Two separate sessions |
| UX agent | No agent. UX facts go into the personas and the acceptance criteria. | — |
| Named agent characters | None | Remove them |

Prompt:

```text
/workflow:cornerstone-setup
This repo uses BMAD. Use the project brief, the PRD, and the architecture document
as sources for constitution/. Do not copy the agent personas.
Write user personas in constitution/personas.md from the PRD users.
List each architecture rule that a CI check can enforce.
```

After the setup, remove the BMAD agent files from the harness folders in a separate PR.

## Rule files only

This includes a long `CLAUDE.md`, `.cursor/rules/`, `.github/copilot-instructions.md`, or a
`GEMINI.md`.

| Rule file | Cornerstone | Change |
| --- | --- | --- |
| One long instruction file | `AGENTS.md` under 300 lines, and `constitution/` | Facts move to the file that owns them |
| One rule file for each tool | One `AGENTS.md`. Each tool loads it, or a one-line import. | Merge the files |
| "Always write tests" | The tester role and check K6 | The rule becomes a role and a check |
| "Run the linter before a commit" | Check K1 in G3 | The rule becomes a check (P6) |
| "Ask before you delete" | G5 and a deny list in the harness settings | The rule becomes a gate |

Prompt:

```text
/workflow:cornerstone-setup
Merge CLAUDE.md, .cursor/rules/, and .github/copilot-instructions.md into AGENTS.md.
For each rule, tell me if a CI check can enforce it. List those rules separately.
```

## After each migration

1. Commit the docs and the render output separately. See
   [Add Cornerstone to a repo](add-to-a-repo.md#commit-the-result).
2. Make the old framework's commands unavailable in the repo, or say in `AGENTS.md` not to use them.
3. Run the first ticket with [Make a small change](small-change.md). A small first ticket shows the
   gaps in the setup with low risk.
