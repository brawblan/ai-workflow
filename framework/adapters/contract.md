# Adapter contract

An adapter maps the neutral core to one harness or one spec tool. The generator uses the adapter
to write files. The core does not change when an adapter changes (P12).

## Adapter types

| Type | Maps | v0 adapters |
| --- | --- | --- |
| Harness adapter | Instruction file, skills, roles, hooks, sessions, triggers | [claude-code.md](claude-code.md) |
| Spec-tool adapter | Plan artifact, progress file, plan approval | [spec-tools.md](spec-tools.md) (plain) |
| Model profile | The idioms of one model family inside one harness: prompt style, plan use, effort, role models, limits | [claude-code/models/claude-5.yaml](claude-code/models/claude-5.yaml) |

## Adapter status

The component list of an adapter can set `status`:

| Value | Meaning |
| --- | --- |
| `full` (default) | The adapter gives templates, and `stone render` writes the files. |
| `eval-only` | The adapter gives `eval.yaml` and the role file paths. `stone eval` uses it. `stone render` refuses it. |

The repo has two harness adapters:

- `claude-code` is the full adapter.
- `opencode` is eval-only (D112): `stone eval` uses it, and `stone render` refuses it.

An `eval-only` adapter gives the role file paths and the role templates that `stone eval` renders.
It needs no templates for a full render of hooks, CI, or settings. It must still give a target and
an eval for each component. The status is in `components.yaml`, so the core names no harness.

## What a harness adapter MUST provide

1. A mapping table with one row for each concept below.
2. For each row, give the target path, the file format, and the support level (full, partial, none).
   If the support is not full, give the fallback.
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

### Adapter template values

An adapter MAY add `values.py` at its root. It MUST provide `values(config: dict) -> dict[str, str]`.
The core passes neutral ticket state in `config`. It builds no harness tool names or permission
schemas. Each value becomes a string for the templates. An adapter key MUST NOT reuse a core key.

### Adapter data files

The commands of `stone` read these files from `framework/adapters/<name>/`. The core holds no
harness format of its own (P12). An adapter without a file cannot use the command that reads it.

| File | Read by | What it gives |
| --- | --- | --- |
| `components.yaml` | `stone render`, `stone eval` | The file of each component, and the adapter `status` |
| `eval.yaml` | `stone eval` | `run`: the command for each variant. `env`, `tools`, and `trigger` for each role or trigger. `output` and `output_where`: the fields of the harness output. |
| `eval.yaml`, optional keys | `stone eval` | `parser`: a parser file. `rates`: a rates file (D116). `unsupported`: the reason for each eval kind that the adapter cannot run. |
| Parser file | `stone eval` | `parse` returns the usage fields. `transcript_stats` returns the tool calls and the result bytes. Without a parser, the runner reads the last JSON object. |
| Rates file | `stone eval` | The token rates of each model in USD for each 1M tokens, the `source`, the `read` date, and optional peak windows (D116) |
| `usage.yaml` | `stone usage` | The transcript folders, the record format, and the weights (D114) |
| `values.py` | `stone render` | The template values (see above) |

## What a model profile MUST provide

A model profile changes more often than a harness adapter. A new model from the same vendor changes
only its model profile. Use [model-profile-template.yaml](model-profile-template.yaml).

1. The exact model IDs that it covers.
2. A source URL and a read date for each source.
3. For each idiom, give the area, one sentence of guidance, the source, and the affected components.
   Add an eval. If no eval exists yet, leave the field empty.
4. A status: `proposed`, `active`, or `retired`. Only an `active` profile can be the default in a
   target repo. A profile becomes `active` when the [adapter-refresh](../profiles/adapter-refresh.md)
   evals support it. An `active` profile can have idioms with no eval yet. Such an idiom is not
   proven (D37 in the [framework decisions](../README.md)).

Path: `framework/adapters/<harness>/models/<model-family>.yaml`. All vendor adapters and model
profiles stay in the repo. A target repo selects one of each in its config.

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
