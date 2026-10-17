---
id: adapter-refresh
name: Adapter refresh
version: 0.1.0
purpose: After a vendor release, update the model profile to the new guidance. Keep only the changes that evals support.
triggers: [schedule:weekly, command]
stages: [intake, plan, build, test, verify, review, deliver, learn]
roles: [investigator, implementer, tester, reviewer]
plan_form: decision-log
mode: agent-centric
gates:
  G1: skip
  G2: skip
  G3: required
  G4: human
  G5: if-needed
checks: [K1, K6, K7, K13, K14, K17]
limits:
  pr_changed_lines: 600
outputs: [pr]
---

# Adapter refresh

This profile runs on the framework repo, not on a target repo. It keeps the adapters and the model
profiles in line with each vendor's current models and guidance.

## Use when

- A vendor releases a new model or a new model version.
- A vendor changes its published best practices for prompts, skills, tools, or its harness.
- The lifecycle review finds a model profile past its `reviewed` date plus 6 months.

## Do not use when

- Only the harness software changed (a new CLI flag, a new file path). Edit the harness adapter in a
  normal [single-ticket](single-ticket.md) run.

## Flow

1. **Watch (Intake).** Start the investigator in a fresh session. It reads each source URL in each
   active model profile, and each vendor's release notes. It compares them with the `sources.read`
   dates.
2. If nothing changed, stop. Write one line in the run log.
3. **Plan.** The investigator writes the guidance diff: each new, changed, or removed idiom, with the
   source and a quote of 2 sentences or fewer.
4. **Build.** Start the implementer in a fresh session. It writes a new model profile with
   `status: proposed`, or updates the current one. It does not change the core framework files.
5. **Test.** Start the tester in a fresh session. For each new or changed idiom, it runs the evals of
   the components in `affects`:
   1. With the current adapter and the current model (baseline).
   2. With the current adapter and the new model.
   3. With the changed adapter and the new model.
6. Keep an idiom only if run 3 is better than run 2, or equal at a lower cost. Remove the others from
   the proposal. Record the results in the decision log.
7. **Verify.** Run `stone check` and `stone render --dry-run` on a sample repo (G3).
8. **Review.** Start the reviewer in a fresh session. It checks each kept idiom against its source and
   its eval result.
9. Open the PR with the guidance diff, the eval table, and the decision log. A human approves it (G4).
10. **Learn.** After the merge, tag a new framework version. Each target repo updates
    `framework_version` and runs `stone render`.

> WARNING: The investigator reads web pages that the framework does not control. Give it no secrets
> and no write access other than the PR branch (P9, lethal trifecta).

## Switching vendors

All vendor adapters and model profiles stay in the repo. A target repo selects one in its config:
`harness` and `model_profile`. To switch, change those two lines and run `stone render`. To compare
vendors, run the same evals with each profile.

## Exit criteria

- Each kept idiom has a source, a read date, and an eval result.
- No core framework file changed (P12).
- A human approved the PR.

## Failure handling

| Failure | Action |
| --- | --- |
| A source page is not reachable | Keep the old idiom. Record the failure. Retry on the next run. |
| No eval exists for an affected component | Keep the idiom as `proposed`. Open a ticket to write the eval (P5). |
| The new model is worse on the baseline evals | Do not change `role_models`. Report it in the PR. |

## Evidence

Dossier IDs: G4, G5, G6, G7, H5, F4.
