# Component lifecycle

Each generated component (rule, skill, role, hook, check, CI job) has a lifecycle. The goal is to
remove components that no longer help the current model (P5).

## Manifest

The generator writes a manifest in the target repo. Default path: `.cornerstone/manifest.yaml`.

```yaml
framework_version: 0.1.0
components:
  - id: role.tester
    kind: role                  # rule | skill | role | hook | check | ci-job
    purpose: Write independent tests from the ticket and the diff.
    principle: [P2]
    source: framework           # framework | repo
    owner: <github-username>
    eval: evals/role-tester/    # empty only for checks (a check is its own test)
    models_tested: [<model-id>]
    added: 2026-10-17
    review_by: 2027-04-17       # added + 6 months
    why_not_a_check: Test design needs judgment.   # required for kind: rule | skill
    files: [<generated file paths>]
    hash: <sha256 of the generated content>
```

## Review triggers

| Trigger | Action |
| --- | --- |
| `review_by` date passes | Review the component (procedure below). |
| The model changes for a role | Run all evals for components that the role uses. |
| A vendor releases a new model, or a model profile changes | Run the [adapter-refresh](profiles/adapter-refresh.md) profile. |
| The harness version changes in a major way | Run all evals. |
| An eval fails 2 runs in a row | Review the component. |
| A human edits a generated file | The generator reports drift. The owner decides: keep the edit in the repo config, or discard it. |

## Review procedure

1. Run the component's eval with the component and without it.
2. Compare the results. Use the same tasks and the same model.
3. If the component does not improve the result, delete it.
4. If the component improves the result, set `review_by` to 6 months later.
5. If the component is a rule or a skill, read `why_not_a_check` again. If a check can now do the
   job, replace the component with a check.
6. Record the result in the manifest and in the PR that changes it.

> CAUTION: Do not delete a check only because its eval is missing. A check is its own test. Review a
> check for false positives and for cost instead.

## Eval design

| Item | Rule | Source |
| --- | --- | --- |
| Size | Start with 3 to 5 scenarios for each component. Grow to 20–50 tasks for each profile from real failures. | dossier G4, G6 |
| Baseline | Always measure without the component first. | G4 |
| Grader | Use a code-based grader first. Use a model grader only for judgment, and calibrate it against a human. | G6 |
| Consistency | Report pass^k (all k trials pass) for roles in CI. | G7 |
| Cost | Record tokens and time for each run. A component that adds cost with no gain fails. | G3 |
| Transcripts | Read some transcripts at each review. A score alone can hide a bad grader. | G6 |
| Models | Run the eval on each model that the repo uses for that role. | G5 |

Default eval folder: `evals/<component-id>/` with `scenarios.yaml` and a grader script.

## Metrics for each profile

Collect these for each merged item. Record the mode and the stage drivers with each item. Compare
the metrics before and after a workflow change, and between modes for the same profile.

| Metric | Meaning |
| --- | --- |
| Lead time | Time from G1 to merge |
| Human time | Time a human spends at gates |
| Loops | Number of Build–Verify loops |
| Rework | Follow-up fixes within 30 days |
| Escaped defects | Bugs found after merge that the item caused |
| Cost | Tokens or usage for each item |
| PR size | Lines changed |
