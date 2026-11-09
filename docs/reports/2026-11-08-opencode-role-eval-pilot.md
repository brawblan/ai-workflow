# Pilot of the role evals on OpenCode Go models

Issue [#302](https://github.com/brawblan/ai-workflow/issues/302), part of
[#301](https://github.com/brawblan/ai-workflow/issues/301). Date: 2026-11-08. Profile: `spike`.

## Result

- 21 of 21 runs finished with exit code 0. All 21 runs passed every outcome and contract check.
- The computed cost is $0.5839 at the published rates. The OpenCode `cost` field is 0 for each run.
- The harness facts are in the table below. Two facts need a change in the adapter design:
  role permissions need a deny-all first rule, and OpenCode gives no cost field.
- The scenarios are too small to rank the models. All three models pass every check. The matrix
  needs harder scenarios to give a quality signal.

## Method

- Harness: OpenCode 2.2.6. Plan: OpenCode Go.
- Models: `opencode-go/deepseek-v4.1-flash`, `opencode-go/glm-5.3-flash`,
  `opencode-go/kimi-k3.1-pro`.
- Baseline: the committed Claude Code results for `claude-sonnet-5-5`. No baseline run. The files are
  `evals/results/20261027-212939-role.implementer-claude-sonnet-5-5.md` and
  `evals/results/20261022-160145-role.tester-claude-sonnet-5-5.md`.
- Scope: `role.implementer` (I1 to I3) and `role.tester` (T1 to T4). One trial for each cell. Only
  the `with` variant. 21 runs.
- Each run used a temporary copy of the eval fixture. The copy had a hand-written
  `.opencode/agents/<role>.md` file. The file had the role text, the model, `steps: 60`, and an
  ordered permission list.
- The permission list starts with a deny-all rule. It then allows the tools of the role. File
  changes to `tests/` and to the check paths are denied for the implementer. File changes to `src/`
  are denied for the tester.
- The run command was:

```bash
opencode run --standalone --format json --auto --archived \
  --agent <role> --model <model> "<task and scenario prompt>"
```

- The environment had `OPENCODE_DISABLE_CLAUDE_CODE=1`, a `python` shim, and a fixed git identity.
- Grading used the existing `grade.py` of each eval and the `expect` list of each scenario. The
  checks are `acceptance`, `scope`, `names`, `decision_log`, `commit_trailer`, `unchanged`,
  `file_exists`, `matches`, `kills_mutants`, `passes_with_patch`, and `test_names`.
- The raw JSONL files and the workspaces are outside the repo. They are not committed.
- The cost uses the published token rates and the `step_finish` token counts. The cost adds the
  reasoning tokens to the output tokens. The DeepSeek rate is the off-peak rate. The date was a
  Sunday, so the whole run was off-peak.

## Facts to prove

| Fact | Command | Result |
| --- | --- | --- |
| Headless run | `opencode run --agent implementer --model <id> --format json --auto --archived "<prompt>"` | **Yes.** 21 of 21 runs finished with no prompt. `--auto` approves an `ask` rule. Without `--auto`, an `ask` rule is denied. OpenCode does not wait for a person. |
| Role file | `opencode debug agents` with `.opencode/agents/implementer.md` | **Partial.** The file sets `model`, `permissions`, `steps`, and the system prompt. A deny-all first rule is necessary. Without it, the default allow-all rule stays in force. In one probe, the model used the `execute` tool. `steps` is a model-step cap. The current role files have no equal field. |
| Report | A role run with no `StructuredOutput` tool | **Yes.** The final assistant text is the report. A T2 report matched the `@report` pattern. The role file must tell the model to put the report in its final message. |
| Metrics | `step_finish` events in the `--format json` output | **Partial.** Each event gives `tokens.input`, `tokens.output`, `tokens.reasoning`, `tokens.cache.read`, and `tokens.cache.write`. The `cost` field is 0. The CLI output has no `opencode.allowance` field. |
| Isolation | `opencode debug config`, with and without `OPENCODE_DISABLE_CLAUDE_CODE=1` | **Partial.** `debug config` lists `~/.config/opencode` and the project `.opencode`. There is no `--setting-sources project` flag. The env variable made no difference in the instruction probe. Use a workspace outside the repo and a clean global config. |
| Effort | `--model opencode-go/<model>#high` and `#bogus` | **Yes.** `#high` and `#low` work on all three models. `#bogus` fails with `provider.no-route` and "Variant unavailable". On one probe, `#high` gave 239 reasoning tokens and 155 output tokens. `#low` gave 0 and 3. |
| Limits | `opencode run --help`, and a role file with `steps: 2` | **Partial.** There is no `--max-budget-usd` flag and no cost limit. `steps: N` stops the run at N model steps. At the cap, OpenCode removes the tools and adds a "Maximum steps" message. |

## Evidence

The lines below are excerpts from the run output. The raw files are outside the repo.

```text
# opencode debug agents (one agent)
"id": "implementer",
"model": {"id": "deepseek-v4.1-flash", "providerID": "opencode-go"},
"system": "You are the implementer. ...",
"steps": 60,
"permissions": [{"action": "*", "resource": "*", "effect": "deny"}, ...]

# one step_finish event
{"type": "step_finish", "part": {"type": "step-finish", "reason": "stop", "cost": 0,
 "tokens": {"input": 8763, "output": 2880, "reasoning": 531,
            "cache": {"read": 53760, "write": 0}}}}

# --model ...#bogus
{"type": "error", "error": {"type": "provider.no-route",
 "message": "Variant unavailable for opencode-go/deepseek-v4.1-flash: bogus"}}

# a role file with steps: 2, after 2 model steps
Maximum steps for this agent have been reached, so I can't continue with further tool calls.

# --agent asker, shell permission "ask", no --auto
The `ls` shell command was rejected by the sandbox's permission policy, ...

# --agent asker, shell permission "ask", with --auto
`ls` shows one entry:
- `README.md`
```

## Metrics

Each row is one run. Cost is in USD.

| Scenario | Model | Pass | Cost | Steps | Tools | Tool bytes | Wall s | In | Out | Reasoning | Cache read | Cache write |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| I1 | `deepseek-v4.1-flash` | yes | 0.0035 | 11 | 13 | 7903 | 31.6 | 8763 | 2880 | 531 | 53760 | 0 |
| I1 | `glm-5.3-flash` | yes | 0.0017 | 6 | 6 | 1182 | 17.0 | 5972 | 840 | 0 | 11968 | 0 |
| I1 | `kimi-k3.1-pro` | yes | 0.0487 | 11 | 10 | 3156 | 99.4 | 1134 | 1918 | 849 | 39936 | 5376 |
| I2 | `deepseek-v4.1-flash` | yes | 0.0033 | 11 | 13 | 9069 | 28.1 | 7251 | 2281 | 1077 | 55168 | 0 |
| I2 | `glm-5.3-flash` | yes | 0.0028 | 9 | 9 | 3282 | 29.6 | 8845 | 1312 | 274 | 22848 | 0 |
| I2 | `kimi-k3.1-pro` | yes | 0.0876 | 15 | 16 | 3458 | 185.4 | 1691 | 3112 | 2399 | 78848 | 6656 |
| I3 | `deepseek-v4.1-flash` | yes | 0.0054 | 7 | 9 | 4052 | 28.5 | 28891 | 1517 | 232 | 0 | 0 |
| I3 | `glm-5.3-flash` | yes | 0.0027 | 8 | 8 | 2771 | 35.6 | 7790 | 1242 | 623 | 20672 | 0 |
| I3 | `kimi-k3.1-pro` | yes | 0.0798 | 12 | 19 | 3797 | 163.2 | 1318 | 2781 | 2404 | 59904 | 6656 |
| T1 | `deepseek-v4.1-flash` | yes | 0.0077 | 9 | 10 | 3745 | 46.3 | 38161 | 2607 | 630 | 5632 | 0 |
| T1 | `glm-5.3-flash` | yes | 0.0025 | 8 | 8 | 2550 | 21.7 | 8368 | 1177 | 137 | 18496 | 0 |
| T1 | `kimi-k3.1-pro` | yes | 0.0996 | 12 | 16 | 4219 | 200.8 | 1279 | 2945 | 3616 | 75008 | 8192 |
| T2 | `deepseek-v4.1-flash` | yes | 0.0031 | 10 | 11 | 7284 | 29.9 | 7433 | 2671 | 465 | 44800 | 0 |
| T2 | `glm-5.3-flash` | yes | 0.0026 | 8 | 8 | 4154 | 24.9 | 9206 | 1149 | 164 | 19584 | 0 |
| T2 | `kimi-k3.1-pro` | yes | 0.0639 | 9 | 12 | 5101 | 135.9 | 1013 | 2373 | 1911 | 41472 | 5376 |
| T3 | `deepseek-v4.1-flash` | yes | 0.0032 | 7 | 9 | 4323 | 23.2 | 4721 | 3467 | 612 | 30464 | 0 |
| T3 | `glm-5.3-flash` | yes | 0.0029 | 9 | 8 | 3011 | 28.9 | 8658 | 1410 | 221 | 25024 | 0 |
| T3 | `kimi-k3.1-pro` | yes | 0.0615 | 10 | 15 | 2902 | 126.9 | 1127 | 2217 | 1867 | 43520 | 4864 |
| T4 | `deepseek-v4.1-flash` | yes | 0.0080 | 9 | 10 | 5856 | 45.1 | 40994 | 1944 | 1045 | 7552 | 0 |
| T4 | `glm-5.3-flash` | yes | 0.0031 | 10 | 12 | 5344 | 31.2 | 8251 | 1348 | 203 | 34816 | 0 |
| T4 | `kimi-k3.1-pro` | yes | 0.0904 | 11 | 18 | 6499 | 183.2 | 1270 | 2700 | 3231 | 66048 | 7680 |

Role totals:

| Role | Model | Runs | Pass | Mean cost | Mean steps | Mean tools | Mean tool bytes | Mean wall s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Implementer | `deepseek-v4.1-flash` | 3 | 3 | 0.0122 | 9.7 | 11.7 | 7008 | 29.4 |
| Implementer | `glm-5.3-flash` | 3 | 3 | 0.0072 | 7.7 | 7.7 | 2412 | 27.4 |
| Implementer | `kimi-k3.1-pro` | 3 | 3 | 0.2160 | 12.7 | 15.0 | 3470 | 149.3 |
| Tester | `deepseek-v4.1-flash` | 4 | 4 | 0.0220 | 8.8 | 10.0 | 5302 | 36.1 |
| Tester | `glm-5.3-flash` | 4 | 4 | 0.0110 | 8.8 | 9.0 | 3765 | 26.7 |
| Tester | `kimi-k3.1-pro` | 4 | 4 | 0.3154 | 10.5 | 15.2 | 4680 | 161.7 |

The baseline from the committed results:

| Role | Model | Variant | Mean cost | Outcome | Contract |
| --- | --- | --- | --- | --- | --- |
| Implementer | `claude-sonnet-5-5` | with | 0.0367 | 1.00 | 0.89 |
| Implementer | `claude-sonnet-5-5` | without | 0.0900 | 0.67 | 0.00 |
| Tester | `claude-sonnet-5-5` | with | 0.0750 | 1.00 | 1.00 |
| Tester | `claude-sonnet-5-5` | without | not measured | not measured | not measured |

## Cost of one eval run, and the matrix estimate

"Full eval" means one trial of every scenario of the role, both variants. The pilot measured only
the `with` variant. The table estimates the `without` variant at the same cost as `with`. Treat the
values as estimates.

| Model | Implementer full eval | Tester full eval | 3-trial matrix, both roles | Monthly cap | Share of cap |
| --- | --- | --- | --- | --- | --- |
| `deepseek-v4.1-flash` | 0.0243 | 0.0441 | 0.2052 | $100 | 0.2% |
| `glm-5.3-flash` | 0.0144 | 0.0220 | 0.1093 | $60 | 0.2% |
| `kimi-k3.1-pro` | 0.4321 | 0.6308 | 3.1887 | $15 | 21.3% |
| `claude-sonnet-5-5` | 0.3800 | 0.6000 | 2.9400 | subscription | not applicable |

- The #304 matrix is 3 trials of 2 roles on 4 models, with both variants.
- The estimate for the plan models is $3.50. The baseline estimate is $2.94. The total is $6.44.
- The estimate assumes the `without` cost is equal to the `with` cost. The baseline tester `without`
  result does not exist. This is a known gap.
- Kimi K3.1 Pro uses 21% of its monthly cap in one matrix. DeepSeek and GLM use less than 1%.
- The monthly caps come from the OpenCode Go plan page, read on 2026-11-08. The page can change.

## Harness-dependent scenarios and graders

| Item | Dependence | Proposed change |
| --- | --- | --- |
| `framework/adapters/claude-code/eval.yaml` | The run argv, `--setting-sources`, `--max-budget-usd`, and the `result` event with dotted output paths | Add an OpenCode `eval.yaml` and a JSONL parser (#303). |
| `StructuredOutput` in the six role files | That tool is not in OpenCode | The role returns the report as its final message. The parser reads the final assistant text. |
| `--setting-sources project` | OpenCode has no equal flag | Start the run in a clean workspace. Keep the global OpenCode config empty. Record this limit in the adapter. |
| `--max-budget-usd` | OpenCode has no cost limit | Use `steps` as a turn cap. Track the cost from the token counts. Stop the batch at the local cap. |
| `--allowedTools` | OpenCode uses ordered `permissions` | Write a deny-all first rule, then the allows. Add a test that `execute` and `subagent` are denied. |
| `evals/README.md` | It names `claude-opus-5-5` and `stone eval` with no harness | Add a harness column and the `--run-config` form. |
| `evals/results/*.md` | The header names only the model | Add the harness to each result (#303, acceptance criterion 7). |
| `role.tester` T2 `matches @report` | The report is the last assistant text | Join the text parts of the final assistant message. Do not use only the last `text` event. |
| `trigger.*`, `hook.*`, `guidance.*` evals | They need a render, a hook, or `--allowedTools` | Mark them "not supported" in the OpenCode `eval.yaml`. `stone eval` must say so. |
| `evals/role-tester` and `evals/role-implementer` commands | The prompt says `python`. The machine has `python3`. | Keep the prompt. Put a `python` shim on PATH, or change the eval command. |

The git checks are harness-neutral: `unchanged`, `commit_trailer`, and `file_exists`. The `grade.py`
files are harness-neutral. They use `sys.executable` and git.

## Limits

- One trial for each cell. The pass rates have no confidence interval.
- Only the `with` variant. The pilot cannot show the role effect.
- All 21 runs pass. The scenarios are at a ceiling. The data cannot rank quality.
- The role files are hand-written for the pilot. `stone render` did not write them.
- The tool bytes come from the tool output text. The count can differ from the Claude parser.
- The `cost` field is 0. The cost values are estimates from published rates.
- The DeepSeek rate is the off-peak rate. The pilot did not test a peak-hour run.
- The pilot did not run a guidance eval, a trigger eval, or a hook eval.
- The monthly caps and the rates can change.
- The model variants have one probe each. The pilot did not measure effort on a full scenario.
- The pilot ran no CI job. The plan key stays on the owner's computer.

## Reproduction

1. Copy the fixture of the scenario to a temporary folder.
2. Run `git init -b main`, commit the fixture, and apply the `change` diff.
3. Add `.opencode/agents/<role>.md` with the role text and the model.
4. Run the command in "Method".
5. Run the grader of each `expect` item on the workspace. Example:

```bash
python evals/role-implementer/grade.py acceptance --workspace <workspace> \
  --args '{"test": "acceptance/NOTE-21.py"}'
python evals/role-tester/grade.py kills_mutants --workspace <workspace> \
  --args '{"mutants": ["mutants/slugify-m1-no-lower.diff"]}'
```

The `stone check` and K17 checks pass on this report.
