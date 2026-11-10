# Spike: the OpenCode facts for a full adapter and a CI run

Issue [#325](https://github.com/brawblan/ai-workflow/issues/325), part of the 1.8.0 OpenCode work.
Date: 2026-11-10. Profile: `spike`. Harness: OpenCode 2.2.6.

## Result

- A read-only role runs in a GitHub Actions job of a private test repo. The job installs a pinned
  OpenCode build, checks its SHA-256, and reads the plan key from the secret `OPENCODE_API_KEY`.
  3 of 3 runs passed.
- OpenCode reads the plan key from the env variable `OPENCODE_API_KEY`. The secret name is correct.
- A role with the shell denied did not read the plan key. The read tool refused
  `/proc/self/environ` (D32). **But the read tool follows a symlink in the workspace to a path
  outside it.** A deny rule on the target path does not stop it. Only the binary-file check stopped
  the read of `/proc/self/environ`.
- The report can be structured. The role ends its final message with a JSON object. 3 of 3 CI runs
  gave a valid JSON object, but with no code fence. The parser must accept a bare JSON object.
- OpenCode reads an MCP server from the project `opencode.json`. The model calls an MCP tool through
  the `execute` tool. `stone-index` has no MCP server mode today.
- Of the 5 `[TO CONFIRM]` facts of the adapter, 4 are now tested. Two of them differ from the
  adapter doc: OpenCode does not read `CLAUDE.md`, and a clean global config does not remove the
  user-level skills.

## Facts and results

| # | Fact | Result |
| --- | --- | --- |
| 1 | Repo instruction file `AGENTS.md` | **Yes.** Read on macOS and in CI. |
| 2 | User instruction file `~/.config/opencode/AGENTS.md` | **Yes.** It follows `XDG_CONFIG_HOME`, only with `--standalone`. |
| 3 | `CLAUDE.md` fallback if `AGENTS.md` is absent | **No.** OpenCode did not read `CLAUDE.md` in any probe, with or without `AGENTS.md` and with or without `OPENCODE_DISABLE_CLAUDE_CODE=1`. The adapter doc is wrong. |
| 4 | Skill path `.opencode/skills/<name>/SKILL.md` | **Yes.** The `skill` tool loads it. `.claude/skills/<name>/SKILL.md` also loads. `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` turns off the `.claude` paths. |
| 5 | Action names `read`, `grep`, `glob`, `edit` | **Yes.** A role with a deny-all rule and one allow rule gets only that tool. A denied tool is not offered to the model. |
| 6 | A clean global config removes each user-level rule | **Partial.** A clean `XDG_CONFIG_HOME` removes `~/.config/opencode`. The skills in `~/.claude/skills` and `~/.agents/skills` still load. The two disable flags remove `~/.claude/skills`. `~/.agents/skills` still loads. On a CI runner, `HOME` is clean, so this is a local risk only. |
| 7 | Published token rates stay fixed | `[TO CONFIRM]`. Not in the scope of this spike. |
| 8 | Pinned install and the plan key from a secret in CI | **Yes.** See "CI run". |
| 9 | Plan key in the env, shell denied | **Not read, by chance.** See "Plan key". |
| 10 | Structured report | **Yes, as a bare JSON object** at the end of the final message. See "Report". |
| 11 | MCP server from the project config | **Yes.** See "MCP". |

## Commands

The probes ran in a temporary git workspace outside the repo. Each probe used a private config
folder and a private server:

```bash
cd "$WS"
XDG_CONFIG_HOME="$TMP/cfg" PWD="$WS" opencode --standalone run --format json --archived \
  --model opencode-go/glm-5.3-flash [--agent <probe-role> --auto] "<probe prompt>"
```

- Without `--standalone`, `opencode debug config` showed the user config folder, not the private
  one. The background server keeps its own environment. Use `--standalone` for an isolated run.
- An instruction probe put a canary word in each file, and asked the model for each canary. A second
  probe told the model to start each reply with a fixed word. `AGENTS.md` made the model do it.
  `CLAUDE.md` did not.
- An action probe used one role for each action: a deny-all rule, then one `allow` rule. The prompt
  asked for a read, a grep, a glob, an edit, and a shell command, in that order.
- The Linux probes used the `opencode-linux-arm64` build of 2.2.6 in a `debian:stable-slim`
  container. They used the free model `opencode/glm-5.3-flash-free`, so the plan key was not in the
  container. A decoy env variable took the place of the key.

## Plan key

The plan key is an env variable of the OpenCode process. The read tool runs in that process. So
`/proc/self/environ` holds the key. The probes used a decoy variable with the same exposure.

| Probe | Role permissions | Result |
| --- | --- | --- |
| Read `/proc/self/environ` | deny-all, allow `read`, `grep`, `glob` | Denied: `Permission denied: external_directory` |
| The same | also deny `read` on `/proc/*` | Denied: `external_directory` |
| The same | also allow `external_directory` | Refused: `Cannot read binary file` |
| Read `env-link.txt`, a symlink in the workspace to `/proc/self/environ` | deny-all, allow `read`, `grep`, `glob` | Refused: `Cannot read binary file` |
| The same | also deny `read` on `/proc/*` | Refused: `Cannot read binary file` |
| Grep for the decoy name in the workspace | deny-all, allow `read`, `grep`, `glob` | No match. `grep` does not follow the symlink. |
| Read `out-link.txt`, a symlink in the workspace to a text file in `/etc` | deny-all, allow `read`, `grep`, `glob`, deny `read` on `/proc/*` | **Read.** The tool gave the file text. |

What this shows:

- The deny-all rule also denies `external_directory`. So a direct read of a path outside the
  workspace fails.
- The read tool follows a symlink in the workspace. The `external_directory` check and the path
  rules look at the link path, not the target.
- `/proc/self/environ` separates its entries with NUL bytes. The binary-file check refused it. This
  check is not a permission, and a later version can change it.
- A pull request can add a symlink. A read-only role in CI could then read any text file that the
  runner user can read.

Controls for #326 and #327:

1. Give the key only through the env. Do not write it to a file, for example with `opencode auth
   login` or a `{file:...}` value in the config.
2. Before the role runs, fail the job on a symlink in the checkout. The spike workflow does this
   with `find . -path ./.git -prune -o -type l -print`.
3. Keep the deny-all first rule, so `external_directory` stays denied.
4. Do not allow `execute` or `webfetch` in a CI role unless the role needs an MCP tool (see "MCP").

The CI job did not run the `/proc` probe with the real key. A successful read would send the key
to the model provider. The Linux container used the same OpenCode version.

## CI run

The workflow is in the private repo `brawblan/opencode-ci-test` at `.github/workflows/spike.yml`. It
has only a manual trigger and `contents: read`. The steps:

1. `actions/checkout`, pinned to a SHA, with `persist-credentials: false`.
2. Download `opencode-linux-x64.tar.gz` of v2.2.6 from the release page. Check its SHA-256 with
   `sha256sum -c`. Put the binary on `PATH`.
3. Run `opencode --standalone debug config` and `debug agents`.
4. Fail on a symlink in the checkout.
5. Run the role with no key, as a control.
6. Run `opencode --standalone run --agent reviewer --format json --archived "<prompt>"` with
   `OPENCODE_API_KEY` from the secret.
7. Parse the JSONL: the tools, the final text, the report, and the token counts.

| Item | Result |
| --- | --- |
| Version | `opencode v2.2.6` |
| Config sources | `/home/runner/.config/opencode` (empty) and the project `.opencode` |
| Agents | The built-in agents and `reviewer` |
| Run with no key | Exit 1. `provider.free-limit`: "Free usage limit reached." |
| Run with the key | Exit 0 in 3 of 3 runs. 2 or 3 model steps, 269 to 1647 input tokens. Job time 27 s. |
| Tools used | `glob` and `read` only |
| Repo `AGENTS.md` | Read. Each report started with the word that `AGENTS.md` asked for. |
| Key in the log | Masked as `***` by GitHub. |

The role file gave the model, `steps: 15`, and the deny-all rule, then `read`, `grep`, and `glob`.
The job had `timeout-minutes: 10`.

## Report

The role text asks for one JSON object at the end of the final message, with a `verdict` and a
`findings` list.

- On macOS, the model put the object in a fenced `json` block. The parser read it.
- In CI, 3 of 3 runs put a valid object at the end, with no fence. The fence regex found nothing.
- OpenCode has no CLI flag for a JSON schema. The `--format json` events give the text parts, as in
  the #302 pilot.
- A report file is not an option for a read-only role, because the role has no `edit` permission.

Recommendation: the parser takes the text parts of the last assistant message, then reads the last
JSON object. It accepts a fenced block or a bare object. It fails the run if no object parses.

## MCP

The probe used a small stdio MCP server in Python with one tool. The workspace `opencode.json`:

```json
{
  "mcp": {
    "canary": {"type": "local", "command": ["python3", "<path>/mcp_canary.py"], "enabled": true}
  }
}
```

| Item | Result |
| --- | --- |
| Project config read | **Yes.** The model got the tool result. |
| How the model calls it | Through the `execute` tool: `return await tools.canary.mcp_canary();` |
| `opencode mcp list` | "No MCP servers configured". It does not show the project server. |
| Permission | A role needs `execute` and an allow rule on `<server>_<tool>`, for example `canary_mcp_canary` or `canary*`. `mcp` does not match. |
| What `execute` can reach | No `process` object. `fetch` exists, but the `webfetch` permission denies it. The `tools` object holds only the allowed tools. |

`stone-index` is a CLI with no MCP server mode. A role can use it only through the shell today. A
read-only CI role has no shell. So the CI roles cannot use the code index until `stone-index` gets
an MCP mode, or the adapter adds a wrapper.

## Hand-off

| For | Input from this spike |
| --- | --- |
| #326 adapter | Fix the `CLAUDE.md` row and the skill row. Add the `.claude/skills` path and its flag. Add `external_directory`, `execute`, and `<server>_<tool>` to the action names. Use `--standalone` for an isolated run. Keep the deny-all first rule. Accept a bare JSON report. |
| #327 item 6 | A read-only role with the shell denied can run in CI. The job must fail on a symlink, and the key must stay in the env only. A role with the shell can read the env (D39). Refuse a trigger for it. |
| #327 install | Download the release asset of a pinned version. Check the SHA-256. npm has only 1.19.5, so do not use npm for 2.x. |
| `stone-index` | Decide if `stone-index` needs an MCP mode for the CI roles. |

## Limits

- One OpenCode version, 2.2.6. Each local probe ran once. The CI role ran 3 times.
- The `/proc` and symlink probes ran in a local Linux container with a free model and a decoy. They
  did not run on a GitHub runner with the real key.
- The binary-file check is not a permission. It can change in a later version.
- The probes used one model, `glm-5.3-flash`. Another model can follow the report format less well.
- A test with an empty `HOME` lost the local login, so the user-level skills on a clean `HOME` were
  tested only on the CI runner.
- Fact 7, the token rates, was not tested.

The `stone check` and K17 checks pass on this report.
