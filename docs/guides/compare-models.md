# Compare models with evals

## When to use it

Use this guide to find the cheapest model that passes a role eval. `stone eval` can run more than one
model and summarize the results by model.

The OpenCode adapter supports role evals only (D112). See the
[OpenCode adapter](../../framework/adapters/opencode.md) for its support status.

## Steps

1. Prepare OpenCode with [Run on OpenCode](../../evals/README.md#run-on-opencode).
2. Run one role eval with more than one `--model`:

   ```bash
   stone eval <role> --variant with --trials 3 \
     --model <harness>:<model> --model <harness>:<model>
   ```

   Each model runs every scenario for 3 trials. The command writes one result file for each model.
3. Find `runs.jsonl` in `.cornerstone/eval-runs/<stamp>-<eval>/`.
4. Print the model summary:

   ```bash
   stone eval --summary <runs.jsonl> --by model
   ```

## How to read the matrix

- Use **Cost per pass** as the main metric. It divides the total cost by the number of passing runs.
- Compare token counts only inside one model family. Each family has its own tokenizer.
- Run 3 trials or more for each cell. One trial gives no confidence interval.
- If no run passes, or a run has no cost, the table shows "—" for Cost per pass.

## The cost estimate on OpenCode (D116)

OpenCode reports a cost of 0 on the Go plan. `stone eval` estimates the cost from the token counts and
[rates.yaml](../../framework/adapters/opencode/rates.yaml). The estimate is not the billed cost.

The file gives the USD rates for each 1M tokens. Reasoning tokens use the output rate. The start of a
run selects the peak or the off-peak rate. A model with no rates and a reported cost of 0 shows "—".

If the command warns that a model is in a peak window, stop it. Run it outside that window to use the
off-peak rate.

When the plan page changes, update the rates and the read date in `rates.yaml`. Follow
[Token rates](../../framework/profiles/adapter-refresh.md#token-rates).

## Limits

The [first matrix](../reports/2026-11-09-opencode-role-eval-costs.md) had one trial for each cell and
saturated scenarios, so it cannot rank the models yet.

The model picks come later in [#305](https://github.com/brawblan/ai-workflow/issues/305) and
[#306](https://github.com/brawblan/ai-workflow/issues/306).
