# Measure and cut the fixed start context of a session

Issue #300, part of #296. Date: 2026-11-09.

## Result

- A main session in a remote child session starts at 57,452 tokens. A subagent starts at 8.3k to 11k tokens.
- This repo controls about 3 percent of the main-session start context (`AGENTS.md`, 1.7k tokens).
- The owner controls about 20 percent: skill list, connectors, memory, global file (up to 11k tokens).
- No one here controls about 77 percent: system text, built-in tools, and the 34 bridge tools.
- The bridge tools alone are 29.4k tokens (51 percent).
- This PR cuts 68 tokens. It saves about 0.03 percent of the release cost. Real savings are in the owner's list.

## Method

| Item | Value |
| --- | --- |
| Count | The first API call of each transcript: input, cache read, and cache write tokens. Same measure as `stone usage` (D114). |
| Sessions | 183 main and subagent sessions of this repo, October and November 2026, from `~/.claude/projects/` |
| Part sizes | The transcript keeps the system text, the tool list, and each reminder of the first call. This report counts the characters of each part. |
| Conversion | 57,452 tokens for 219,183 characters of the measured session = 3.8 characters for each token. The sizes in tokens are estimates, with the same ratio for each part. |
| Local session | The transcript does not keep the tool list of a local session. The tool definitions are the rest after the recorded parts. |

Reproduce: `stone usage <transcript folder>` gives the calls. The first-call count is in the first
`assistant` record, field `message.usage`.

## Start context by session kind

| Kind | Count | Start context (median) | Range |
| --- | --- | --- | --- |
| Main, remote child session | 56 sessions | 55.7k | 43.7k to 68.5k |
| Main, local | 36 sessions | 69.8k in October, 43.1k in November | 40.5k to 72.8k |
| Subagent, remote or local | 91 sessions | 8.4k to 10.4k | 8.2k to 11.8k |

## Parts of a remote child main session

Session `e0cb9acc`, 57,452 tokens at the first call.

| Part | Tokens (estimate) | Share | Group |
| --- | --- | --- | --- |
| Bridge MCP tools (34 tools) | 29.4k | 51.2% | No one here |
| Built-in tool definitions (12 tools) | 11.9k | 20.7% | No one here |
| Skill list (42 skills) | 5.3k | 9.2% | Owner |
| System text (harness and remote environment) | 5.2k | 9.0% | No one here |
| Instruction files | 2.7k | 4.7% | Split, see below |
| Deferred tool names | 1.0k | 1.7% | Owner |
| Agent list (10 agents) | 0.7k | 1.2% | Split, see below |
| Connector instructions | 0.6k | 1.0% | Owner |
| Environment, model, date, session | 0.5k | 0.9% | No one here |
| First prompt | 0.2k | 0.3% | The task |

The 4 largest bridge tools (`create_environment`, `update_environment`, `create_trigger`,
`update_trigger`) are 18.3k tokens together. The harness sends them to every bridge session. This repo
cannot filter them.

### Instruction files

| File | Tokens | Group |
| --- | --- | --- |
| `AGENTS.md` of this repo | 1,715 | This repo |
| `MEMORY.md` of the owner (13 lines) | 463 | Owner |
| `global/AGENTS.md` | 295 | Owner |
| Two `CLAUDE.md` stubs (`@AGENTS.md`) | 5 | Both |

### Agent list and skill descriptions of this repo

| Item | Size | Note |
| --- | --- | --- |
| 4 project agents (`implementer`, `reviewer`, `shaper`, `tester`) | 131 to 148 characters each | Already short |
| 5 plugin skills | 131 to 464 characters each, 1.7k in all | The plugin is not enabled in this repo, so these 5 are not in the measured list. A target repo with the plugin pays about 0.45k tokens. |

## Parts of a local main session

Session `50fdb563` (2026-11), 43,055 tokens.

| Part | Tokens (estimate) |
| --- | --- |
| Tool definitions (not recorded) | 27.8k |
| Skill list (45 skills) | 5.9k |
| System text | 3.1k |
| Deferred tool names (50) | 1.5k |
| Instruction files | 2.3k |
| Agent list | 1.0k |
| Connector instructions | 0.9k |
| Other | 0.5k |

The October local sessions started at 70k. The deferred tool list was 3 times longer (172 names) and the
connector instructions 1.5 times longer. The owner removed some connectors since then.

## Proposed cuts

| # | Cut | Group | Saves (tokens) | Done here |
| --- | --- | --- | --- | --- |
| 1 | Merge 3 Rust rows and 3 test rows in the `AGENTS.md` command table. Shorten the two release steps to links. | This repo | 68 | Yes |
| 2 | Disable the skill sets that this repo does not use: `anthropic-skills` (1.8k), `engineering` (0.7k), `design` (0.5k), `dataviz` (0.4k), `cowork-plugin-management` (0.2k). Enable them per project. | Owner | 3.6k | No |
| 3 | Disconnect connectors that the release work does not use. Each connector adds names (1.0k in all) and instructions (0.6k). In October, 172 names cost 4k. | Owner | 1.6k to 4k | No |
| 4 | Trim `MEMORY.md`. Merge the 13 lines to the ones that change work. | Owner | 0.2k | No |
| 5 | Run the release subagents in a local session, not a bridge session, if the bridge is not needed. A local session has no bridge tools. | Owner | `[TO CONFIRM]` up to 29k | No |
| 6 | Shorten the 5 skill descriptions to about 200 characters each. | This repo | 0.1k | No. A description sets when the skill starts. A test of the trigger must come first. |
| 7 | The system text, the built-in tools, and the 34 bridge tools. | No one here | 0 | Not possible |

Cut 5 needs a test: a local session that has the same plugin set. The October local sessions were as large
as the bridge sessions (70k), so the gain is not proved. Measure one local session with the connectors of
cut 3 off before you decide.

### Owner changes (not made here)

1. In `~/.claude/settings.json`, set `enabledPlugins` to false for `design`, `engineering`, and `cowork-plugin-management`.
2. Remove the claude.ai connectors that this repo does not use (Gmail, Stripe, and the others that show "needs authentication").
3. Disable `anthropic-skills` document skills (`docx`, `pdf`, `pptx`, `xlsx`) for this project.
4. Trim `MEMORY.md` of this project.

## Count before and after

| Measure | Before | After |
| --- | --- | --- |
| `AGENTS.md`, characters | 6,541 | 6,280 |
| `AGENTS.md`, tokens (3.8 characters for each) | 1,715 | 1,647 |
| Main start context, remote (same estimate) | 57,452 | 57,384 |

The "after" count is an estimate with the same ratio. A new session cannot measure it until this PR
merges. After the merge, start one remote child session and read its first call:
`stone usage <transcript folder>` and the first `assistant` record. `[TO CONFIRM]`.

## Replay cost

The #296 replay gives about 4 percent of the release cost for each 10k cut. The 68-token cut is below
the noise of the count. Cuts 2 and 3 (5k to 8k together) give about 2 to 3 percent. Cut 5 could give
up to 11 percent.

## Proposed check (new issue, not built)

- **Title:** Budget for the start context of this repo.
- **Idea:** `stone check` counts the characters of `AGENTS.md` and the plugin skill descriptions. It warns
  above a limit in the profile (for example 8,000 characters for `AGENTS.md`, and 300 for one description).
- **Why:** The repo controls only 3 percent, but this part grows with each rule. A limit keeps it from growing.
- **Not built here.** The non-goals of #300 exclude a new check.

## Limits of this report

- The token sizes of the parts are estimates from characters. Only the total is counted.
- The tool list of a local session is not in the transcript. Its 27.8k is a remainder.
- One remote session gives the part table. The totals of other sessions agree within 10 percent.
- Harness names stay in this report and in the adapter (P12). The core does not name them.
