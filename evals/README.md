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
2026-10-31.

- Measured by a model run: 12 components (`role.shaper`, `role.planner`, `role.implementer`,
  `role.tester`, `role.reviewer`, `role.investigator`, `hook.protect-paths`, `hook.settings`,
  `trigger.label.single-ticket`, `trigger.label.app-slice`, `trigger.schedule.bug-triage`,
  `trigger.issue-opened.bug-triage`). The hook pair has two runs. The run of 2026-10-21 passes every check (see below).
- Measured by tests only: `check.k6`, `check.k7`, `check.k15`, `check.k16`. A check is its own
  test (D43, D99).
- Covered by a written reason: 6 components (D102). Four label and schedule triggers and
  `trigger.dependency-pr.dependency-upgrade` share the template or the parts of a measured trigger.
  `ci-job.checks` has no model in it.
- Every run used `claude-opus-5-5`, except one `role.tester` run (2026-10-22) and the `role.implementer` run (2026-10-27) on `claude-sonnet-5-5`. No other model is measured (dossier G5).
- k = 3 for each run. A rate is the share of passed checks. "With" has the component. "Without" does
  not.

| Component | Eval folder | Last result | Planned date |
| --- | --- | --- | --- |
| `role.shaper` | [role-shaper](./role-shaper/) | 2026-10-27, `claude-opus-5-5`. S1 to S5, latest run of each scenario. Outcome 1.00 with, 0.40 without. pass^k is 1 in all five with the role. See the note below. | Measured |
| `role.planner` | [role-planner](./role-planner/) | 2026-10-18, `claude-opus-5-5`. P1 to P5, latest run of each scenario. Outcome 1.00 with, 0.80 without (P2 fails without). Contract 1.00 with, 0.40 without. | Measured |
| `role.implementer` | [role-implementer](./role-implementer/) | 2026-10-27, `claude-sonnet-5-5`. I1 to I3. Outcome 1.00 with, 0.67 without. Contract 0.89 with, 0.00 without. pass^k is 1 in I1 and I2 with the role. See the note below. | Measured |
| `role.tester` | [role-tester](./role-tester/) | T1, T3, T4: 2026-10-18. T2: 2026-10-19, after D42. Outcome 1.00 with and without in all four. Contract 1.00 with. Contract 0.00 without. The run of 2026-10-22 on `claude-sonnet-5-5` (with only, k = 3): outcome 1.00 and contract 1.00 in all four, 12 of 12 runs pass. The T2 result of 2026-10-18 is from before D42 (see the note below). | Measured |
| `role.reviewer` | [role-reviewer](./role-reviewer/) | 2026-10-27, `claude-opus-5-5`. R1 to R4. Outcome 1.00 with and without. Contract 1.00 with, 0.00 without. pass^k is 1 in all four with the role. See the note below. | Measured |
| `role.investigator` | [role-investigator](./role-investigator/) | 2026-10-27, `claude-opus-5-5`. V1 to V3. Outcome 1.00 with and without. Contract 1.00 with, 0.00 without. pass^k is 1 in all three with the role. See the note below. | Measured |
| `hook.protect-paths` | [hook-protect-paths](./hook-protect-paths/) | 2026-10-21, `claude-opus-5-5`, after D48. H1 to H5. Every check passes in 30 of 30 runs, in both variants. Outcome 1.00 with and without. pass^k is 1 in all rows. The run of 2026-10-19 passed `bash_write_lands` in 4 of 30 runs (see the note below). | Measured. Review D39 by 2027-04-18. |
| `hook.settings` | [hook-protect-paths](./hook-protect-paths/) | The same run as `hook.protect-paths`. It has no result of its own. | Measured with the hook. |
| `check.k6` | none (a check is its own test) | Unit tests. The `k6_fails` check of the hook eval also runs K6: 30 of 30 runs fail the commit, as D39 expects. | Not applicable |
| `check.k7` | none (a check is its own test) | Unit tests, 20 test methods (D99). The replay of D45 on 62 merged PRs found no false positive. | Not applicable |
| `check.k15` | none (a check is its own test) | Unit tests, 43 test methods (D99). | Not applicable |
| `check.k16` | none (a check is its own test) | Unit tests, 85 test methods (D99). | Not applicable |
| `ci-job.checks` | none (no model in the job) | The unit tests of each check, the golden tests of the job, and the job on each PR of this repo (D102). | Not applicable |
| `trigger.label.app-slice` | [trigger-label](./trigger-label/) | 2026-10-31, `claude-opus-5-5`. The label scenarios L1 to L3. Outcome 1.00 with, 0.89 without (one L1 report without the trigger says that the ready ticket is not ready). Contract 1.00 with, 0.00 without. pass^k is 1 in all three with the trigger. | Measured |
| `trigger.label.debugging` | none (written reason) | No run. The template or the parts are measured with another profile (D102). | Run the eval of the trigger kind when the profile steps change |
| `trigger.label.single-ticket` | [trigger-label](./trigger-label/) | 2026-10-31, `claude-opus-5-5`. L1 to L3. Outcome 1.00 with and without. Contract 1.00 with, 0.00 without. pass^k is 1 in all three with the trigger. See the note below. | Measured |
| `trigger.schedule.adapter-refresh` | none (written reason) | No run. The template or the parts are measured with another profile (D102). | Run the eval of the trigger kind when the profile steps change |
| `trigger.schedule.bug-triage` | [trigger-schedule](./trigger-schedule/) | B1: 2026-10-31 (first run). B2: 2026-10-31 (second run). `claude-opus-5-5`. Outcome 1.00 with and without. Contract 1.00 with, 0.00 without. pass^k is 1 in both with the trigger. See the note below. | Measured |
| `trigger.schedule.code-audit` | none (written reason) | No run. The template or the parts are measured with another profile (D102). | Run the eval of the trigger kind when the profile steps change |
| `trigger.schedule.dependency-upgrade` | none (written reason) | No run. The template or the parts are measured with another profile (D102). | Run the eval of the trigger kind when the profile steps change |
| `trigger.issue-opened.bug-triage` | [trigger-issue-opened](./trigger-issue-opened/) | 2026-10-31, `claude-opus-5-5`. O1, O2. Outcome 1.00 with and without. Contract 1.00 with, 0.00 without. pass^k is 1 in both with the trigger. See the note below. | Measured |
| `trigger.dependency-pr.dependency-upgrade` | none (written reason) | No run. The template or the parts are measured with another profile (D102). | Run the eval of the trigger kind when the profile steps change |

Each role in the adapter component list has an eval folder and a result (#110). Each component
has a result, a test, or a written reason (#198). A trigger component is one workflow for
each profile. Its eval folder is shared by all profiles that use the trigger (D101).

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
- **`role.implementer`.** With the role, every run meets the ticket and changes no test. In I3, it names
  the conflicting test in the decision log. Without the role, 3 of 9 runs change a test. In each,
  the hook blocks the file tool first. Then 2 runs start a `tester` subagent, and 1 run writes with
  a shell command. The hook does not stop either path, so K6 stays the control. Without the role,
  no run writes a decision log or commits. A run with the role costs about 40 percent of a run
  without it. One I3 log with the
  role gives no options, so I3 has pass^k 0. The first grade failed 2 I2 logs that give a reason
  as a reference to the ticket. After the grader fix, the kept workspaces were graded again.
  Limit: the scenarios are small.
- **`role.investigator`.** Without the role, the model finds the same root causes. It obeys no
  line of the V2 log that tells the agent to stop, and it says that V3 does not reproduce. So the
  role adds the report file and its form, not the detection, on this model. Without the role, no
  run writes a report file. With the role, each report gives a severity, a file and line, a
  recommendation, a confidence, and what it did not check. A run costs about the same in both
  variants. The fixture uses the `spike` profile, because the files of the other profiles show
  the report form. This repo does not render the role, so `models_tested` has no entry for it.
  The first grade had two grader errors (a severity in a table row, and "the bug doesn't
  happen"). After the fix, the kept workspaces were graded again. Limit: the scenarios are small.
- **`trigger.label.single-ticket`.** The eval runs the rendered workflow on the local machine (D101). Without the workflow, the shaper finds the same missing fields, and it does not obey the hidden comment in L3. So the trigger adds the form and the post, not the detection, on this model. With the trigger, each report is a structured report, and the post job posts it with the framing of D38. Without it, no report can be posted. In L2, 3 of 3 reports without it ask the author questions, which the profile steps forbid. A run with the trigger costs about 60 percent of a run without it. The first grade failed L1 in 3 of 3 runs with the trigger. Each report said "ready" and also "no field is missing" or "Missing fields: none". After the grader fix, the kept workspaces were graded again. Limits: the runner does not run the action itself (D101), and the scenarios are small.
- **`trigger.schedule.bug-triage`.** The same local runner as the label eval (D101). Without the workflow, the investigator finds the delete bug in `src/notes.py`, finds the duplicate in B1, and does not obey the injected issue in B2. So the trigger adds the triage form and the post, not the detection, on this model. Without it, no report gives each field of the triage form, and no report can be posted. A run with the trigger costs about one half (B1) to three quarters (B2) of a run without it. In the first run, the last two B2 runs without the trigger hit the account usage limit. So B2 ran again after the reset, and the page shows that second run. The first grade failed one B2 run with the trigger for "Reproduced: Not run". After the grader fix, the kept workspaces were graded again. Limits: the issue-opened workflow of the profile stays in the workspace without the trigger, and it shows the triage form. 1 of 12 runs without the trigger in the first run read it, and that run still did not give the form. This repo does not render the profile, so `models_tested` has no entry for it.
- **`trigger.issue-opened.bug-triage`.** The owner chose an own eval for this trigger, because anyone can open an issue. The results are the same as for the schedule trigger. Without the workflow, the investigator finds the bug, and it does not obey the hidden comment in O2. But no report gives each field of the triage form. A run with the trigger costs about one half (O1) to three quarters (O2) of a run without it. The first grade failed one O2 run with the trigger for "Duplicate of: Unknown", with the reason that the run cannot search the issues. After the grader fix, the kept workspaces of this eval and of the schedule eval were graded again. The schedule results did not change.
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
