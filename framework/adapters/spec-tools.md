# Adapters: spec tools

A spec tool stores the plan artifact. The only adapter is plain Markdown. To add a spec tool, map
it to the contract in [contract.md](contract.md#what-a-spec-tool-adapter-must-provide) (D18).

## Plain (default)

| Concept | Target |
| --- | --- |
| Plan artifact | `docs/plans/<id>.md` with the six sections |
| Decision log | `docs/plans/<id>.decisions.md` |
| Progress file | `docs/plans/<id>.progress.json` |
| Spec delta | `docs/plans/<id>.spec.md` |
| Spec | `docs/specs/<capability>.md`, written by `stone spec apply` |
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
