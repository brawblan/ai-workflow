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
| K6 | Protected paths | An implementer commit changes a test, check, CI, or check-config path. Each commit has a `Role:` trailer. A commit with no trailer counts as an implementer commit. Human and agent commits follow the same rule. | yes | script in the generator output |
| K7 | Change size | The diff is over the profile's size limit and has no waiver. | yes | script in the generator output |
| K8 | Architecture fitness | A dependency breaks a layer, boundary, or cycle rule. | by profile | import-linter, dependency-cruiser, ArchUnit |
| K9 | Complexity caps | A function is over the cyclomatic, cognitive, nesting, parameter, or length limit. | yes | ruff (mccabe), radon, eslint complexity |
| K10 | Mutation score | Too many mutants survive in the changed code. | by profile | mutmut, Stryker (incremental), pitest |
| K11 | Property and fuzz tests | A generated input breaks a stated rule or crashes the code. | by profile | hypothesis, fast-check, atheris |
| K12 | Differential tests | Two independent implementations give different outputs. | by profile | custom harness, `git bisect run` |
| K13 | Secret scan | A secret or token is in the diff. | yes | gitleaks, platform secret scanning |
| K14 | PR evidence | A required PR section (evidence, decision log, confidence) is empty. | yes | script in the generator output |
| K15 | Instruction size | The instruction file is over the line limit. | yes | script in the generator output |
| K16 | No merge to main | A branch from a spike targets the main branch. | spike profile | branch protection, script |
| K17 | Writing standard | New or changed human-facing text breaks a measurable rule. See [writing.md](writing.md#what-k17-tests). | yes, also for profiles that only write reports | script in the generator output |

"Baseline" checks run in each profile that changes code. A profile adds the "by profile" checks.

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

1. A check MUST be read-only for the implementer and the tester. Only a human changes a check (K6).
2. A check failure message SHOULD say how to fix the failure. Agents act on the message (dossier C7).
3. A new check starts as a warning for 2 weeks. Then it becomes blocking. The repo config can
   change this period.
4. When an agent makes the same mistake twice, add a check if the rule can be stated. Add an
   instruction only if it cannot (P6).
5. Limits (size, complexity, mutation score) are in the repo config, not in the check code.
