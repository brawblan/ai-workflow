# OpenCode Go model research (2026-11-09)

Research date: 2026-11-09. Source ticket: #308 (part of #301). The first model matrix (#304) and the economy and quality picks (#305) use this report as the source of their model list.

Every recommendation is a hypothesis to test. None is a decision.

## 0. How to read this report

| Item | Meaning |
| --- | --- |
| Confidence rules | High: two or more independent sources agree, and one is an agentic benchmark. Medium: one benchmark, or many agreeing user reports. Low: a vendor claim, or one user report. |
| Result | No recommendation reaches high. No source ran the current Go models in an OpenCode agent loop with a published pass rate. Public benchmark numbers are mostly vendor claims or aggregator copies. |
| Evidence limits | Several pages were read through a summarizer, and aggregator pages are not primary. Treat every number as "reported", not "verified". |
| Variant names | Names come from the `reasoning_options` field in the models.dev catalog. OpenCode shows variants from this catalog. I did not run a model (no Go key on this machine), so no name is confirmed in the UI. Issues #54801 and #62264 show that a declared ladder can be missing at run time. |
| Not found | Items marked "not found" had no source. |

## 1. Summary

Top 3 Go models to test first for `role.implementer` and `role.tester` in the #304 matrix:

| # | Model and variant | Reason | Main risk |
| --- | --- | --- | --- |
| 1 | `opencode-go/deepseek-v4.1-flash#high` | Lowest price among strong candidates ($0.15 in, $0.60 out, $0.003 cache read). Highest Go cap ($100 a month). Top token share on OpenRouter for the week of 2026-11-02 (usage data). A source calls Flash a "volume workhorse". This is the best economy-pick candidate. | A reasoning-only stop ends the agent with no error (issue #55378, seen on this model family). Vendor claims are the only agentic scores. |
| 2 | `opencode-go/glm-5.3#high` (compare with `#max`) | Vendor claims strong agentic coding (DeepSWE 66.9, Terminal-Bench 3.0 28.3). Medium price ($1.40 in, $4.40 out). Z.ai reports `max` uses about 75K output tokens and `high` about 50K for 34.5% and 31.4% (vendor). This gives a direct test of effort cost. | The Go cap is only $15 a month on the docs page. Z.ai numbers are vendor claims. |
| 3 | `opencode-go/kimi-k3.1-pro#high` (compare with `#max`) | Newest and most capable Kimi on the list (vendor, 2026-10-23). Third in OpenRouter weekly tokens, up 91% (usage data). This is the best quality-pick candidate. | $2 in, $10 out, and a $15 cap. The matrix can use the cap fast. Scores are vendor claims. |

Reserve list, in this order: `kimi-k2.7-code` (coding-tuned, $60 cap), `glm-5.3-flash#high` ($60 cap), `claude-haiku-5-5#medium` (same family as the baseline), `gpt-6-luna#medium`.

Largest gaps:

| Gap | Effect |
| --- | --- |
| No independent agentic score for the current Go models | All ranks are weak. The matrix must decide. |
| The Go cap is one shared pool (user reports), not one cap for each model (docs) | One expensive model can lock the whole matrix for 5 hours. |
| No cost or turn data for any task | "Cost for each passing run" is unknown for every model. |

## 2. Model list

Source: `opencode models` (OpenCode 2.2.6), the Go docs page, and the models.dev catalog (all read 2026-11-09). Prices are in dollars per million tokens. "Cap" is the monthly dollar limit on the Go plan, from the docs page. The docs also give the 5-hour limit as 20% of the cap and the weekly limit as 50%. User reports say the pool is shared (see section 6).

A dash means that the price is not listed. Prices in brackets apply above the context size that is shown.

| Model (`opencode-go/…`) | Vendor | Variants (catalog `effort` values) | Context | Input | Output | Cache read | Cache write | Cap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `deepseek-v4.1-flash` | DeepSeek | low, high, max | 1.0M | 0.15 (docs: 0.15–0.30 peak) | 0.60 (docs: 0.60–1.20) | 0.003 | — | $100 |
| `deepseek-v4-pro` | DeepSeek | high, max | 1.0M | 0.66 (docs: 0.66–1.32) | 1.98 (docs: 1.98–3.96) | 0.022 | — | $15 |
| `glm-5.3` | Z.ai | low, high, max | 1.0M | 1.40 | 4.40 | 0.26 | — | $15 |
| `glm-5.3-flash` | Z.ai | low, high, max | 1.0M | 0.15 | 0.50 | 0.03 | — | $60 |
| `glm-5.2` | Z.ai | high, max | 1.0M | 1.40 | 4.40 | 0.26 | — | $60 |
| `kimi-k3.1-pro` | Moonshot | low, high, max | 1.05M | 2.00 | 10.00 | 0.20 | 2.00 | $15 |
| `kimi-k3` | Moonshot | max | 1.05M | 3.00 | 15.00 | 0.30 | 3.00 | $15 |
| `kimi-k2.7-code` | Moonshot | none found | 262K | 0.95 | 4.00 | 0.19 | — | $60 |
| `mimo-v2.6-pro` | Xiaomi | none found | 1.05M | 0.435 | 0.87 | 0.0036 | — | $15 |
| `mimo-v2.6-flash` | Xiaomi | none found | 1.05M | 0.14 | 0.28 | 0.0028 | — | $60 |
| `mimo-v2.5-pro` | Xiaomi | none found | 1.05M | 0.435 | 0.87 | 0.0036 | — | $15 |
| `mimo-v2.5` | Xiaomi | none found | 1.0M | 0.14 | 0.28 | 0.0028 | — | $60 |
| `qwen3.8-max` | Alibaba | toggle; low, medium, xhigh; token budget | 1.0M | 2.00 | 6.00 | 0.25 | 2.50 | $15 |
| `qwen3.8-flash` | Alibaba | toggle; low, medium, xhigh; token budget | 1.0M | 0.15 | 0.47 | 0.016 | 0.20 | $30 |
| `qwen3.7-plus` | Alibaba | toggle; token budget | 1.0M | 0.40 (1.20 above 256K) | 1.60 (4.80) | 0.04 | 0.50 | $60 |
| `minimax-m3` | MiniMax | toggle | 1.0M | 0.30 (0.60 above 512K) | 1.20 (2.40) | 0.06 | — | $60 |
| `minimax-m3.1-flash` | MiniMax | low, medium, high, xhigh, max | 1.0M | 0.15 | 0.60 | 0.015 | — | $20 |
| `claude-haiku-5-5` | Anthropic | toggle; low, medium, high, xhigh, max | 1.0M | 0.10 (0.50 above 100K) | 0.50 (2.50) | 0.01 | 0.125 | $15 |
| `gpt-6-luna` | OpenAI | none, low, medium, high, xhigh, max | 1.05M | 0.10 (0.20 above 272K) | 0.50 (0.75) | 0.01 | 0.125 | $15 |
| `gpt-5.6-luna` | OpenAI | none, low, medium, high, xhigh, max | 1.05M | 0.20 (0.40 above 272K) | 1.20 (1.80) | 0.02 | 0.25 | $15 |
| `grok-4.7` | xAI | low, medium, high, xhigh | 500K | 2.00 (4.00 above 200K) | 6.00 (12.00) | 0.50 | — | $15 |
| `gemini-4-argon` | Google | low, medium, high | 1.05M | 2.00 (docs: 50% discount to 2026-11-30) | 10.00 | 0.10 | — | $30 |
| `step-5-preview` | StepFun | low, medium, high | 1.0M | 1.00 | 2.70 | 0.10 | — | $15 |
| `hy4` | Tencent | none, high | 1.05M | 0.834 | 2.501 | 0.042 | — | $60 |
| `hy4-preview` | Tencent | none, high | 1.02M | 0.834 | 2.501 | 0.042 | — | $30 |
| `hy3` | Tencent | none, low, high | 256K | 0.14 | 0.58 | 0.035 | — | $60 |
| `longcat-2.0` | Meituan | toggle | 1.0M | 0.30 | 1.20 | 0.006 | — | $60 |
| `muse-spark-1.3-contributor` | Meta | minimal, low, medium, high, xhigh | 1.05M | 0.10 | 0.20 | 0.002 | — | $60 (training data allowed) |
| `muse-spark-1.2-contributor` | Meta | minimal, low, medium, high, xhigh | 1.05M | 0.10 | 0.20 | 0.002 | — | $60 (training data allowed) |
| `beam-free`, `crouton-alpha-free` | stealth | low…max / minimal…max | 1.05M | free | free | free | — | unlimited, limited time |
| `iceman-contributor-free`, `longcat-2.5-free` | stealth, Meituan | none found / toggle | 262K / 1.0M | free | free | free | — | unlimited, limited time |

Notes:
- `opencode models` listed 33 Go models. The task text says about 38. The difference is not found.
- Usage syntax: `--model opencode-go/glm-5.3#max`.
- A name marked "toggle" has an on/off switch. The exact variant name for it is not found.
- Cap vs real use: one source (2026-08-03, older model set) reports about 110 requests per 5 hours for Kimi K3. It reports about 31,650 for DeepSeek V4 Flash. The spread between models is large.

## 3. Recommendations by task kind

Common notes for all tables:
- All rows are hypotheses. Confidence uses the rules in section 0.
- Evidence labels: [V] vendor claim, [U] user report, [D] usage data, [C] catalog or docs.
- Links are in section 8. Short names are used here.

### 3.1 Shape a ticket (shaper)

The shaper holds a short interview and reads a few files. Context is small. Volume is low.

| When to use | Model | Variant | Why | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| Default. The ticket is vague or has many gaps. | `kimi-k3.1-pro` | `high` | Strongest Kimi. Cost is small because the context is small. | Kimi K3.1 Pro post (2026-10-23) [V]; OpenRouter (2026-11-08) [D] | Low |
| The ticket is mostly clear. You want the lowest cost. | `deepseek-v4.1-flash` | `high` | Cheapest strong model. Gap finding needs reading, not long loops. | OpenRouter [D]; bitdoze (2026-08-03) [U] | Low |
| The ticket touches security or data. | `glm-5.3` | `max` | Z.ai reports its best security results on this model. | Z.ai GLM-5.3 doc [V] | Low |

### 3.2 Plan a change that touches many files (planner)

| When to use | Model | Variant | Why | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| The change crosses modules and the context is above 200K tokens. | `kimi-k3.1-pro` | `max` | 1M context. A blog says Kimi K3 is steady over many steps. | buildfast (2026-08-17) [U]; Kimi post [V] | Low |
| The change is large and you want a second family. | `glm-5.3` | `max` | Vendor says `max` is for complex coding. | Z.ai doc [V] | Low |
| Economy. The plan has 5 files or fewer. | `deepseek-v4.1-flash` | `max` | Cheap thinking. Test whether `max` beats `high` on plan quality. | bitdoze, vanja.io (2026-09-16): "do not run a thinking-mode novel for a mechanical edit" [U] | Low |

### 3.3 Small change from a clear ticket (implementer)

| When to use | Model | Variant | Why | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| The ticket is clear and the change is in 1 or 2 files (Python, TypeScript, shell, Markdown). | `deepseek-v4.1-flash` | `high` | Lowest cost and highest cap. | OpenRouter [D]; vendor Terminal-Bench 2.1 score 90.6% via bitdoze [V] | Low |
| Same size, but you need a high cap or a second family. | `glm-5.3-flash` | `high` | $60 cap, $0.15/$0.50. A user report shows output damage on very long context. Keep context under 200K. | OpenRouter [D]; issue #62900 (2026-11-09) [U] | Low |
| The change is in Rust or has a security or data-loss risk. | `glm-5.3` | `high` | Stronger model. `high` uses fewer output tokens than `max` (vendor). | Z.ai doc [V] | Low |
| You want the same family as the Claude baseline. | `claude-haiku-5-5` | `medium` | Same prompts and tool habits as the baseline. Token counts compare with the baseline. | Catalog [C]. No benchmark found. | Low |

### 3.4 Large change or refactor across modules (implementer)

| When to use | Model | Variant | Why | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| The change touches 5 files or more, or moves code between modules. | `glm-5.3` | `max` | Vendor says long-horizon coding. DeepSWE 66.9 (vendor). | Z.ai doc [V] | Low |
| Same size. You need steady behavior over many steps. | `kimi-k3.1-pro` | `high` | Kimi is reported as steady in long agent loops. | buildfast (2026-08-17) [U] | Low |
| Repo-wide work with a $60 cap. The context is under 262K tokens. | `kimi-k2.7-code` | none found | Catalog text: stronger on long-horizon repo work, less overthinking. | Catalog description [C] | Low |

### 3.5 Write tests from the acceptance criteria (tester)

The tester must not change source code. Test a different family from the implementer.

| When to use | Model | Variant | Why | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| Default. Python or Rust tests from clear criteria. | `glm-5.3` | `high` | Strong instruction following is reported for GLM on structured tasks. | Z.ai doc [V]. No test-writing score found. | Low |
| Economy. The criteria are short and the code is small. | `deepseek-v4.1-flash` | `high` | Lowest cost. The role needs reading, writing, and running tests. | OpenRouter [D] | Low |
| The implementer used DeepSeek, and you want independent errors. | `kimi-k2.7-code` | none found | Another family. The cap is $60. | Catalog [C] | Low |

### 3.6 Review a diff for defects and scope drift (reviewer)

| When to use | Model | Variant | Why | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| Default, and any change with security or data risk. | `kimi-k3.1-pro` | `high` | Highest quality candidate. The loop is short, so cost is small. | Kimi post [V] | Low |
| Same risk. You want a second opinion from another family. | `glm-5.3` | `max` | Z.ai reports its best defensive-security result here (CyberGym 84.5%). | Z.ai doc [V] | Low |
| Economy. The diff is small and the checks pass. | `deepseek-v4.1-flash` | `max` | Cheap. Test whether `max` finds more defects than `high`. | bitdoze [U] | Low |

Use a reviewer model that differs from the implementer model. This is a design idea. No source tested it.

### 3.7 Investigate a bug in unknown code (investigator)

| When to use | Model | Variant | Why | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| The code base is large and the agent must read much. | `glm-5.3` | `max` | 1M context. Vendor says long-horizon agent work. | Z.ai doc [V] | Low |
| The bug path is unclear, and the work needs many steps. | `kimi-k3.1-pro` | `high` | Reported as steady over many steps. | buildfast [U] | Low |
| Economy. First pass to locate files. | `qwen3.8-flash` | `low` | 1M context, $0.15/$0.47, $30 cap. No agentic evidence found. | Catalog [C] | Low |

### 3.8 Find the cause of a CI failure from its logs

Logs are long and the reasoning is short. Cache reads matter.

| When to use | Model | Variant | Why | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| Default. The log is long and the failure is a clear error. | `deepseek-v4.1-flash` | `low` | Cache read is $0.003. The cap is $100. | Catalog [C]; OpenRouter [D] | Low |
| The cause spans several steps or jobs. | `glm-5.3-flash` | `high` | $60 cap. Cheap. | Catalog [C] | Low |
| The log is above 500K tokens. | `gpt-6-luna` | `medium` | 1.05M context, $0.10 input. A price step applies above 272K tokens. | Catalog [C]. No benchmark found. | Low |

### 3.9 Write docs in controlled English (ASD-STE100)

K17 checks the output. Use K17 pass count as the score.

| When to use | Model | Variant | Why | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| Default. A new doc or a rewrite with strict word rules. | `kimi-k3.1-pro` | `low` | Strong instruction following is expected. Low effort saves cost. | No source found. Hypothesis only. | Low |
| Economy. A short change of an existing doc. | `claude-haiku-5-5` | `medium` | Same family as the baseline writer. | No source found. | Low |
| You need a cheap draft before a K17 pass. | `deepseek-v4.1-flash` | `low` | Lowest cost. | Catalog [C] | Low |

### 3.10 Quick work for a main session (search, summary, compaction)

| When to use | Model | Variant | Why | Evidence | Confidence |
| --- | --- | --- | --- | --- | --- |
| Code search or a file summary. | `glm-5.3-flash` | `low` | Cheap and fast. $60 cap. | OpenRouter [D] | Low |
| The task is high volume (many small calls). | `deepseek-v4.1-flash` | `low` | $100 cap. Cheapest cache read. | Catalog [C] | Low |
| Compaction of a session below 200K tokens. | `mimo-v2.6-flash` | none found | $0.14/$0.28. $60 cap. Tool-call defects (section 5) matter less in a no-tool task. | Catalog [C] | Low |

Keep compaction input under 200K tokens. Issue #62900 reports repeated, damaged output at about 294K tokens on `glm-5.3-flash` (through a third-party provider).

## 4. Starting picks for #305

Rules from #305: Economy is the lowest cost for each passing run, with a pass rate within 1 standard error of the baseline. Quality is the highest pass rate, with a cost for each passing run not above the baseline. Baseline is the role model in the claude-5 profile. No pick is valid until a role has 3 or more trials for each scenario.

| Role | Baseline (claude-5) | Starting economy idea | Starting quality idea | Confidence |
| --- | --- | --- | --- | --- |
| shaper | claude-opus-5-5 | `deepseek-v4.1-flash#high` | `kimi-k3.1-pro#high` | Low |
| planner | claude-opus-5-5 | `deepseek-v4.1-flash#max` | `kimi-k3.1-pro#max` | Low |
| implementer | claude-sonnet-5-5 | `deepseek-v4.1-flash#high` | `glm-5.3#high` | Low |
| tester | claude-sonnet-5-5 | `deepseek-v4.1-flash#high` | `glm-5.3#high` | Low |
| reviewer | claude-opus-5-5 | `deepseek-v4.1-flash#max` | `kimi-k3.1-pro#high` | Low |
| investigator | claude-opus-5-5 | `qwen3.8-flash#low` | `glm-5.3#max` | Low |

Notes:
- The baseline runs in Claude Code, and the new models run in OpenCode. A difference in pass rate can come from the harness, not from the model. The matrix cannot separate these two causes alone. Also run a Claude model in OpenCode: `opencode-go/claude-haiku-5-5`, or `opencode/claude-sonnet-5-5` (in the model list, not in the Go plan).
- Cost at published rates, not a measured cost. Measured cost for each passing run is not found for any model.

## 5. Models to avoid (for the first matrix)

| Model | Reason | Evidence | Confidence |
| --- | --- | --- | --- |
| `qwen3.8-max` | About 160 requests per 5 hours. One user ran out of this cap and was locked out of all paid Go models. It can stop the whole matrix. | Issue #54875 (2026-10-12) [U]; bitdoze (2026-08-03) [U] | Medium |
| `kimi-k3` | `kimi-k3.1-pro` costs less ($2/$10 vs $3/$15) and is newer. About 110 requests per 5 hours (older source). | Catalog [C]; bitdoze (2026-08-03) [U] | Low |
| `deepseek-v4-pro` | Reports of tool-call loops when history is long, and of HTTP 400 errors when `reasoning_content` is not sent back. These come from search snippets that I did not fetch. One source says Flash can match Pro for daily work. | Search snippets (Cursor forum, oh-my-openagent issue); pasqualepillitteri (2026-08-13) [U] | Low |
| `mimo-v2.6-pro`, `mimo-v2.6-flash` (as implementer or tester) | Tool-name selection can collapse to `bash` after many `bash` calls (issue #57584). `xhigh` is rejected with "not valid JSON" (issue #60868). A vendor note says the repetition fix is in later checkpoints. | Issues #57584 (2026-10-21), #60868 (2026-10-31) [U]; bitdoze [V/secondary] | Low |
| `gemini-4-argon` | Reports of HTTP 403 "Endpoint is unavailable" on Go (issues #61845, #61873, now closed). Retest before use. | Issues, 2026-11-06 [U] | Low |
| `hy4`, `hy4-preview`, `step-5-preview`, `longcat-2.0`, `minimax-m3` | No agentic score and no user report found. `hy4` was still a preview in one source. | bitdoze (undated, 2026-10) | Low |
| `muse-spark-*-contributor`, `iceman-contributor-free` | "Training data allowed" and limited regions. Use only for public data. | Go docs page [C] | Medium |
| Free models (`beam-free`, `crouton-alpha-free`, `longcat-2.5-free`) | Limited time and limited regions. Reasoning-only stops were seen on free models in issue #55378. Results would not be repeatable. | Issue #55378 (2026-10-14) [U]; Go docs [C] | Low |
| `gpt-5.6-luna`, `gpt-6-luna` for tool-heavy loops | Hosted `web_search` is dropped on the Go route (issue #61614). The model is served on the `/responses` endpoint, so check the route first. | Issues #61614, #47463 [U] | Low |

## 6. Points where the sources disagree

| Topic | Side A | Side B | Note |
| --- | --- | --- | --- |
| Go caps | Docs: each model has its own limit (5-hour 20%, weekly 50%, monthly 100% of its cap). | Users: one pool, shared by all paid models. A maintainer bot agreed that the docs do not match (issue #60311, 2026-10-29). Free models still work after a lock-out. | Medium confidence that the pool is shared. Plan the matrix for one pool. |
| Cap of DeepSeek V4.1 Flash | Docs page: $100 a month. | A search summary of an aggregator: $80. | Not resolved. Use the docs value and check the console. |
| Flash vs Pro (DeepSeek) | One source: Flash may deliver more than Pro for daily work. | Vendor and price tables rank Pro above Flash. | No test found. Test both. |
| Terminal-Bench numbers | Aggregator copy of vendor claims: Terminal-Bench 2.1 above 84% for many models (DeepSeek V4.1 Flash 90.6%, Kimi K3 88.3%). | BenchLM (2026-11-07) shows Terminal-Bench 2.0 scores of 56.9–70.3% for the previous generation. Kimi's own post gives 65.7% on Terminal-Bench 4.0. | The versions differ (2.0, 2.1, 3.0, 4.0). Do not compare across them. |
| GLM-5.3 vs Kimi K3 | A blog: GLM-5.3 beats DeepSeek V4-Pro on agentic coding. | The same blog: Kimi K3 is a little behind on peak scores but steadier on long tasks. | Both are secondary. Test steadiness with trials. |
| Variant names | Catalog: `kimi-k3` has only `max`; MiMo has none. | Issue #60868: MiMo accepts `low`, `medium`, `high`, `max` on the API, and rejects `xhigh`. Issues #54801 and #62264: a declared ladder can be missing for MiniMax. | Confirm the variant list in the OpenCode UI before each run. |
| Effort cost | Z.ai: `max` gives 34.5% at about 75K output tokens, `high` gives 31.4% at about 50K. | No independent source. | Test whether +3 points is worth +50% output tokens. |

## 7. Questions that only an eval can answer

Phrase: a test for the #304 matrix. Each test uses 3 trials or more for each cell.

| # | Test | What it decides |
| --- | --- | --- |
| 1 | Run `role.implementer` on `deepseek-v4.1-flash#high`, `glm-5.3#high`, `kimi-k3.1-pro#high`, and the claude-5 baseline. Compare cost for each passing run. | The first economy and quality picks |
| 2 | Run `role.tester` on the same models. Count how often the model edits source code. | Role discipline (the tester must not change source) |
| 3 | Run `glm-5.3` at `high` and `max`, and `kimi-k3.1-pro` at `high` and `max`. Compare pass rate and output tokens. | Whether the higher effort pays for itself |
| 4 | Count reasoning-only stops (no text, no tool call) for each model over all runs. | Whether issue #55378 harms `deepseek-v4.1-flash` |
| 5 | Run one Claude model through OpenCode, and the same model through Claude Code. Compare pass rates. | The size of the harness effect (needed to read all other results) |
| 6 | Record the Go console usage after each model. Run one model until the 5-hour limit, then call another model. | Whether the cap is one pool or one cap for each model |
| 7 | Run the same task at 100K and at 300K tokens of context on `glm-5.3-flash`. Check output damage and repetition. | The safe context size for compaction and quick work |
| 8 | Run `deepseek-v4.1-flash` at peak and at off-peak times. Compare cost and wall time. | Whether peak pricing changes the economy pick |
| 9 | Run a ticket set in Rust and a set in Python on the top 3 models. | Whether language changes the order |
| 10 | Pair implementer and reviewer: same family and different family. Count defects found. | The independent-reviewer idea (section 3.6) |
| 11 | Run `claude-haiku-5-5#medium` and `gpt-6-luna#medium` on `role.implementer`. | Whether a cheap closed model beats open models on cost for each passing run |
| 12 | Run the Cornerstone K17 check on STE docs from three models. | The model for task kind 9 (no evidence found) |
| 13 | List the variants of each candidate with the OpenCode UI. Compare with section 2. | Exact variant names |
| 14 | Record turns, tool bytes, and cost for each run. | The first cost-for-each-passing-run table (not found in any source) |

Matrix size warning: 3 models, 2 evals, N scenarios, 3 trials. A $15 cap on `glm-5.3` or `kimi-k3.1-pro` can run out before the matrix ends. Run the models with high caps first, and run the $15-cap models in separate 5-hour windows.

## 8. Sources

Types: benchmark, user report, vendor claim, usage data, docs. "Read" means that I opened the page. "Snippet" means that I saw only a search result.

### 8.1 Used

| Link | Date | Type | Use |
| --- | --- | --- | --- |
| https://opencode.ai/docs/go/ | undated, read 2026-11-09 | docs / vendor | Model list, caps, prices, endpoints |
| https://models.dev/api.json (provider `opencode-go`) | read 2026-11-09; model release dates 2026-04-22 to 2026-11-04 | docs (catalog) | Context, cache prices, variant values |
| `opencode models`, OpenCode 2.2.6 | run 2026-11-09 | docs (CLI) | Count of 33 Go models |
| https://opencode.ai/docs/models/ | undated, read 2026-11-09 | docs | Variant syntax `provider/model#variant` |
| https://openrouter.ai/rankings | week 2026-11-02 to 2026-11-08 | usage data | Weekly token share |
| https://github.com/anomalyco/opencode/issues/60311 | 2026-10-29 | user report | Shared Go pool |
| https://github.com/anomalyco/opencode/issues/54875 | 2026-10-12 | user report | Lock-out after `qwen3.8-max` |
| https://github.com/anomalyco/opencode/issues/49014 | closed 2026-11-06 | user report | Same lock-out |
| https://github.com/anomalyco/opencode/issues/47463 | 2026-09-05 | user report | Endpoint errors for some Go models |
| https://github.com/anomalyco/opencode/issues/55378 | 2026-10-14 | user report | Reasoning-only stop |
| https://github.com/anomalyco/opencode/issues/57584 | 2026-10-21 | user report | `mimo-v2.6-pro` tool-name collapse |
| https://github.com/anomalyco/opencode/issues/60868 | 2026-10-31 | user report | `xhigh` rejected on MiMo |
| https://github.com/anomalyco/opencode/issues/62900 | 2026-11-09 | user report | `glm-5.3-flash` repetition on long context |
| https://github.com/anomalyco/opencode/issues/61943 | 2026-11-05 | user report | Authorization header error |
| https://github.com/anomalyco/opencode/issues/61845 and /61873 | 2026-11-06 | user report | `gemini-4-argon` 403 |
| https://github.com/anomalyco/opencode/issues/61614 | 2026-11-06 | user report | `web_search` dropped on `gpt-6-luna` |
| https://github.com/anomalyco/opencode/issues/54801 and /62264 | 2026-11-06 to 2026-11-07 | user report | Declared effort ladder missing (MiniMax) |
| https://www.kimi.com/blog/kimi-k3-1-pro | 2026-10-23 | vendor claim | Kimi K3.1 Pro scores |
| https://docs.z.ai/guides/llm/glm-5.3 | undated | vendor claim | GLM-5.3 scores and effort levels |
| https://blog.buildfastwithai.com/glm-5-3-vs-deepseek-v4-pro-vs-kimi-k3 | 2026-08-17 | user report (blog) | GLM vs DeepSeek vs Kimi |
| https://www.bitdoze.com/best-open-source-llms-claude-alternative | undated (content from 2026-08 to 2026-10) | aggregator of vendor claims | Terminal-Bench copies |
| https://www.bitdoze.com/opencode-go-vs-clinepass-cheap-models/ | 2026-08-03 | user report (blog) | Request estimates |
| https://pasqualepillitteri.it/en/news/10943/leaving-claude-max-codex-for-opencode-go | 2026-08-13 | user report (blog) | Flash vs Pro remark |
| https://vanja.io/deepseek-glm/ | 2026-09-16 | user report (blog) | Cache and effort advice |
| https://www.benchlm.ai/benchmarks/terminal-bench-2 | 2026-11-07 | benchmark (self-reported, previous generation) | Terminal-Bench 2.0 context |

### 8.2 Read but not used

Reason: older than 6 months, or about models that are no longer the current ones.

| Link | Date | Type | Reason |
| --- | --- | --- | --- |
| https://twcom-rr.pages.dev/blog/opencode-go-review/ | 2026-04-15 | user report | Older than 6 months; old model set |
| https://www.mindstudio.ai/blog/best-open-source-llms-agentic-coding-2026 | 2026-04-26 | user report | Older than 6 months; old model set |
| https://aider.chat/docs/leaderboards/ | 2025-11-20 | benchmark | No Go model of the current list |
| https://labs.scale.com/leaderboard/swe_bench_pro_public | not found | benchmark | The snapshot has old models only |
| https://www.codesota.com/benchmark/terminal-bench | 2026-04 | benchmark | No Go model on the page |
| https://www.tbench.ai/leaderboard/terminal-bench/2.0 | not found | benchmark | The table rows did not load |
| https://artificialanalysis.ai/models/capabilities/coding | not found | benchmark | Model scores did not load |

### 8.3 Search snippets only (not opened)

| Link | Date | Type | Use |
| --- | --- | --- | --- |
| https://forum.cursor.com/t/deepseek-v4-pro-error-report/159983/5 | not found | user report | `deepseek-v4-pro` errors (section 5) |
| https://github.com/code-yeongyu/oh-my-openagent/issues/1033 | not found | user report | Tool-call loop with long history |

### 8.4 Gaps

| Gap | Effect |
| --- | --- |
| No SWE-bench Pro, Terminal-Bench, or Aider polyglot row for `kimi-k3.1-pro`, `glm-5.3`, `deepseek-v4.1-flash`, `mimo-v2.6-*`, `claude-haiku-5-5`, or `gpt-6-luna` from an independent run | All ranks are low confidence |
| Harness of each vendor score | Not stated in most sources. Do not assume OpenCode. |
| Cost, turns, or tokens for each task | Not found for any model |
| Reddit, Hacker News, and Discord threads about current Go models | Not found. Search returned old or empty threads. |
| Fast "Highspeed" Kimi variant (2 to 3 times faster, vendor) | Not in the Go list |
| Artificial Analysis and tbench.ai tables | Pages did not load |
| Variant names for "toggle" models | Not found |

