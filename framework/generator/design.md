# Generator design

Status: design only (v0). No code yet.

## Goal

Write the files for a target repo from the framework, one harness adapter, one spec-tool adapter,
and the repo config. The same inputs MUST give the same files.

| Item | Value |
| --- | --- |
| Trigger | A person runs the CLI, or the `cornerstone-setup` skill runs it |
| Inputs | `framework/` (this repo, at a version tag), `.cornerstone/config.yaml`, profile overrides |
| Outputs | Instruction file, skills, roles, hooks, CI workflows, check scripts, templates, `.cornerstone/manifest.yaml` |
| Owner | brawblan |

Reason for a CLI plus a skill: a deterministic CLI gives repeatable files, and generated free-text
context files did not help agents (dossier A3, A4). The skill only collects facts and fills the
repo config.

## Parts

| Part | Job |
| --- | --- |
| `stone` CLI (Python 3) | Read the inputs, validate them, render the templates, write the files and the manifest. |
| `cornerstone-setup` skill | The entry skill. Run `project-setup` as the Shape step (constitution and `AGENTS.md`). Then survey the repo, interview the human for missing facts, write `.cornerstone/config.yaml`, and run the CLI. `project-setup` stays usable alone. |
| Templates | Jinja2 files in `framework/adapters/<adapter>/templates/`. |

## Commands

| Command | Does |
| --- | --- |
| `stone init` | Make `.cornerstone/config.yaml` with `TODO(<owner>)` values. |
| `stone render` | Write all files from the inputs. Safe to run again. |
| `stone check` | Validate the config, the profiles, and the manifest. Report drift between files and templates. |
| `stone review` | List the components past `review_by`. Exit code 1 if there are any. |
| `stone eval <component-id>` | Run the component's eval with and without the component. (Later version.) |

## Constraints

- Python 3.11 or later. Type hints. No network access during `render`.
- Idempotent: a second `render` with the same inputs changes no file.
- Generated content sits between markers. Content outside the markers belongs to the human.

```text
<!-- stone:begin id=instruction.commands hash=<sha256> -->
...generated content...
<!-- stone:end -->
```

- The framework version is pinned in the repo config (`framework_version`).
- Secrets: the CLI never reads or writes a secret value. Templates use placeholders such as
  `[HARNESS_TOKEN]`. The adapter names the real secret.

## Flow of `stone render`

1. Load the framework at the pinned version.
2. Load and validate the repo config. Stop on the first error. Print the field and the fix.
3. Resolve each profile: framework profile, then the repo override. Apply the rules in
   [customization.md](../customization.md). Stop if a waiver removes G3 or G5.
4. Resolve the mode for each profile (repo config, then profile override, then profile default).
   The ticket mode applies at run time, not at render time. So render the components for each mode
   in `modes_allowed` in the repo config. The default is all three modes.
5. Build the component list from the profiles, the modes, the adapters, and `.cornerstone/local/`.
6. Render each component to memory.
7. Compare each rendered block with the file on disk:
   - Same hash: skip.
   - The disk block changed since the last render: report drift. Do not overwrite. Exit code 2.
   - Otherwise: write the new block.
8. Write the manifest. Keep `added`, `owner`, and `review_by` for existing components.
9. Print a summary: files written, files skipped, drift found.

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
- To roll back the framework, set `framework_version` to the earlier tag and run `stone render`.

> CAUTION: `--force` overwrites drifted blocks and loses manual edits. The CLI asks for confirmation
> before it uses `--force`.

## Assumptions

- Target repos use git and GitHub.
- Jinja2 is the template engine. A template-tool option (Copier) was not selected.
- v0 has one harness adapter (see [adapters/](../adapters/contract.md)). Other harness adapters come later.
