# The first stone eval runs on OpenCode, and their cost

Part of [#301](https://github.com/brawblan/ai-workflow/issues/301). Date: 2026-11-09. The cost fix
is [#315](https://github.com/brawblan/ai-workflow/issues/315).

## Result

- 28 of 28 runs finished with no error. `stone eval` ran them with the OpenCode adapter of `dev`.
- With the role, 13 of 14 runs passed every check. Without the role, 0 of 14 runs passed. The
  contract score without the role was 0.00 in each run.
- The cost from the token counts and the published rates is $0.0994 for all 28 runs. Each result
  file shows $0.0000, because OpenCode reports a cost of 0. #315 fixes this.
- With the role, one run costs $0.0026 to $0.0040. That is less than 0.01% of the monthly cap of
  each model.

## Method

- Harness: OpenCode 2.2.6. Plan: OpenCode Go. `stone` from `dev` at commit `9413145`.
- Models: `opencode-go/glm-5.3-flash` and `opencode-go/deepseek-v4.1-flash`. Kimi K3.1 Pro was not
  run, to save the plan usage.
- Scope: `role.implementer` (I1 to I3) and `role.tester` (T1 to T4). Both variants. One trial.
- The commands were:

```bash
stone eval role.implementer --trials 1 \
  --model opencode:opencode-go/glm-5.3-flash --model opencode:opencode-go/deepseek-v4.1-flash
stone eval role.tester --trials 1 \
  --model opencode:opencode-go/glm-5.3-flash --model opencode:opencode-go/deepseek-v4.1-flash
```

- The runs started at about 21:26 UTC and ended at about 21:40 UTC, on a Monday. That time is
  off-peak for DeepSeek.
- The cost uses the token counts in the `runs.jsonl` file of each run. Reasoning tokens use the
  output rate, as in the [pilot](2026-11-08-opencode-role-eval-pilot.md).

The rates in USD for each 1M tokens, from the [OpenCode Go docs](https://opencode.ai/docs/go), read
2026-11-09:

| Model | Input | Output | Cache read | Cache write |
| --- | --- | --- | --- | --- |
| `glm-5.3-flash` | 0.15 | 0.50 | 0.03 | none given |
| `deepseek-v4.1-flash`, off-peak | 0.15 | 0.60 | 0.003 | none given |
| `deepseek-v4.1-flash`, peak | 0.30 | 1.20 | 0.006 | none given |
| `kimi-k3.1-pro` | 2.00 | 10.00 | 0.20 | 2.00 |

DeepSeek peak hours are 01:00 to 04:00 and 06:00 to 10:00 UTC, Monday to Friday.

## Pass rates

| Role | Model | Pass with | Pass without | Outcome, with minus without |
| --- | --- | --- | --- | --- |
| Implementer | `glm-5.3-flash` | 3 of 3 | 0 of 3 | +0.67 |
| Implementer | `deepseek-v4.1-flash` | 3 of 3 | 0 of 3 | +1.00 |
| Tester | `glm-5.3-flash` | 3 of 4 | 0 of 4 | +0.50 |
| Tester | `deepseek-v4.1-flash` | 4 of 4 | 0 of 4 | +0.00 |

- Without the role, no run kept the contract: the decision log, the commit trailer, and the report
  form. The Claude Code baseline shows the same result.
- Without the role, DeepSeek wrote tests that killed the mutants in T1 to T4. It failed the
  acceptance tests in I1 to I3.
- One `glm-5.3-flash` T4 run with the role passed the outcome checks and failed a contract check.
  The workspace was not kept, so the failed check is not known.

## Cost

| Role | Model | Variant | Runs | Pass | Total | Mean for each run | Cost per pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Implementer | `deepseek-v4.1-flash` | with | 3 | 3 | 0.0098 | 0.0033 | 0.0033 |
| Implementer | `deepseek-v4.1-flash` | without | 3 | 0 | 0.0096 | 0.0032 | — |
| Implementer | `glm-5.3-flash` | with | 3 | 3 | 0.0078 | 0.0026 | 0.0026 |
| Implementer | `glm-5.3-flash` | without | 3 | 0 | 0.0111 | 0.0037 | — |
| Tester | `deepseek-v4.1-flash` | with | 4 | 4 | 0.0160 | 0.0040 | 0.0040 |
| Tester | `deepseek-v4.1-flash` | without | 4 | 0 | 0.0185 | 0.0046 | — |
| Tester | `glm-5.3-flash` | with | 4 | 3 | 0.0111 | 0.0028 | 0.0037 |
| Tester | `glm-5.3-flash` | without | 4 | 0 | 0.0155 | 0.0039 | — |

- With the role, a `glm-5.3-flash` run costs 13% to 29% less than without it.
- With the role, a `deepseek-v4.1-flash` run costs about the same as without it. Without the role,
  the tester runs read about two times the tool bytes. DeepSeek cache reads are cheap, so the cost
  stays almost the same.
- A peak-hour DeepSeek run costs two times the values above.

## Plan caps

From the same docs page, read 2026-11-09:

| Plan | Price | `glm-5.3-flash` cap | `deepseek-v4.1-flash` cap | `kimi-k3.1-pro` cap |
| --- | --- | --- | --- | --- |
| Go | $10 for each month | $60 | $100 | $15 |
| Go Plus | $40 for each month | $180 | $200 | $60 |

The pilot estimated that one full #304 matrix uses 21% of the Kimi cap on Go. On Go Plus, that is
about 5%. The flash models use less than 1% on each plan.

## Limits

- One trial for each cell. The pass rates have no confidence interval.
- The cost is an estimate from the published rates. It is not the billed cost. OpenCode reports
  neither the billed cost nor the allowance.
- The docs give no cache write rate for the two flash models. Their cache write counts were 0.
- The scenarios are at a ceiling with the role. The data cannot rank the two models.
- The `without` variant of OpenCode has no permissions and no step cap. The difference mixes the
  role text, the permissions, and the step cap (see the adapter doc).
- The `runs.jsonl` files and the transcripts are outside the repo. They are not committed.

## Result files

- [role.implementer, glm-5.3-flash](../../evals/results/20261109-162610-role.implementer-opencode-opencode-go-glm-5.3-flash.md)
- [role.implementer, deepseek-v4.1-flash](../../evals/results/20261109-162610-role.implementer-opencode-opencode-go-deepseek-v4.1-flash.md)
- [role.tester, glm-5.3-flash](../../evals/results/20261109-163102-role.tester-opencode-opencode-go-glm-5.3-flash.md)
- [role.tester, deepseek-v4.1-flash](../../evals/results/20261109-163102-role.tester-opencode-opencode-go-deepseek-v4.1-flash.md)
