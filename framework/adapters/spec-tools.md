# Adapters: spec tools

A spec tool stores the plan artifact. The default is plain Markdown. OpenSpec is optional. The core
works with either.

## Plain (default)

| Concept | Target |
| --- | --- |
| Plan artifact | `docs/plans/<id>.md` with the six sections |
| Decision log | `docs/plans/<id>.decisions.md` |
| Progress file | `docs/plans/<id>.progress.json` |
| G2 approval | A human approves the PR that adds the plan, or adds the `plan-approved` label |
| Validate | A script checks that the six sections exist and are not empty |

Progress file format:

```json
{
  "id": "issue-123-export-csv",
  "tasks": [
    {
      "id": "t1",
      "description": "Add the export button to the report page.",
      "test_steps": ["Open a report.", "Select Export.", "A CSV file downloads."],
      "passes": false
    }
  ]
}
```

## OpenSpec

| Concept | Target | Notes |
| --- | --- | --- |
| Plan artifact | `openspec/changes/<id>/` (`proposal.md`, `design.md`, spec deltas, `tasks.md`) | Understanding and scope are in `proposal.md`. Approach and files are in `design.md`. AC coverage is in the spec scenarios. |
| Decision log | `openspec/changes/<id>/decisions.md` | `[TO CONFIRM]` that OpenSpec keeps extra files when it archives a change. |
| Progress file | `tasks.md` checkboxes, plus `progress.json` for the pass state | JSON is safer for the pass state (dossier E4). |
| G2 approval | A human approves the docs PR from `sdd-plan` | |
| Validate | `openspec validate <id> --strict` | |

The `sdd-plan` and `sdd-build` skills in this repo are the current OpenSpec implementation.
