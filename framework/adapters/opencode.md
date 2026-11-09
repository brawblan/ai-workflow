# Adapter: OpenCode

Status: eval-only v0. The #302 pilot tested the facts below on OpenCode 2.2.6 on 2026-11-08. A fact
marked `[TO CONFIRM]` is not proven.

Model profiles: [opencode/models/opencode-default.yaml](opencode/models/opencode-default.yaml).

The component list [opencode/components.yaml](opencode/components.yaml) maps each role to its
`.opencode/agents/<role>.md` file. The run command is [opencode/eval.yaml](opencode/eval.yaml). The
parser is [opencode/parsers/opencode.py](opencode/parsers/opencode.py). A target repo selects
`harness: opencode` and `model_profile: opencode-default`.

`stone render` refuses this adapter because its status is `eval-only` (see
[contract.md](contract.md#adapter-status)). It writes no files. `stone eval` uses it. The role
templates in `opencode/templates/agents/` have the same steps as the reference templates, so a
later adapter can render them.

## Mapping

| Concept | Target | Format | Support | Fallback |
| --- | --- | --- | --- | --- |
| Instruction file (repo) | `AGENTS.md` in the repo root | Markdown | full | none. OpenCode reads `CLAUDE.md` only if `AGENTS.md` is absent. |
| Instruction file (user) | `~/.config/opencode/AGENTS.md` | Markdown | full | none. |
| Skill | `.opencode/skills/<name>/SKILL.md` | Markdown | full | Linked docs that `AGENTS.md` names. |
| Role | `.opencode/agents/<role>.md` with `description`, `mode`, `model`, `permissions`, and `steps` | Markdown with YAML frontmatter | partial | Separate `opencode run` sessions with a role prompt, plus CI checks. A role file limits tools, not paths. |
| Fresh session for each role | One `opencode run` for each role | process or command | full | none. P2 needs it. |
| Headless run | `opencode run "<prompt>"` | process or command | full | none. CI needs it. |
| Eval run | [opencode/eval.yaml](opencode/eval.yaml): the argv for each variant, the env, the parser, and the role tool list | YAML | full for a role | No guidance or trigger command yet. `stone eval` names the reason. |
| Select the role for a headless run | `opencode run --agent <role>` loads `.opencode/agents/<role>.md` | process or command | full | none. Tested on 2.2.6 (2026-11-08). |
| Model for each role | `--model <provider>/<model>[#variant]`, or `model` in the role file | process or command | full | One model for all roles. |
| Permissions | The ordered `permissions` list in the role file, or the global list | Markdown with YAML frontmatter | partial | Run in a container with no secrets. The K6 check is the control for a protected path. |
| Hook before a file edit | none | not applicable | none | Check K6 in CI. |
| Hook before the session ends | none | not applicable | none | Gate G3 in CI. |
| CI trigger | none | not applicable | none | Run the role by hand, or use an adapter that provides a trigger. |
| Render the role files and the settings | none | not applicable | none | Keep the files by hand in the target repo. |

## Role files

A role file is `.opencode/agents/<role>.md`. The agent ID is the file name. The body is the system
prompt. The frontmatter sets the model, the mode, the permissions, and the step cap.

```markdown
---
description: Write independent tests from the ticket and the diff.
mode: primary
model: opencode-go/beam-free
steps: 60
permissions:
  - action: "*"
    resource: "*"
    effect: deny
  - action: edit
    resource: "*"
    effect: allow
---

You are the tester. ...
```

The `permissions` list uses `allow`, `ask`, or `deny`. The last rule that matches wins. The first
rule must deny all actions. Without it, the default allow-all rule stays in force. A path rule
limits a file tool. It does not limit a shell command, as in the reference adapter (D39).

`steps: 60` caps the model steps. OpenCode has no cost limit. At the cap, the run stops and adds a
"Maximum steps" message.

## Eval run

`stone eval` starts one headless run for each variant. The `with` variant names the role. The
`without` variant names no role, and the runner removes the role file from the workspace.

```bash
opencode --standalone run --agent tester --model opencode-go/beam-free --format json --auto \
  --archived "Write tests for this ticket."
```

`--standalone` gives the run a private server. `--auto` approves each permission that the role file
does not deny. `--archived` keeps the eval session out of the session list.

The parser reads the JSONL events:

| Field | Source |
| --- | --- |
| Report | The text parts of the last assistant message, joined. |
| Cost | The sum of the `step_finish` cost. OpenCode reports 0 on the Go plan, so the table shows 0.0000. A missing cost shows "—". |
| Turns | The count of `step_finish` events. |
| Input, output, reasoning, cache tokens | The sum of the `step_finish` token counts. |
| Tool calls, tool bytes | The `tool_use` events and the bytes of their output. |

A field that the harness does not give shows "—". The #302 pilot found that the 0 on the Go plan is
not the billed cost, and found no `opencode.allowance` field. Use the published token rates for a
cost estimate.

Limits of this eval run:

- There is no `--setting-sources project` flag. `OPENCODE_DISABLE_CLAUDE_CODE=1` made no difference
  in the pilot. Start the run in a clean workspace and keep the global OpenCode config empty.
- A guidance eval needs `run.guidance`, and a trigger eval needs `run.trigger`. This adapter has
  neither command. The `unsupported` map in `eval.yaml` gives the reason, and `stone eval` prints
  it.

## Facts to test

| Fact | Result |
| --- | --- |
| Headless run | **Yes.** `--auto` approves an `ask` rule. Without it, the rule is denied. |
| Role file | **Partial.** The file sets the model, the permissions, and the steps. The first rule must deny all actions. |
| Report | **Yes.** The final assistant text is the report. The parser joins the text parts of the last message. |
| Metrics | **Partial.** `step_finish` gives the token counts. The cost is 0, and there is no allowance field. |
| Isolation | **Partial.** No flag equals `--setting-sources project`. Use a clean workspace and global config. |
| Project discovery | **Yes.** Set `PWD` to the workspace. OpenCode did not find `.opencode/agents` from the process cwd alone. |
| Effort | **Yes.** `#high` and `#low` work on each pilot model. `#bogus` fails with `provider.no-route`. |
| Limits | **Partial.** There is no cost limit. `steps` caps the model steps. |

Unproven facts:

- `[TO CONFIRM]` that a clean global config removes each user-level rule from a run.
- `[TO CONFIRM]` that the published token rates stay fixed.

## Decision record

| Field | Value |
| --- | --- |
| Date | 2026-11-08 |
| Status | eval-only v0 |
| Reason | #301 needs a second harness to compare models. The #302 pilot proved only the role eval. |
| Options | A full adapter with render (later), an eval-only adapter (chosen), or a wrapper script (rejected: it hides the harness commands). |
| Risks | The adapter has no render, hook, trigger, or cost limit. The pilot has one trial and saturated scenarios. |
| Review | 2027-05-08 |
| Framework decision | D112 |
