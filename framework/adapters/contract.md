# Adapter contract

An adapter maps the neutral core to one harness or one spec tool. The generator uses the adapter
to write files. The core does not change when an adapter changes (P12).

## Adapter types

| Type | Maps | v0 adapters |
| --- | --- | --- |
| Harness adapter | Instruction file, skills, roles, hooks, sessions, triggers | [claude-code.md](claude-code.md) |
| Spec-tool adapter | Plan artifact, progress file, plan approval | [spec-tools.md](spec-tools.md) (plain, OpenSpec) |

## What a harness adapter MUST provide

1. A mapping table with one row for each concept below.
2. For each row: the target path, the file format, the support level (full, partial, none), and the
   fallback if the support is not full.
3. A template folder: `framework/adapters/<name>/templates/`. The generator renders these files.
4. A list of the facts that can change with harness versions. Mark each one `[TO CONFIRM]` until a
   test proves it.

| Concept | Required support | Fallback if partial or none |
| --- | --- | --- |
| Instruction file | full | none. An adapter without it is not valid. |
| Skill (on-demand procedure) | full or partial | Linked docs that the instruction file names |
| Role with its own tools and permissions | partial or better | Separate sessions with a role prompt, plus CI checks |
| Fresh session for each role | full | none. P2 needs it. |
| Headless run (no human at the terminal) | full | none. CI needs it. |
| Hook before a file edit | optional | Check K6 in CI |
| Hook before the session ends | optional | Gate G3 in CI |
| Model choice for each role | optional | One model for all roles |
| Permission allowlist and sandbox | partial or better | Run in a container with no secrets |
| CI trigger (issue label, PR event, schedule) | full | none |

## What a spec-tool adapter MUST provide

| Concept | Required support |
| --- | --- |
| Plan artifact with the six sections in [workflow-model.md](../workflow-model.md#plan-artifact-sections) | full, or a mapping from the tool's files to each section |
| Progress file with a pass state for each task | full or a fallback |
| A way to record G2 approval | full |
| A validate command that returns pass or fail | optional |

## How to add an adapter

1. Copy [claude-code.md](claude-code.md) as a model.
2. Fill the mapping table. Mark each unproven fact `[TO CONFIRM]`.
3. Add the templates.
4. Run the generator on a test repo. Run the eval set for one profile.
5. Remove each `[TO CONFIRM]` mark that the test proves.
