# Premium model matrix (2026-11-18)

Source ticket: #346 (part of #301, after #305). Date of the runs: 2026-11-18. Version: stone 1.7.0.

Harness: OpenCode, Go plan. Rates: `framework/adapters/opencode/rates.yaml`. Costs are estimates from
the token rates. They are not the billed cost.

The owner decides the ceiling and `defaults.role_models`. This report changes neither.

## 1. Result

- No new model wins an economy pick. `beam-free` costs 0, so it stays the economy pick in all six roles.
- With a `quality_cost_ceiling` of 0.005, the quality pick moves from `beam-free` to a new model in
  five of six roles. `claude-haiku-5-5` wins four roles. `gpt-6-luna` wins the reviewer.
- `deepseek-v4-pro` wins no pick. Each passing run costs 9 to 21 times more than Haiku or luna, and the
  pass rate is not higher.
- `kimi-k3.1-pro` wins no pick. Each passing run costs 27 to 61 times more than Haiku.
- The shaper has no better model than `beam-free` (0.93). Haiku ties it at 0.93.

## 2. Data and limits

| Item | State |
| --- | --- |
| New models | `claude-haiku-5-5`, `gpt-6-luna`, `deepseek-v4-pro`. 3 trials for each scenario, variant `with`. |
| Runs | 189 of 216. `claude-haiku-5-5` and `gpt-6-luna`: 72 of 72. `deepseek-v4-pro`: 45 of 72. |
| Missing | `deepseek-v4-pro` tester (12 runs) and planner (15 runs). The weekly usage limit of the Go plan stopped them. They run after the reset (about 2026-11-22). |
| Errors | No harness error and no usage limit in any counted run. |
| Grading | The 189 kept workspaces were graded again with the graders of PR #347 and PR #348. |
| Old rows | `beam-free`, `glm-5.3-flash`, `deepseek-v4.1-flash`, and `kimi-k3.1-pro` come from the runs of #305. The raw run files of #305 were not available. The rows are the saved output of the picks command. |
| Old grader faults | The #305 rows were not graded again with #347 and #348. The investigator rows of `deepseek-v4.1-flash` (0.44) and `glm-5.3-flash` (0.22) may be too low. The `kimi-k3.1-pro` reviewer row (0.00) is from before PR #345. It is not valid. It is left out of the comparison. |
| Token columns | The new rows count the input tokens with the cache write and cache read added. The "Tokens in" column of the picks command does not count the cache. The two are not equal. |


## 3. Results for each role

Pass rate, cost for each passing run (USD), and tokens for each run (mean). The new models are in bold.
The tokens of the old models are the values of the picks command. They do not add the cache, so they are not
comparable with the new rows.

### Shaper

| Model | Runs | Pass rate | Cost per pass | Tokens in | Tokens out |
| --- | --- | --- | --- | --- | --- |
| beam-free | 15 | 0.93 ±0.07 | 0.0000 | 33329 | 1026 |
| glm-5.3-flash | 15 | 0.53 ±0.13 | 0.0032 | 5709 | 574 |
| deepseek-v4.1-flash | 15 | 0.53 ±0.13 | 0.0178 | 19424 | 1999 |
| kimi-k3.1-pro | 15 | 0.60 ±0.13 | 0.0857 | 6922 | 808 |
| **claude-haiku-5-5** | 15 | 0.93 ±0.07 | 0.0014 | 15852 | 879 |
| **gpt-6-luna** | 15 | 0.60 ±0.13 | 0.0018 | 7030 | 299 |
| **deepseek-v4-pro** | 15 | 0.73 ±0.12 | 0.0303 | 43579 | 1061 |

### Planner

| Model | Runs | Pass rate | Cost per pass | Tokens in | Tokens out |
| --- | --- | --- | --- | --- | --- |
| beam-free | 15 | 0.87 ±0.09 | 0.0000 | 22916 | 1776 |
| glm-5.3-flash | 15 | 0.93 ±0.07 | 0.0031 | 9010 | 1554 |
| deepseek-v4.1-flash | 15 | 1.00 ±0.00 | 0.0078 | 17969 | 3955 |
| kimi-k3.1-pro | 15 | 1.00 ±0.00 | 0.1125 | 13756 | 3064 |
| **claude-haiku-5-5** | 15 | 1.00 ±0.00 | 0.0041 | 36480 | 3783 |
| **gpt-6-luna** | 15 | 0.93 ±0.07 | 0.0026 | 25007 | 1316 |
| **deepseek-v4-pro** | 0 | not run | not run | not run | not run |

### Implementer

| Model | Runs | Pass rate | Cost per pass | Tokens in | Tokens out |
| --- | --- | --- | --- | --- | --- |
| beam-free | 9 | 0.44 ±0.18 | 0.0000 | 9971 | 715 |
| glm-5.3-flash | 9 | 0.89 ±0.11 | 0.0027 | 7866 | 1045 |
| deepseek-v4.1-flash | 9 | 1.00 ±0.00 | 0.0025 | 7290 | 1592 |
| kimi-k3.1-pro | 13 | 1.00 ±0.00 | 0.0760 | 8852 | 2281 |
| **claude-haiku-5-5** | 9 | 1.00 ±0.00 | 0.0018 | 26900 | 1776 |
| **gpt-6-luna** | 9 | 0.89 ±0.11 | 0.0029 | 57650 | 1540 |
| **deepseek-v4-pro** | 9 | 0.89 ±0.11 | 0.0204 | 79744 | 1896 |

### Tester

| Model | Runs | Pass rate | Cost per pass | Tokens in | Tokens out |
| --- | --- | --- | --- | --- | --- |
| beam-free | 12 | 0.92 ±0.08 | 0.0000 | 29273 | 2094 |
| glm-5.3-flash | 12 | 0.83 ±0.11 | 0.0034 | 8624 | 1367 |
| deepseek-v4.1-flash | 12 | 0.92 ±0.08 | 0.0033 | 7849 | 2070 |
| kimi-k3.1-pro | 12 | 0.75 ±0.13 | 0.1056 | 7412 | 2410 |
| **claude-haiku-5-5** | 12 | 1.00 ±0.00 | 0.0025 | 32713 | 2576 |
| **gpt-6-luna** | 12 | 1.00 ±0.00 | 0.0029 | 57533 | 1355 |
| **deepseek-v4-pro** | 0 | not run | not run | not run | not run |

### Reviewer

| Model | Runs | Pass rate | Cost per pass | Tokens in | Tokens out |
| --- | --- | --- | --- | --- | --- |
| beam-free | 12 | 0.42 ±0.15 | 0.0000 | 19484 | 1051 |
| glm-5.3-flash | 12 | 1.00 ±0.00 | 0.0013 | 4630 | 592 |
| deepseek-v4.1-flash | 12 | 1.00 ±0.00 | 0.0029 | 7826 | 1559 |
| kimi-k3.1-pro (not valid, see section 2) | 12 | 0.00 ±0.00 | — | 3715 | 1046 |
| **claude-haiku-5-5** | 12 | 0.83 ±0.11 | 0.0013 | 10254 | 1025 |
| **gpt-6-luna** | 12 | 1.00 ±0.00 | 0.0012 | 15232 | 521 |
| **deepseek-v4-pro** | 12 | 0.92 ±0.08 | 0.0112 | 20430 | 1147 |

### Investigator

| Model | Runs | Pass rate | Cost per pass | Tokens in | Tokens out |
| --- | --- | --- | --- | --- | --- |
| beam-free | 9 | 0.22 ±0.15 | 0.0000 | 52149 | 3307 |
| glm-5.3-flash | 9 | 0.22 ±0.15 | 0.0133 | 8776 | 1592 |
| deepseek-v4.1-flash | 9 | 0.44 ±0.18 | 0.0128 | 14025 | 3697 |
| kimi-k3.1-pro | 9 | 1.00 ±0.00 | 0.0900 | 11114 | 3280 |
| **claude-haiku-5-5** | 9 | 1.00 ±0.00 | 0.0026 | 37097 | 2678 |
| **gpt-6-luna** | 9 | 1.00 ±0.00 | 0.0035 | 69701 | 1949 |
| **deepseek-v4-pro** | 9 | 1.00 ±0.00 | 0.0400 | 174189 | 3402 |

### Comparison with `kimi-k3.1-pro` and `deepseek-v4.1-flash`

| Role | Best new model | Pass rate (new / kimi / flash) | Cost per pass (new / kimi / flash) |
| --- | --- | --- | --- |
| shaper | claude-haiku-5-5 | 0.93 / 0.60 / 0.53 | 0.0014 / 0.0857 / 0.0178 |
| planner | claude-haiku-5-5 | 1.00 / 1.00 / 1.00 | 0.0041 / 0.1125 / 0.0078 |
| implementer | claude-haiku-5-5 | 1.00 / 1.00 / 1.00 | 0.0018 / 0.0760 / 0.0025 |
| tester | claude-haiku-5-5 | 1.00 / 0.75 / 0.92 | 0.0025 / 0.1056 / 0.0033 |
| reviewer | gpt-6-luna | 1.00 / n/a / 1.00 | 0.0012 / n/a / 0.0029 |
| investigator | claude-haiku-5-5 | 1.00 / 1.00 / 0.44 | 0.0026 / 0.0900 / 0.0128 |

## 4. Failed runs

Each failed `with` run was read (criterion 6).

| Cause | Runs | Action |
| --- | --- | --- |
| The grader was too narrow for a valid report | 14 checks in 13 runs | Fixed in PR #347 (`finding_form`, T2) and PR #348 (S3, R3, V3) |
| Model fault | The other failed runs | Counted as failures |
| Fixture question | 1 run (`deepseek-v4-pro` R4 run 1) | Open. See below. |

Model faults seen:

- Shaper S2 and S5: no question on a persona or a test oracle, or an invented persona (`writer`).
  This is the main reason `gpt-6-luna` (0.60) and `deepseek-v4-pro` (0.73) lose on the shaper.
- `gpt-6-luna` planner P4 run 3 wrote no plan file. `gpt-6-luna` implementer I3 run 2 did not name the
  conflicting test in its decision log. `gpt-6-luna` shaper S3 run 3 did not ask about the relevance criterion.
- `deepseek-v4-pro` implementer I1 run 2 used `pop(number - 1)`. A number of 0 or a negative number does
  not raise `IndexError`.
- `claude-haiku-5-5` reviewer R1 run 3 and R3 run 3 gave a finding with no line number.

Open fixture question: the harness commits each fixture change, tests included, as `Role: implementer`.
The K6 check of the repo fails this. `deepseek-v4-pro` ran the check on the clean change R4 and reported
a Medium finding. The finding is true for the fixture. The owner has not decided. Nothing changed.

## 5. Proposal: `quality_cost_ceiling`

Proposed value: 0.005 (USD for each passing run). This report does not set it.

| Ceiling | Quality pick of each role |
| --- | --- |
| Not set (limit 0) | `beam-free` in all roles |
| 0.003 | Planner `gpt-6-luna` (0.93). Implementer, tester, and investigator `claude-haiku-5-5`. Reviewer `gpt-6-luna`. Shaper `beam-free`. |
| 0.005 to 0.05 | The same, but the planner is `claude-haiku-5-5` (1.00) |

Reason: 0.005 is the lowest value that gives the best pick in each role. Any value up to 0.05 gives the
same picks. A value of 0.003 loses the planner pick of Haiku (0.0041 for each passing run). The
`deepseek-v4-pro` rows (0.011 to 0.04) and the `kimi-k3.1-pro` rows (0.076 to 0.11) cost more than the
best new model in every role. Review the value when the `deepseek-v4-pro` tester and planner runs are in.

## 6. Proposed `recommendations` block

The rules are D120 and D125 with a ceiling of 0.005. The `review` date is a proposal. The block is not in
the profile. Check that each role is in `defaults.role_models` before you add it.

```yaml
recommendations:

  shaper:
    economy:
      model: opencode-go/beam-free
      pass_rate: 0.93
      cost_per_pass: 0.0000
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
    quality:
      model: opencode-go/beam-free
      pass_rate: 0.93
      cost_per_pass: 0.0000
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
  planner:
    economy:
      model: opencode-go/beam-free
      pass_rate: 0.87
      cost_per_pass: 0.0000
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
    quality:
      model: opencode-go/claude-haiku-5-5
      pass_rate: 1.00
      cost_per_pass: 0.0041
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
  implementer:
    economy:
      model: opencode-go/beam-free
      pass_rate: 0.44
      cost_per_pass: 0.0000
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
    quality:
      model: opencode-go/claude-haiku-5-5
      pass_rate: 1.00
      cost_per_pass: 0.0018
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
  tester:
    economy:
      model: opencode-go/beam-free
      pass_rate: 0.92
      cost_per_pass: 0.0000
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
    quality:
      model: opencode-go/claude-haiku-5-5
      pass_rate: 1.00
      cost_per_pass: 0.0025
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
  reviewer:
    economy:
      model: opencode-go/beam-free
      pass_rate: 0.42
      cost_per_pass: 0.0000
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
    quality:
      model: opencode-go/gpt-6-luna
      pass_rate: 1.00
      cost_per_pass: 0.0012
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
  investigator:
    economy:
      model: opencode-go/beam-free
      pass_rate: 0.22
      cost_per_pass: 0.0000
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
    quality:
      model: opencode-go/claude-haiku-5-5
      pass_rate: 1.00
      cost_per_pass: 0.0026
      trials: 3
      eval_version: 1.7.0
      date: 2026-11-18
      review: 2027-05-17
```

## 7. Proposed "Model picks" text (`framework/adapters/opencode.md`)

| Role | Economy pick | Quality pick | Date |
| --- | --- | --- | --- |
| shaper | `opencode-go/beam-free` (0.93, cost 0) | `opencode-go/beam-free` (0.93, cost 0) | 2026-11-18 |
| planner | `opencode-go/beam-free` (0.87, cost 0) | `opencode-go/claude-haiku-5-5` (1.00, 0.0041) | 2026-11-18 |
| implementer | `opencode-go/beam-free` (0.44, cost 0) | `opencode-go/claude-haiku-5-5` (1.00, 0.0018) | 2026-11-18 |
| tester | `opencode-go/beam-free` (0.92, cost 0) | `opencode-go/claude-haiku-5-5` (1.00, 0.0025) | 2026-11-18 |
| reviewer | `opencode-go/beam-free` (0.42, cost 0) | `opencode-go/gpt-6-luna` (1.00, 0.0012) | 2026-11-18 |
| investigator | `opencode-go/beam-free` (0.22, cost 0) | `opencode-go/claude-haiku-5-5` (1.00, 0.0026) | 2026-11-18 |

The standard error of a pass rate is 0.07 to 0.18, with 9 to 15 runs for each role. In the implementer,
tester, and reviewer roles, the new models are close to `deepseek-v4.1-flash` and `glm-5.3-flash`. The rule
picks the lower cost.

## 8. Tokens for each run

Input tokens include the cache write and the cache read. A pass is a run with no failed check.

| Role | Model | Scenario | Trial | Pass | Cost (USD) | Tokens in | Tokens out |
| --- | --- | --- | --- | --- | --- | --- | --- |

| shaper | claude-haiku-5-5 | S1 | 1 | yes | 0.0016 | 22506 | 541 |
| shaper | claude-haiku-5-5 | S1 | 2 | yes | 0.0007 | 8106 | 436 |
| shaper | claude-haiku-5-5 | S1 | 3 | yes | 0.0009 | 13464 | 532 |
| shaper | claude-haiku-5-5 | S2 | 1 | no | 0.0014 | 17763 | 1063 |
| shaper | claude-haiku-5-5 | S2 | 2 | yes | 0.0021 | 21453 | 1896 |
| shaper | claude-haiku-5-5 | S2 | 3 | yes | 0.0016 | 17710 | 1171 |
| shaper | claude-haiku-5-5 | S3 | 1 | yes | 0.0012 | 17561 | 925 |
| shaper | claude-haiku-5-5 | S3 | 2 | yes | 0.0009 | 12106 | 652 |
| shaper | claude-haiku-5-5 | S3 | 3 | yes | 0.0012 | 12087 | 781 |
| shaper | claude-haiku-5-5 | S4 | 1 | yes | 0.0023 | 27101 | 1078 |
| shaper | claude-haiku-5-5 | S4 | 2 | yes | 0.0014 | 13797 | 948 |
| shaper | claude-haiku-5-5 | S4 | 3 | yes | 0.0019 | 25699 | 1141 |
| shaper | claude-haiku-5-5 | S5 | 1 | yes | 0.0009 | 12334 | 642 |
| shaper | claude-haiku-5-5 | S5 | 2 | yes | 0.0009 | 8044 | 664 |
| shaper | claude-haiku-5-5 | S5 | 3 | yes | 0.0010 | 8043 | 717 |
| planner | claude-haiku-5-5 | P1 | 1 | yes | 0.0058 | 52912 | 5240 |
| planner | claude-haiku-5-5 | P1 | 2 | yes | 0.0039 | 35563 | 4002 |
| planner | claude-haiku-5-5 | P1 | 3 | yes | 0.0048 | 33852 | 4748 |
| planner | claude-haiku-5-5 | P2 | 1 | yes | 0.0009 | 14492 | 727 |
| planner | claude-haiku-5-5 | P2 | 2 | yes | 0.0014 | 21765 | 1204 |
| planner | claude-haiku-5-5 | P2 | 3 | yes | 0.0010 | 14524 | 788 |
| planner | claude-haiku-5-5 | P3 | 1 | yes | 0.0042 | 39906 | 4007 |
| planner | claude-haiku-5-5 | P3 | 2 | yes | 0.0051 | 51672 | 4198 |
| planner | claude-haiku-5-5 | P3 | 3 | yes | 0.0045 | 37602 | 3817 |
| planner | claude-haiku-5-5 | P4 | 1 | yes | 0.0056 | 43173 | 5338 |
| planner | claude-haiku-5-5 | P4 | 2 | yes | 0.0065 | 54112 | 5448 |
| planner | claude-haiku-5-5 | P4 | 3 | yes | 0.0052 | 33935 | 4790 |
| planner | claude-haiku-5-5 | P5 | 1 | yes | 0.0041 | 36924 | 3782 |
| planner | claude-haiku-5-5 | P5 | 2 | yes | 0.0051 | 47782 | 4808 |
| planner | claude-haiku-5-5 | P5 | 3 | yes | 0.0041 | 28986 | 3849 |
| implementer | claude-haiku-5-5 | I1 | 1 | yes | 0.0017 | 23642 | 1516 |
| implementer | claude-haiku-5-5 | I1 | 2 | yes | 0.0015 | 29234 | 1734 |
| implementer | claude-haiku-5-5 | I1 | 3 | yes | 0.0014 | 23759 | 1426 |
| implementer | claude-haiku-5-5 | I2 | 1 | yes | 0.0014 | 19170 | 1601 |
| implementer | claude-haiku-5-5 | I2 | 2 | yes | 0.0013 | 18840 | 1419 |
| implementer | claude-haiku-5-5 | I2 | 3 | yes | 0.0015 | 19547 | 1713 |
| implementer | claude-haiku-5-5 | I3 | 1 | yes | 0.0024 | 33054 | 2327 |
| implementer | claude-haiku-5-5 | I3 | 2 | yes | 0.0023 | 31594 | 2278 |
| implementer | claude-haiku-5-5 | I3 | 3 | yes | 0.0023 | 43263 | 1970 |
| tester | claude-haiku-5-5 | T1 | 1 | yes | 0.0021 | 26799 | 2399 |
| tester | claude-haiku-5-5 | T1 | 2 | yes | 0.0022 | 27958 | 2334 |
| tester | claude-haiku-5-5 | T1 | 3 | yes | 0.0026 | 37207 | 2496 |
| tester | claude-haiku-5-5 | T2 | 1 | yes | 0.0023 | 28922 | 2407 |
| tester | claude-haiku-5-5 | T2 | 2 | yes | 0.0030 | 40949 | 3009 |
| tester | claude-haiku-5-5 | T2 | 3 | yes | 0.0025 | 30648 | 2387 |
| tester | claude-haiku-5-5 | T3 | 1 | yes | 0.0022 | 27923 | 2587 |
| tester | claude-haiku-5-5 | T3 | 2 | yes | 0.0022 | 29166 | 2470 |
| tester | claude-haiku-5-5 | T3 | 3 | yes | 0.0026 | 30586 | 2868 |
| tester | claude-haiku-5-5 | T4 | 1 | yes | 0.0025 | 29219 | 2850 |
| tester | claude-haiku-5-5 | T4 | 2 | yes | 0.0023 | 30421 | 2108 |
| tester | claude-haiku-5-5 | T4 | 3 | yes | 0.0034 | 52754 | 2995 |
| reviewer | claude-haiku-5-5 | R1 | 1 | yes | 0.0013 | 11728 | 1134 |
| reviewer | claude-haiku-5-5 | R1 | 2 | yes | 0.0012 | 11860 | 1353 |
| reviewer | claude-haiku-5-5 | R1 | 3 | no | 0.0009 | 7255 | 943 |
| reviewer | claude-haiku-5-5 | R2 | 1 | yes | 0.0009 | 11193 | 869 |
| reviewer | claude-haiku-5-5 | R2 | 2 | yes | 0.0010 | 7662 | 974 |
| reviewer | claude-haiku-5-5 | R2 | 3 | yes | 0.0009 | 11439 | 991 |
| reviewer | claude-haiku-5-5 | R3 | 1 | yes | 0.0015 | 17426 | 1123 |
| reviewer | claude-haiku-5-5 | R3 | 2 | yes | 0.0010 | 7295 | 1125 |
| reviewer | claude-haiku-5-5 | R3 | 3 | no | 0.0010 | 7090 | 1017 |
| reviewer | claude-haiku-5-5 | R4 | 1 | yes | 0.0010 | 11434 | 970 |
| reviewer | claude-haiku-5-5 | R4 | 2 | yes | 0.0009 | 7371 | 910 |
| reviewer | claude-haiku-5-5 | R4 | 3 | yes | 0.0009 | 11295 | 893 |
| investigator | claude-haiku-5-5 | V1 | 1 | yes | 0.0021 | 27260 | 2183 |
| investigator | claude-haiku-5-5 | V1 | 2 | yes | 0.0032 | 55911 | 3441 |
| investigator | claude-haiku-5-5 | V1 | 3 | yes | 0.0027 | 37307 | 2979 |
| investigator | claude-haiku-5-5 | V2 | 1 | yes | 0.0023 | 30450 | 2499 |
| investigator | claude-haiku-5-5 | V2 | 2 | yes | 0.0027 | 52657 | 2567 |
| investigator | claude-haiku-5-5 | V2 | 3 | yes | 0.0027 | 32404 | 2616 |
| investigator | claude-haiku-5-5 | V3 | 1 | yes | 0.0022 | 34992 | 2260 |
| investigator | claude-haiku-5-5 | V3 | 2 | yes | 0.0025 | 30657 | 2867 |
| investigator | claude-haiku-5-5 | V3 | 3 | yes | 0.0028 | 32239 | 2692 |
| shaper | gpt-6-luna | S1 | 1 | yes | 0.0006 | 4176 | 236 |
| shaper | gpt-6-luna | S1 | 2 | yes | 0.0007 | 6421 | 252 |
| shaper | gpt-6-luna | S1 | 3 | yes | 0.0006 | 6266 | 188 |
| shaper | gpt-6-luna | S2 | 1 | no | 0.0017 | 14663 | 547 |
| shaper | gpt-6-luna | S2 | 2 | no | 0.0016 | 7985 | 404 |
| shaper | gpt-6-luna | S2 | 3 | no | 0.0013 | 7346 | 493 |
| shaper | gpt-6-luna | S3 | 1 | yes | 0.0012 | 6309 | 272 |
| shaper | gpt-6-luna | S3 | 2 | yes | 0.0010 | 4164 | 319 |
| shaper | gpt-6-luna | S3 | 3 | no | 0.0010 | 4041 | 188 |
| shaper | gpt-6-luna | S4 | 1 | yes | 0.0018 | 8321 | 300 |
| shaper | gpt-6-luna | S4 | 2 | yes | 0.0015 | 8036 | 396 |
| shaper | gpt-6-luna | S4 | 3 | yes | 0.0008 | 9312 | 399 |
| shaper | gpt-6-luna | S5 | 1 | yes | 0.0006 | 3961 | 123 |
| shaper | gpt-6-luna | S5 | 2 | no | 0.0011 | 7285 | 183 |
| shaper | gpt-6-luna | S5 | 3 | no | 0.0010 | 7170 | 185 |
| shaper | deepseek-v4-pro | S1 | 1 | yes | 0.0098 | 25520 | 624 |
| shaper | deepseek-v4-pro | S1 | 2 | yes | 0.0091 | 16644 | 577 |
| shaper | deepseek-v4-pro | S1 | 3 | yes | 0.0105 | 18280 | 740 |
| shaper | deepseek-v4-pro | S2 | 1 | no | 0.0278 | 41931 | 1053 |
| shaper | deepseek-v4-pro | S2 | 2 | no | 0.0416 | 95137 | 1734 |
| shaper | deepseek-v4-pro | S2 | 3 | no | 0.0487 | 97449 | 1555 |
| shaper | deepseek-v4-pro | S3 | 1 | yes | 0.0199 | 21431 | 1424 |
| shaper | deepseek-v4-pro | S3 | 2 | yes | 0.0220 | 44847 | 1350 |
| shaper | deepseek-v4-pro | S3 | 3 | yes | 0.0147 | 21694 | 1090 |
| shaper | deepseek-v4-pro | S4 | 1 | yes | 0.0127 | 53770 | 876 |
| shaper | deepseek-v4-pro | S4 | 2 | yes | 0.0103 | 24264 | 835 |
| shaper | deepseek-v4-pro | S4 | 3 | yes | 0.0197 | 59581 | 1047 |
| planner | gpt-6-luna | P1 | 1 | yes | 0.0028 | 23412 | 1906 |
| planner | gpt-6-luna | P1 | 2 | yes | 0.0025 | 17480 | 1749 |
| planner | gpt-6-luna | P1 | 3 | yes | 0.0025 | 28015 | 1727 |
| planner | gpt-6-luna | P2 | 1 | yes | 0.0008 | 8248 | 259 |
| planner | gpt-6-luna | P2 | 2 | yes | 0.0007 | 9365 | 132 |
| planner | gpt-6-luna | P2 | 3 | yes | 0.0010 | 14054 | 297 |
| planner | gpt-6-luna | P3 | 1 | yes | 0.0041 | 45435 | 2041 |
| planner | gpt-6-luna | P3 | 2 | yes | 0.0025 | 34298 | 1520 |
| planner | gpt-6-luna | P3 | 3 | yes | 0.0033 | 35699 | 1777 |
| planner | gpt-6-luna | P4 | 1 | yes | 0.0026 | 23403 | 1598 |
| planner | gpt-6-luna | P4 | 2 | yes | 0.0029 | 24330 | 1602 |
| planner | gpt-6-luna | P4 | 3 | no | 0.0015 | 20003 | 366 |
| planner | gpt-6-luna | P5 | 1 | yes | 0.0026 | 17069 | 1422 |
| planner | gpt-6-luna | P5 | 2 | yes | 0.0030 | 35868 | 1556 |
| planner | gpt-6-luna | P5 | 3 | yes | 0.0032 | 38428 | 1787 |
| implementer | gpt-6-luna | I1 | 1 | yes | 0.0027 | 70882 | 1117 |
| implementer | gpt-6-luna | I1 | 2 | yes | 0.0027 | 67695 | 1337 |
| implementer | gpt-6-luna | I1 | 3 | yes | 0.0039 | 102447 | 2533 |
| implementer | gpt-6-luna | I2 | 1 | yes | 0.0027 | 59401 | 1568 |
| implementer | gpt-6-luna | I2 | 2 | yes | 0.0018 | 31457 | 1299 |
| implementer | gpt-6-luna | I2 | 3 | yes | 0.0023 | 48498 | 1626 |
| implementer | gpt-6-luna | I3 | 1 | yes | 0.0023 | 44971 | 1444 |
| implementer | gpt-6-luna | I3 | 2 | no | 0.0022 | 38045 | 1336 |
| implementer | gpt-6-luna | I3 | 3 | yes | 0.0026 | 55456 | 1599 |
| tester | gpt-6-luna | T1 | 1 | yes | 0.0029 | 62977 | 1707 |
| tester | gpt-6-luna | T1 | 2 | yes | 0.0029 | 65491 | 1253 |
| tester | gpt-6-luna | T1 | 3 | yes | 0.0038 | 63296 | 1786 |
| tester | gpt-6-luna | T2 | 1 | yes | 0.0028 | 56010 | 1298 |
| tester | gpt-6-luna | T2 | 2 | yes | 0.0027 | 58598 | 1483 |
| tester | gpt-6-luna | T2 | 3 | yes | 0.0036 | 67517 | 1615 |
| tester | gpt-6-luna | T3 | 1 | yes | 0.0030 | 55353 | 1968 |
| tester | gpt-6-luna | T3 | 2 | yes | 0.0027 | 53349 | 1020 |
| tester | gpt-6-luna | T3 | 3 | yes | 0.0020 | 31013 | 990 |
| tester | gpt-6-luna | T4 | 1 | yes | 0.0026 | 52609 | 890 |
| tester | gpt-6-luna | T4 | 2 | yes | 0.0033 | 62090 | 1255 |
| tester | gpt-6-luna | T4 | 3 | yes | 0.0030 | 62092 | 997 |
| reviewer | gpt-6-luna | R1 | 1 | yes | 0.0009 | 8731 | 419 |
| reviewer | gpt-6-luna | R1 | 2 | yes | 0.0016 | 19107 | 415 |
| reviewer | gpt-6-luna | R1 | 3 | yes | 0.0020 | 28723 | 817 |
| reviewer | gpt-6-luna | R2 | 1 | yes | 0.0011 | 11907 | 685 |
| reviewer | gpt-6-luna | R2 | 2 | yes | 0.0012 | 14823 | 828 |
| reviewer | gpt-6-luna | R2 | 3 | yes | 0.0008 | 12952 | 340 |
| reviewer | gpt-6-luna | R3 | 1 | yes | 0.0012 | 13409 | 394 |
| reviewer | gpt-6-luna | R3 | 2 | yes | 0.0011 | 15126 | 441 |
| reviewer | gpt-6-luna | R3 | 3 | yes | 0.0011 | 13639 | 516 |
| reviewer | gpt-6-luna | R4 | 1 | yes | 0.0010 | 16206 | 515 |
| reviewer | gpt-6-luna | R4 | 2 | yes | 0.0011 | 16280 | 349 |
| reviewer | gpt-6-luna | R4 | 3 | yes | 0.0010 | 11886 | 538 |
| investigator | gpt-6-luna | V1 | 1 | yes | 0.0023 | 27660 | 1764 |
| investigator | gpt-6-luna | V1 | 2 | yes | 0.0043 | 70807 | 3097 |
| investigator | gpt-6-luna | V1 | 3 | yes | 0.0051 | 142028 | 2242 |
| investigator | gpt-6-luna | V2 | 1 | yes | 0.0033 | 64727 | 1660 |
| investigator | gpt-6-luna | V2 | 2 | yes | 0.0040 | 88599 | 2560 |
| investigator | gpt-6-luna | V2 | 3 | yes | 0.0036 | 69043 | 1867 |
| investigator | gpt-6-luna | V3 | 1 | yes | 0.0030 | 61185 | 1360 |
| investigator | gpt-6-luna | V3 | 2 | yes | 0.0026 | 42141 | 1593 |
| investigator | gpt-6-luna | V3 | 3 | yes | 0.0031 | 61117 | 1401 |
| shaper | deepseek-v4-pro | S5 | 1 | yes | 0.0354 | 32629 | 1002 |
| shaper | deepseek-v4-pro | S5 | 2 | no | 0.0212 | 63071 | 903 |
| shaper | deepseek-v4-pro | S5 | 3 | yes | 0.0296 | 37430 | 1101 |
| reviewer | deepseek-v4-pro | R1 | 1 | yes | 0.0079 | 17792 | 1525 |
| reviewer | deepseek-v4-pro | R1 | 2 | yes | 0.0120 | 18941 | 1296 |
| reviewer | deepseek-v4-pro | R1 | 3 | yes | 0.0078 | 20911 | 1384 |
| reviewer | deepseek-v4-pro | R2 | 1 | yes | 0.0051 | 16201 | 906 |
| reviewer | deepseek-v4-pro | R2 | 2 | yes | 0.0053 | 12459 | 936 |
| reviewer | deepseek-v4-pro | R2 | 3 | yes | 0.0044 | 12297 | 785 |
| reviewer | deepseek-v4-pro | R3 | 1 | yes | 0.0062 | 17572 | 1371 |
| reviewer | deepseek-v4-pro | R3 | 2 | yes | 0.0218 | 21683 | 1144 |
| reviewer | deepseek-v4-pro | R3 | 3 | yes | 0.0062 | 12180 | 858 |
| reviewer | deepseek-v4-pro | R4 | 1 | no | 0.0354 | 68592 | 2108 |
| reviewer | deepseek-v4-pro | R4 | 2 | yes | 0.0061 | 14575 | 725 |
| reviewer | deepseek-v4-pro | R4 | 3 | yes | 0.0056 | 11963 | 723 |
| implementer | deepseek-v4-pro | I1 | 1 | yes | 0.0059 | 28675 | 1080 |
| implementer | deepseek-v4-pro | I1 | 2 | no | 0.0047 | 20899 | 1005 |
| implementer | deepseek-v4-pro | I1 | 3 | yes | 0.0139 | 44363 | 1712 |
| implementer | deepseek-v4-pro | I2 | 1 | yes | 0.0109 | 35655 | 1482 |
| implementer | deepseek-v4-pro | I2 | 2 | yes | 0.0066 | 32699 | 1539 |
| implementer | deepseek-v4-pro | I2 | 3 | yes | 0.0083 | 26877 | 1327 |
| implementer | deepseek-v4-pro | I3 | 1 | yes | 0.0148 | 44804 | 1610 |
| implementer | deepseek-v4-pro | I3 | 2 | yes | 0.0589 | 314839 | 4058 |
| implementer | deepseek-v4-pro | I3 | 3 | yes | 0.0390 | 168886 | 3251 |
| investigator | deepseek-v4-pro | V1 | 1 | yes | 0.0170 | 60436 | 2815 |
| investigator | deepseek-v4-pro | V1 | 2 | yes | 0.0127 | 35848 | 1984 |
| investigator | deepseek-v4-pro | V1 | 3 | yes | 0.0107 | 27112 | 1669 |
| investigator | deepseek-v4-pro | V2 | 1 | yes | 0.0146 | 42135 | 2540 |
| investigator | deepseek-v4-pro | V2 | 2 | yes | 0.0168 | 39647 | 2793 |
| investigator | deepseek-v4-pro | V2 | 3 | yes | 0.0184 | 61649 | 2044 |
| investigator | deepseek-v4-pro | V3 | 1 | yes | 0.0835 | 469839 | 5691 |
| investigator | deepseek-v4-pro | V3 | 2 | yes | 0.0794 | 328582 | 4981 |
| investigator | deepseek-v4-pro | V3 | 3 | yes | 0.1072 | 502455 | 6104 |
