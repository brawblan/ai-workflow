# Generator design

Status: design only (v0). No code yet.

## Goal

Write the files for a target repo from the framework, one harness adapter, one spec-tool adapter,
and the repo config. The same inputs MUST give the same files.

| Item | Value |
| --- | --- |
| Trigger | A person runs the CLI, or the `framework-setup` skill runs it |
| Inputs | `framework/` (this repo, at a version tag), `.ai-workflow/config.yaml`, profile overrides |
| Outputs | Instruction file, skills, roles, hooks, CI workflows, check scripts, templates, `.ai-workflow/manifest.yaml` |
| Owner | brawblan |

Reason for a CLI plus a skill: a deterministic CLI gives repeatable files, and generated free-text
context files did not help agents (dossier A3, A4). The skill only collects facts and fills the
repo config.

## Parts

| Part | Job |
| --- | --- |
| `aiwf` CLI (Python 3) | Read the inputs, validate them, render the templates, write the files and the manifest. |
| `framework-setup` skill | Survey the repo, interview the human for missing facts, write `.ai-workflow/config.yaml`, then run the CLI. |
| Templates | Jinja2 files in `framework/adapters/<adapter>/templates/`. |

## Commands

| Command | Does |
| --- | --- |
| `aiwf init` | Make `.ai-workflow/config.yaml` with `TODO(<owner>)` values. |
| `aiwf render` | Write all files from the inputs. Safe to run again. |
| `aiwf check` | Validate the config, the profiles, and the manifest. Report drift between files and templates. |
| `aiwf review` | List the components past `review_by`. Exit code 1 if there are any. |
| `aiwf eval <component-id>` | Run the component's eval with and without the component. (Later version.) |

## Constraints

- Python 3.11 or later. Type hints. No network access during `render`.
- Idempotent: a second `render` with the same inputs changes no file.
- Generated content sits between markers. Content outside the markers belongs to the human.

```text
<!-- aiwf:begin id=instruction.commands hash=<sha256> -->
...generated content...
<!-- aiwf:end -->
```

- The framework version is pinned in the repo config (`framework_version`).
- Secrets: the CLI never reads or writes a secret value. Templates use placeholders such as
  `[HARNESS_TOKEN]`. The adapter names the real secret.

## Flow of `aiwf render`

1. Load the framework at the pinned version.
2. Load and validate the repo config. Stop on the first error. Print the field and the fix.
3. Resolve each profile: framework profile, then the repo override. Apply the rules in
   [customization.md](../customization.md). Stop if a waiver removes G3 or G5.
4. Build the component list from the profiles, the adapters, and `.ai-workflow/local/`.
5. Render each component to memory.
6. Compare each rendered block with the file on disk:
   - Same hash: skip.
   - The disk block changed since the last render: report drift. Do not overwrite. Exit code 2.
   - Otherwise: write the new block.
7. Write the manifest. Keep `added`, `owner`, and `review_by` for existing components.
8. Print a summary: files written, files skipped, drift found.

## Errors and logging

| Error | Behavior |
| --- | --- |
| Invalid config | Stop before any write. Exit code 1. |
| Drift in a generated block | Do not write that file. Continue with other files. Exit code 2. |
| A template fails to render | Stop before any write. Exit code 1. |
| A write fails | Stop. Report the files already written. A second run completes the work. |

- Log to standard error. Use one line for each file: `wrote`, `skipped`, or `drift`.
- `--dry-run` prints the changes and writes nothing.

## Verification

1. Unit tests for config validation and profile resolution.
2. Golden-file tests: render a fixture repo. Compare the output with stored files.
3. Idempotence test: render twice. The second run writes nothing.
4. Drift test: edit a generated block. `render` reports drift and does not overwrite.
5. End-to-end: render a sample repo. Run the single-ticket profile on one sample ticket.

## Rollback

- All output is in git. To roll back, revert the commit that the render made.
- To roll back the framework, set `framework_version` to the earlier tag and run `aiwf render`.

> CAUTION: `--force` overwrites drifted blocks and loses manual edits. The CLI asks for confirmation
> before it uses `--force`.

## Assumptions

- Target repos use git and GitHub.
- Jinja2 is the template engine. A template-tool option (Copier) was not selected.
- v0 has one harness adapter (see [adapters/](../adapters/contract.md)). Other harness adapters come later.
