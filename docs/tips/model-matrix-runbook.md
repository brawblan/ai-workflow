# Runbook: run the 3-trial model matrix (issue #305)

Result: this runbook gives the commands for you to run the matrix on your own Mac. It runs the six
role evals on four OpenCode Go models, with 3 trials for each cell. Then it reads the picks and
writes the `recommendations` block. PR #335 (D120, the pick rule) is merged into `dev`, so use `dev`.

Do not run the matrix in CI or in an agent session. It uses your OpenCode Go plan key and costs
money.

## What it runs

| Item | Value |
| --- | --- |
| Roles | shaper (S1 to S5), planner (P1 to P5), implementer (I1 to I3), tester (T1 to T4), reviewer (R1 to R4), investigator (V1 to V3) |
| Models | `opencode-go/beam-free` (the baseline: the role model of `opencode-default`), `opencode-go/glm-5.3-flash`, `opencode-go/deepseek-v4.1-flash`, `opencode-go/kimi-k3.1-pro` |
| Variant | `--variant with` only. The picks use the runs of the variants that are not `without`. This halves the cost. |
| Trials | `--trials 3` (the minimum for a pick, D120) |
| Runs | 24 scenarios x 3 trials x 4 models = 288 runs |

## Expected cost (estimate)

| Model | Basis | Estimate |
| --- | --- | --- |
| `glm-5.3-flash` | The 1.7.0 pilot: $0.0026 to $0.0040 for each run with the role. 72 runs. | about $0.30 |
| `deepseek-v4.1-flash` | Same basis, off-peak rate. A peak run costs 2 times more. | about $0.30 |
| `kimi-k3.1-pro` | Rates are 13 to 20 times the flash rates. The pilot put a full #304 matrix at 21% of the $15 Go cap. | $3 to $6 |
| `beam-free` | No rates in `rates.yaml`. The cost shows "—". | unknown |
| Total | | about $4 to $7 |

The numbers are estimates from published rates. OpenCode reports a cost of 0 on the Go plan. The
Kimi cap on Go is $15 each month. Check your usage page before and after.

## Before you start

1. DeepSeek peak windows: 01:00 to 04:00 and 06:00 to 10:00 UTC, Monday to Friday. Start the run
   outside them. `stone eval` also warns if a model is in a peak window. If it warns, stop and
   start later. Weekends are always off-peak.
2. Add rates for `beam-free` to `framework/adapters/opencode/rates.yaml` if you know them (zero if
   it is free). Without rates, its cost is "—". Then no model can get a quality pick, because the
   rule needs the baseline cost. Do this in its own commit. A baseline with a cost of 0 has the
   same effect on quality: see "Read the picks".
3. Make a private venv and a fresh worktree from `dev`. The Mac has no `python` command (see the
   eval notes), so put the venv first on PATH.

```bash
cd /Users/brandonblankenstein/Repos/ai-workflow && git fetch origin && git worktree add -b chore/model-matrix ../ai-workflow-matrix origin/dev
```

```bash
cd /Users/brandonblankenstein/Repos/ai-workflow-matrix && python3 -m venv /tmp/v-matrix && /tmp/v-matrix/bin/pip install -e ./stone
```

```bash
cd /Users/brandonblankenstein/Repos/ai-workflow-matrix && export PATH=/tmp/v-matrix/bin:$PATH && python -c "import stone; print(stone.__file__)" && opencode --version && date -u
```

The path in the second line must be inside `ai-workflow-matrix`. The adapter was tested on OpenCode
2.2.6. If `opencode auth login` is not done, run it first. Keep `~/.config/opencode` empty.

## Run

Run each role as one command. Put this in each command: `cd`, the PATH, `--variant with`,
`--trials 3`, `--keep`, `--budget`, and the four models. OpenCode has no cost limit, so `--budget`
has no effect and the command says so. Keep it, so a later harness change stays safe.

```bash
cd /Users/brandonblankenstein/Repos/ai-workflow-matrix && export PATH=/tmp/v-matrix/bin:$PATH && for role in shaper planner implementer tester reviewer investigator; do stone eval role.$role --variant with --trials 3 --budget 1 --keep --model opencode:opencode-go/beam-free --model opencode:opencode-go/glm-5.3-flash --model opencode:opencode-go/deepseek-v4.1-flash --model opencode:opencode-go/kimi-k3.1-pro || break; done
```

- The loop stops at the first failing command. A usage-limit stop shows as a harness error on each
  later run. If that happens, wait for the reset and run only the roles that are left.
- Each role writes `.cornerstone/eval-runs/<stamp>-role-<role>/runs.jsonl` and one result file for
  each model in `evals/results/`.
- A role takes a few minutes for each model. Expect 1 to 3 hours in all. Use `caffeinate -i` in
  front of `stone eval` to keep the Mac awake if the loop is long.

## Read the picks

Join the six `runs.jsonl` files and print the matrix with the picks:

```bash
cd /Users/brandonblankenstein/Repos/ai-workflow-matrix && export PATH=/tmp/v-matrix/bin:$PATH && args=$(for f in .cornerstone/eval-runs/*-role-*/runs.jsonl; do printf -- '--summary %s ' "$f"; done) && stone eval $args --by model --picks framework/adapters/opencode/models/opencode-default.yaml | tee /tmp/matrix-picks.txt
```

- Use only the folders of this matrix. If older folders exist, name the six files yourself.
- Add `--json` for the data of each row.
- The rule (D120): economy is the lowest cost for each passing run. The pass rate must be within 1
  standard error of the difference from the baseline. Quality is the highest pass rate, if the cost
  for each passing run is not above the limit. The limit is `quality_cost_ceiling` of the model
  profile (D125), in USD for each passing run. If the profile has no ceiling, the limit is the
  baseline cost. A free baseline (cost 0) needs a ceiling: the owner sets the value from the
  matrix results, then runs the same command again. If no model meets a rule, the pick is the
  baseline.
- Read each failed run of a `with` variant before you trust a low pass rate. In past evals, most
  failures were grader or fixture errors. If a grader is wrong, fix it, then grade the kept
  workspaces again with `evals.grade`.

## Write the `recommendations` block

For each role, add an economy pick and a quality pick to
`framework/adapters/opencode/models/opencode-default.yaml`. Use the values of the picks table:

```yaml
recommendations:
  tester:
    economy:
      model: opencode-go/glm-5.3-flash
      pass_rate: 1.0
      cost_per_pass: 0.0037
      trials: 3
      eval_version: "<short SHA of dev that ran the eval>"
      date: 2026-11-20
      review: 2027-05-20
    quality:
      model: opencode-go/deepseek-v4.1-flash
      # same six keys
```

- Each role needs both keys. `cost_per_pass` is `null` if no rate is known.
- `review` is later than `date`. D120 sets a review about 6 months out.
- Do not change `defaults.role_models`. That is a G4 decision, and it goes in its own PR.
- Update the table in `framework/adapters/opencode.md` ("Model picks") with the same picks.
- Run `stone check`. It validates the block.

## Open the G4 PR

1. Branch from `dev` as `feature/model-picks-data`. Keep the result files and the picks block in
   one commit with `Role: generator` only if `stone render` made them. A hand edit of the profile
   and the table is a normal commit.
2. A change of `defaults.role_models` is a separate PR. Show a WARNING in it and get your approval.
3. Run the checks before the push:

```bash
cd /Users/brandonblankenstein/Repos/ai-workflow-matrix && export PATH=/tmp/v-matrix/bin:$PATH && python stone/tests/run_parallel.py -q && stone check && stone check-writing --diff origin/dev && stone check-rules --base origin/dev
```

4. Write the PR body with the nine sections of the `ticket-delivery` skill. Put the picks table and
   the cost in it. Test the body with K17 and K14 before `gh pr create`.
5. Open the PR into `dev`. Link #305 and #301. "Closes" in a PR into `dev` does not fire, so close
   #305 by hand after the release.
6. Post the table in the tracking issue #301.

## Limits

- The evals come from one harness, and the samples are small (3 trials).
- The scenarios are near a ceiling with the role, so the pass rates may not rank the models.
- The cost is an estimate from the published rates, not the billed cost.
