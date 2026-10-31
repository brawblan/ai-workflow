---
id: dependency-upgrade
name: Dependency upgrade
version: 0.1.0
purpose: Upgrade one dependency, fix the breaks, and prove that behavior did not change.
triggers: [ci:dependency-pr, schedule:weekly, command]
stages: [intake, build, test, verify, review, deliver, learn]
roles: [investigator, implementer, tester, reviewer]
plan_form: decision-log
mode: agent-centric
gates:
  G1: skip
  G2: skip
  G3: required
  G4: human
  G5: if-needed
checks: [K1, K2, K3, K4, K5, K6, K7, K9, K13, K14, K17, K20, K22, K23, K24]
limits:
  pr_changed_lines: 300
outputs: [pr]
---

# Dependency upgrade

## Use when

- A dependency update tool opens a PR, or a scheduled scan finds an old version.
- The upgrade is one dependency (or one group that must move together).

## Do not use when

- The upgrade needs a large code change. Use [refactor-migration](refactor-migration.md).

## Flow

1. Start the investigator in a fresh session. It reads the release notes and the changelog between
   the two versions. It lists the breaking changes that apply to this repo, with file paths.
2. Update the version and the lock file.
3. Run the checks (G3).
4. If a check fails, start the implementer in a fresh session with the investigator's list and the
   check output. It fixes the breaks.
5. If the dependency has a behavior change that the tests do not cover, start the tester. It adds
   tests for the behavior that the repo uses.
6. Start the reviewer in a fresh session. It checks the diff against the breaking-change list.
7. Open the PR with the breaking-change list and the decision log. A human approves it (G4).

## Exit criteria

- All checks pass on the new version.
- Each breaking change on the list is fixed or marked "does not apply", with a reason.

## Failure handling

| Failure | Action |
| --- | --- |
| The upgrade needs more than the size limit | Stop. Open a refactor-migration ticket. |
| The new version has a known security issue | Stop. Report it. Do not merge. |

## Patch-version waiver

By default, a human approves each upgrade (G4). A repo MAY add a waiver to skip G4 when all of these
conditions are true:

1. The upgrade changes only the patch version (for example 2.4.1 to 2.4.3).
2. All checks pass.
3. No security notice applies to the new version.
4. The investigator found no breaking change.

Minor and major versions always need G4. Put the waiver in the profile override
`.cornerstone/profiles/dependency-upgrade.yaml`. `stone check` validates it (D84). The waiver is a
record: the human reads it and decides at G4. Form:

```yaml
waivers:
  - gate: G4
    scope: patch-versions
    reason: High volume, low risk, full check coverage.
    owner: <github-username>
    until: <date>
```

## Evidence

Dossier IDs: H3, H4, E13.
