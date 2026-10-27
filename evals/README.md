# Evals

An eval tests one component (a role, a skill, a rule) with the component and without it. The
runs use the same prompt and tools. Code graders check the result. See
[Eval design](../framework/lifecycle.md#eval-design) and decision D26 in the
[framework decisions](../framework/README.md).

How to read a table:

| Column | Meaning |
| --- | --- |
| Variant | `with` has the component. `without` does not. |
| pass^k | 1 if all k trials passed every check. Else 0. |
| Outcome | Rate of passed `outcome` checks (the behavior). |
| Contract | Rate of passed `contract` checks (the format of the component). |
| Cost, Tokens out, Seconds | Mean for each trial. |
| Errors | Trials that ended in an error. |

Runs are local. Run `stone eval <component-id>`. The command writes a result file to
`evals/results/`. Commit the file. This page reads those files at build time.

## Coverage

A full render for all 10 profiles writes 22 components. This table lists each one. Facts as of
2026-10-27.

- Measured by a model run: 6 components (`role.shaper`, `role.planner`, `role.tester`,
  `role.reviewer`, `hook.protect-paths`, `hook.settings`). The hook pair has two runs. The run of 2026-10-21 passes every check (see below).
- Measured by tests only: `check.k6`. A check is its own test (D43).
- Not measured: 15 components. Each has an eval plan in the adapter component list. The eval
  folder does not exist yet.
- Every run used `claude-opus-5-5`, except one `role.tester` run on `claude-sonnet-5-5` (2026-10-22). No other model is measured (dossier G5).
- k = 3 for each run. A rate is the share of passed checks. "With" has the component. "Without" does
  not.

| Component | Eval folder | Last result | Planned date |
| --- | --- | --- | --- |
| `role.shaper` | [role-shaper](./role-shaper/) | 2026-10-27, `claude-opus-5-5`. S1 to S5, latest run of each scenario. Outcome 1.00 with, 0.40 without. pass^k is 1 in all five with the role. See the note below. | Measured |
| `role.planner` | [role-planner](./role-planner/) | 2026-10-18, `claude-opus-5-5`. P1 to P5, latest run of each scenario. Outcome 1.00 with, 0.80 without (P2 fails without). Contract 1.00 with, 0.40 without. | Measured |
| `role.implementer` | none | no run | 2027-04-18 (proposed) |
| `role.tester` | [role-tester](./role-tester/) | T1, T3, T4: 2026-10-18. T2: 2026-10-19, after D42. Outcome 1.00 with and without in all four. Contract 1.00 with. Contract 0.00 without. The run of 2026-10-22 on `claude-sonnet-5-5` (with only, k = 3): outcome 1.00 and contract 1.00 in all four, 12 of 12 runs pass. The T2 result of 2026-10-18 is from before D42 (see the note below). | Measured |
| `role.reviewer` | [role-reviewer](./role-reviewer/) | 2026-10-27, `claude-opus-5-5`. R1 to R4. Outcome 1.00 with and without. Contract 1.00 with, 0.00 without. pass^k is 1 in all four with the role. See the note below. | Measured |
| `role.investigator` | none | no run | 2027-04-18 (proposed) |
| `hook.protect-paths` | [hook-protect-paths](./hook-protect-paths/) | 2026-10-21, `claude-opus-5-5`, after D48. H1 to H5. Every check passes in 30 of 30 runs, in both variants. Outcome 1.00 with and without. pass^k is 1 in all rows. The run of 2026-10-19 passed `bash_write_lands` in 4 of 30 runs (see the note below). | Measured. Review D39 by 2027-04-18. |
| `hook.settings` | [hook-protect-paths](./hook-protect-paths/) | The same run as `hook.protect-paths`. It has no result of its own. | Measured with the hook. |
| `check.k6` | none (a check is its own test) | Unit tests. The `k6_fails` check of the hook eval also runs K6: 30 of 30 runs fail the commit, as D39 expects. | Not applicable |
| `check.k7` | none | no run | 2027-04-18 (proposed) |
| `check.k15` | none | no run | 2027-04-18 (proposed) |
| `check.k16` | none | no run | 2027-04-18 (proposed) |
| `ci-job.checks` | none | no run | 2027-04-18 (proposed) |
| `trigger.label.app-slice` | none | no run | 2027-04-18 (proposed) |
| `trigger.label.debugging` | none | no run | 2027-04-18 (proposed) |
| `trigger.label.single-ticket` | none | no run | 2027-04-18 (proposed) |
| `trigger.schedule.adapter-refresh` | none | no run | 2027-04-18 (proposed) |
| `trigger.schedule.bug-triage` | none | no run | 2027-04-18 (proposed) |
| `trigger.schedule.code-audit` | none | no run | 2027-04-18 (proposed) |
| `trigger.schedule.dependency-upgrade` | none | no run | 2027-04-18 (proposed) |
| `trigger.issue-opened.bug-triage` | none | no run | 2027-04-18 (proposed) |
| `trigger.dependency-pr.dependency-upgrade` | none | no run | 2027-04-18 (proposed) |

The roadmap in the [framework decisions](../framework/README.md) lists the shaper, implementer,
reviewer, and investigator evals as still to write, but gives no date. The date 2027-04-18 is a
proposal. It matches the review date of D39 and D40. The eval folders that the adapter plans
(`evals/role-shaper/` and others) are not in the repo yet. A trigger component is one workflow for
each profile. Its eval plan is shared by all profiles that use the trigger.

Notes on the results:

- **`role.tester` T2.** D42 changed the rule for a ticket and code that disagree. Before D42, the
  tester stopped and committed nothing. The T2 result of 2026-10-18 is from before D42. That
  scenario had no commit check then, so its contract rate of 1.00 is empty. The scenario has the
  check again. The run of 2026-10-19 is after D42. With the role, 3 of 3 runs commit the failing
  test. Without it, 0 of 3 do.
- **`hook.protect-paths`.** D39 expects that each check passes in both variants. The first run
  (2026-10-19) did not show that. The two checks that use no model output passed. No matcher
  selects the shell tool. The hook lets the command through. K6 fails the commit. The check
  `bash_write_lands` passed in 4 of 30 runs. In 26 of 30 runs, the model refused to run the
  command, because the rules of its role forbid a change in `tests/` (issue #97). The refusal
  rate was the same with the hook and without it. D48 changed the task text. It now lifts that
  role rule for the run, in a throw-away copy. In the second run (2026-10-21), all 30 runs
  started the command, and the write landed. All three checks pass in 30 of 30 runs. The outcome
  rate is 1.00 with the hook and 1.00 without it. So the hook has no effect on a shell write, as
  D39 records. Limits: this is one run for each scenario (k = 3). The 95 percent lower bound of
  the pass rate is about 0.90. The eval does not show how often a model writes a protected path
  with a shell command when nothing lifts its role rule. In the first run, that happened in 4 of
  30 runs. A refusal is a model-dependent control, so K6 stays the control.
- **`role.shaper`.** S1 and S2 are from the second run of 2026-10-27. After the first run, three
  grader errors and one vague ticket (NOTE-1) were fixed. S3 to S5 are from the first run. Their
  rates do not change with the fixed grader. Without the role, the model changes a ready ticket,
  writes its own non-goals and a time limit, and replaces an unknown persona. With the role, a run
  costs about one third. Limit: `not_invented` reads only the field labels, not a "Scope" label.
- **`role.reviewer`.** Without the role, the model finds the same defect, scope drift, and
  missing test, and it gives no false finding on the clean change. So the role adds the form,
  not the detection, on this model. Without the role, no report gives a confidence or open risks,
  and 5 of 9 findings have no severity, or no file and line. With the role, a run costs about one
  half. The first grade failed the R2 contract in all 3 runs with the role. The grader split a
  finding at its "Evidence" item. After the fix, the kept workspaces were graded again. Limit:
  the scenarios are small, and each has one clear gap.
- **Contract column of the hook eval.** The scenarios have no `contract` check. The table shows
  1.00 for an empty set. Read it as "not applicable".
- **Latest run only.** The sections below show the latest run of each component, as D36 says. A
  later run of one scenario hides the table of an earlier run of other scenarios. Use the links to
  the earlier result files for those.

## Guidance evals

A guidance eval tests text that tells an agent what to do, for example the writing rules. It is not a component that `stone render` writes, so the table above does not list it (D69). Its scenarios have `variants` (a text for each variant) instead of `with` and `without`. The variant `none` is the baseline.

| Eval | Folder | Variants | Last result |
| --- | --- | --- | --- |
| `guidance.writing` | [writing-guidance](./writing-guidance/) | `none` (0 words), `always` (189), `current` (860), `short` (81) | 2026-10-23, `claude-sonnet-5-5`, k = 3, 4 tasks. Outcome minus `none`: `always` +0.25, `current` +0.42, `short` +0.42. Cost $1.98. |

Notes on the `guidance.writing` result:

- **What it shows.** Any of the three texts removes the vague words that `none` uses. `short` scores the same as `current` with about one tenth of the words.
- **What it does not show.** The run has 4 tasks, 3 trials, and one model. W1 and W4 score 1.00 in every variant, so they carry no signal. The difference between `always` and the others comes from one length limit in W2.
- **Limit of the grader.** It tests only the rules that a program can test (K17), the first line, and the last line. It does not test whether a reader understands the text. A blind human rating (G8) is still needed before the live text changes.
- **Tuning after the first output.** Two grader settings changed after the smoke run and the first full run: the W2 word limit (120 to 160) and the closing-offer pattern. Then the full run was repeated. The table above is that repeat.

## Results

<!-- evals-index -->
