# Checks

A check is a program that returns pass or fail with no model judgment (P1, P6). Gate G3 runs the
checks for the profile in CI. Each check SHOULD also run on the developer's machine first.

## Check catalog

| ID | Check | Fails when | Baseline | Example tools |
| --- | --- | --- | --- | --- |
| K1 | Format and lint | The code breaks a style or lint rule. | yes | ruff, eslint, prettier |
| K2 | Type check | The code has a type error. | yes, if the language has types | mypy, pyright, tsc |
| K3 | Unit tests | A unit test fails. | yes | pytest, vitest |
| K4 | Integration tests | Components fail to work together. | by profile | pytest, testcontainers |
| K5 | Acceptance tests | Behavior does not match the acceptance criteria. | by profile | playwright, pytest |
| K6 | Protected paths | An implementer commit changes a test, check, CI, or check-config path. Each commit has a `Role:` trailer. A commit with no trailer counts as an implementer commit. Human and agent commits follow the same rule. With `adoption: opt-in`, a commit with `Actor: human` and no `Role:` does not count (D58). | yes | script in the generator output |
| K7 | Change size | The diff is over the size limit of the PR profile, and the PR has no waiver. The PR body names the profile on a `Profile: <id>` line. With no such line, the smallest limit of the selected profiles applies. A waiver is a Markdown heading of any level with `waiver (P10)` in its text, in any case, and text under it. Examples: `## Waiver (P10)` and `### Size waiver (P10)`. A list item is not a waiver. An empty section, `None`, or `TBD` does not count (D46). | yes | script in the generator output |
| K8 | Architecture fitness | A dependency breaks a layer, boundary, or cycle rule. | by profile | import-linter, dependency-cruiser, ArchUnit |
| K9 | Complexity caps | A function is over the cyclomatic, cognitive, nesting, parameter, or length limit. | yes | ruff (mccabe), radon, eslint complexity |
| K10 | Mutation score | Too many mutants survive in the changed code. | by profile | mutmut, Stryker (incremental), pitest |
| K11 | Property and fuzz tests | A generated input breaks a stated rule or crashes the code. | by profile | hypothesis, fast-check, atheris |
| K12 | Differential tests | Two independent implementations give different outputs. | by profile | custom harness, `git bisect run` |
| K13 | Secret scan | A secret or token is in the diff. | yes | gitleaks, platform secret scanning |
| K14 | PR evidence | A required PR section (evidence, decision log, review findings, confidence) is missing or empty. | yes | `stone check-evidence`. Blocks in the G3 workflow (D49). |
| K15 | Instruction size | The instruction file is over the line limit (`instruction_file_max_lines` in the model profile). The adapter names the instruction file. | yes | script in the generator output. Blocks in the G3 workflow (D52). |
| K16 | No merge to main | A spike branch targets the main or the integration branch. | spike profile | branch protection, script |
| K17 | Writing standard | New or changed human-facing text breaks a measurable rule. See [writing.md](writing.md#what-k17-tests). | yes, also for profiles that only write reports | script in the generator output |
| K18 | Persona references | The personas file breaks the format in [workflow-model.md](workflow-model.md#personas), or a plan names a persona or a job story that the file does not have. | by profile | `stone check`. An error since 2026-10-21 (D53). A `Personas:` label in the middle of a line gives a warning, and it can become an error only in a major release (D77). |
| K19 | Spec replay | A spec delta breaks the format in [workflow-model.md](workflow-model.md#specs). Two applied deltas have the same `apply_order`. A spec is not the same as a replay of the applied deltas. | by profile | `stone check`. An error since 2026-10-21 (D53). |
| K20 | Specialist findings | A `blocks: true` specialist that matches the PR has a finding with severity high, or has no report. A PR that a specialist matches has no `Ticket: <id>` line. A heading with `waiver (K20)` and text under it passes, with a notice (D66). | yes, if the repo config has `specialists` | `stone check-specialists`. Blocks since 1.4.0 (D80). |
| K21 | Definition of Ready | A ticket has no field that its profile needs, or the field is empty or vague. The fields come from the table in [workflow-model.md](workflow-model.md#definition-of-ready-default). A `Field: value` line under `## Definition of Ready`, or a heading with the field name, counts (D82). | G1, if the profile has `G1: check` | `stone check-ready`. A warning in 1.x. |

"Baseline" checks run in each profile that changes code. A profile adds the "by profile" checks.
K4, K5, K8, K10, K11, and K12 run a repo tool. The repo config gives the command for each one. See
[customization.md](customization.md#commands-for-the-by-profile-checks).

## K16 and the spike branch

K16 is the control that stops spike code from merging. The protected-path hook trusts the branch
name (D25). On a branch with the `spike/` prefix, the investigator can write any file except the
harness and Cornerstone files. K16 fails a pull request from that branch into the main branch or
the integration branch (D33). Thus spike code cannot get to the main branch through the integration
branch.

- `stone render` writes K16 as a CI job for each profile that lists K16 (D30).
- Render needs `branches.main` and `branches.integration`. The two can be the same branch.
- The job runs from the base branch, so a commit on the spike branch cannot change or remove it.
- K16 blocks from the start. A warning does not stop a merge, and D25 depends on K16.
- Make the K16 job a required status check on the main branch and on the integration branch.
- K16 reads only the head branch name. It does not find spike commits on a branch with a different
  name (D33). Examples: a renamed spike branch, or a spike branch merged into a feature branch. Gate
  G4 is then the control. Do not merge a spike branch into a different branch.

## Choose a test technique by what you can state

| You can state | Use | Check |
| --- | --- | --- |
| An example input and its output | Unit test | K3 |
| A rule that holds for all inputs | Property-based test | K11 |
| The format of valid input | Structure-aware fuzzing | K11 |
| A second, independent implementation | Differential test | K12 |
| How the output changes when the input changes | Metamorphic test | K11 |
| A structural rule about the code | Fitness function | K8 |

Source: dossier B14, C3.

## Rules for checks

1. A check MUST be read-only for the implementer. Only a human changes a check. K6 enforces this for
   the implementer only: it fails an implementer commit that changes a protected path. No check
   sees the same change by the tester, the planner, the investigator, or the reviewer. For those
   roles, the file hook limits the file tools. The reviewer and gate G4 are the control (D39, D51).
2. A check failure message SHOULD say how to fix the failure. Agents act on the message (dossier C7).
3. A new check starts as a warning for 2 weeks. Then it becomes blocking. The repo config can
   change this period. A check may block early if a replay shows no false positive (D45).
   Exception: K16 blocks from the start, because a role permission depends on it (D30).
4. When an agent makes the same mistake twice, add a check if the rule can be stated. Add an
   instruction only if it cannot (P6).
5. Limits (size, complexity, mutation score) are in the repo config, not in the check code.
