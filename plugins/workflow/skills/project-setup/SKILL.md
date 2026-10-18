---
name: project-setup
description: "Set up or update a repo's agent docs: a constitution/ folder (mission, personas, principles, tech stack, roadmap), a short AGENTS.md with a CLAUDE.md import, and the OpenSpec wiring if the repo uses OpenSpec. Reads the repo first, then asks the user only for missing facts. Use when asked to set up a repo for AI agents, create or update a constitution, write AGENTS.md or CLAUDE.md, onboard a repo to spec-driven development, or make a user-level AGENTS.md."
---

# project-setup

Make the documents that agents need, from the facts in the repo and a short interview.
The templates are in [templates/](templates/). Each template has `<!-- Guide: -->` comments. Follow
them, then remove them.

| Template | Target | Job |
| --- | --- | --- |
| `constitution/README.md` | `constitution/README.md` | Index of the constitution |
| `constitution/mission.md` | `constitution/mission.md` | Vision, audience, tone, scope, non-goals |
| `constitution/personas.md` | `constitution/personas.md` | The users: who, job stories, limits, evidence |
| `constitution/principles.md` | `constitution/principles.md` | MUST rules (repos without OpenSpec) |
| `constitution/principles.openspec.md` | `constitution/principles.md` | Pointer to `openspec/config.yaml` (repos with OpenSpec) |
| `constitution/tech-stack.md` | `constitution/tech-stack.md` | Approved technology, ownership, deploy limits, gates |
| `constitution/roadmap.md` | `constitution/roadmap.md` | Phases and milestones, in order |
| `openspec/config.yaml` | `openspec/config.yaml` | Principles in `context`, and read rules for each artifact |
| `repo/AGENTS.md` | `AGENTS.md` | How to work in the repo. Every tool loads it. |
| `repo/CLAUDE.md` | `CLAUDE.md` | One line, `@AGENTS.md`, so Claude Code loads the same file |
| `user/AGENTS.md` | `~/.claude/` or the tool's user folder | Personal preferences for all repos |

If the user asks only for a user-level file, do step 3 with the "User file" questions, and write
`user/AGENTS.md`. Skip the other steps.

## 1. Survey the repo (read only)

Read before you ask. Collect facts into a short fact sheet:

- `README*`, `CONTRIBUTING*`, `AGENTS.md`, `CLAUDE.md`, and folder-level copies of them
- Manifests: `package.json` (and workspaces), `pyproject.toml`, `requirements*.txt`, `go.mod`, `Cargo.toml`
- CI: `.github/workflows/`. Infra: `infra/`, `terraform/`, `Dockerfile`, `docker-compose*`
- Docs: `docs/`, planning folders, ADRs, a backlog file, a style guide
- `openspec/config.yaml`, `openspec/project.md` (old OpenSpec), `.specify/memory/constitution.md` (Spec Kit)
- `git log --oneline -20` and `gh repo view --json nameWithOwner,defaultBranchRef`

For each target file, find what already exists. A doc that already owns a concept is the source.
Examples: a product doc owns the mission, a stack doc owns the tech stack, a priority list owns the
roadmap.

## 2. Show the file map, and get approval

Show one table: target file, source (existing doc, facts found, or interview), and action.

| Action | When |
| --- | --- |
| **Move** | An existing doc owns the concept. Move it with `git mv`, add the missing sections, and update all links. |
| **Fill** | Facts exist in many places. Write the file from the template with those facts. |
| **Interview** | No facts exist. Ask the user. |
| **Pointer** | The content must stay in another file (for example principles in `openspec/config.yaml`). |

Rules for the map:

- Each concept has one owner file. Do not copy a section into a second file. Link to it.
- If `AGENTS.md` and `CLAUDE.md` both have content, merge them into `AGENTS.md`. Then set `CLAUDE.md`
  to `@AGENTS.md`.
- Content in `AGENTS.md` that the constitution owns (ownership, principles, stack) moves to the
  constitution. `AGENTS.md` keeps a link.
- Folder-level `AGENTS.md` or `CLAUDE.md` files stay. If one contradicts the constitution, report it.

Wait for the user to approve the map.

## 3. Interview for missing facts only

- Ask 4 questions or fewer at a time. Group them by file.
- Put the answer from the survey as the first option, when you have one.
- If the user does not know an answer, write `TODO(<owner>): <question>` in the file, and continue.

Question bank (ask only the ones that the survey did not answer):

| File | Questions |
| --- | --- |
| Mission | What changes for the user when this works? Who is the primary user, and who is not? What are 3 non-goals? What is the product voice? What is the engineering tone (strict or relaxed)? (Optional) How will you know it works? |
| Personas | Which 1 to 5 types of people use the product? For each one: who are they, in one line? What are 3 to 5 things that they must get done ("When I ..., I want to ..., so that ...")? Which device, skill, and access limits do they have? Did you talk to real users of this type (validated), or is it a guess (assumed)? |
| Principles | Which rules must every change follow (security, tests, data isolation, accessibility, ownership)? What are the merge gates? What is exempt from the test rule? |
| Tech stack | Which tools are approved but not in the manifests yet? Which tools are not allowed? What are the deploy limits (cost, regions, one project per environment)? Which environments exist? |
| Roadmap | What is the goal of the current phase? What ends the phase? Which epics or issues are in it, in order? What comes next? |
| AGENTS.md | What is the default branch, and the promotion path? Which command runs all checks before a push? Which writing rules apply? |
| User file | What is your role? Where are you strong, and where are you new? Which actions need your approval first? Which writing and code habits do you want? |

## 4. Write the files

1. Copy each template to its target. Fill it from the fact sheet and the answers.
2. Remove every `<!-- Guide: -->` comment and every unused optional section.
3. Leave no `<placeholder>` text. Use a `TODO(<owner>)` line for a deferred answer.
4. Keep `AGENTS.md` under about 120 lines. Move detail to the constitution or to `docs/`.
5. If you moved a doc, update every link to it: `git grep -n "<old name>"`.
   Do not edit archived or frozen history (for example `openspec/changes/archive/`, `specs/`).

## 5. Wire up spec-driven development

**If the repo uses OpenSpec** (`openspec/` exists):

- OpenSpec copies `config.yaml` `context` into every artifact. It is the framework's place for the
  constitution's rules. Put the principles there, not in `constitution/principles.md`.
- Use `constitution/principles.openspec.md` as `constitution/principles.md`.
- Add to `context` the 3-line summary from the template, with the pointers to `constitution/`.
- Add the `rules.proposal` and `rules.design` lines from the template. They make the agent read
  `mission.md` and `roadmap.md` for proposals, and `tech-stack.md` for designs, and nothing more.
- If the repo has `openspec/project.md`, move its content into `context` and the constitution.
- If `context` already has a version heading, increase the MINOR version.
- Run `openspec validate --all --strict`.

**If the repo uses another SDD tool** (for example Spec Kit), keep the principles in
`constitution/principles.md`. Point the tool's constitution file to it, or move that file there.

**If the repo uses no SDD tool**, keep the principles in `constitution/principles.md`. In
`AGENTS.md`, remove the "Planning features" section, or describe the plain-spec flow that the user
wants.

## 6. Check

- Every link in the new and changed files resolves.
- `git grep -n "<!-- Guide:"` finds nothing in the target files.
- No template placeholders are left (for example `<vision>`, `<slug>`, `<command>`, `<branch>`). Read each
  target file to confirm. A regex search also finds real HTML and generics, so do not trust it alone.
- No secrets, tokens, or private hostnames are in the files.
- The repo's lint or format command passes on the changed files.
- If OpenSpec is present, `openspec validate --all --strict` passes.
- If `stone` is installed, `stone check` reports no K18 finding for `constitution/personas.md`.

## 7. Hand off

Report: the files made or moved, the open `TODO` lines, and any contradictions that you found.
Offer to open a PR with the `dev-pr` skill.
