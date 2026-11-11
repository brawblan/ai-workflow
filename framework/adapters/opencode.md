# Adapter: OpenCode

Status: full v1 (D118). The #302 pilot tested the facts below on OpenCode 2.2.6 on 2026-11-08
([dossier S58](../../docs/research/dossier.md#6-sources)). The #325 spike
([report](../../docs/reports/2026-11-10-opencode-adapter-ci-spike.md)) and the #326 probes tested
the other facts on the same version. A fact marked `[TO CONFIRM]` is not proven.

Model profiles: [opencode/models/opencode-default.yaml](opencode/models/opencode-default.yaml).

The component list [opencode/components.yaml](opencode/components.yaml) maps each role to its
`.opencode/agents/<role>.md` file. The run command is [opencode/eval.yaml](opencode/eval.yaml). The
parser is [opencode/parsers/opencode.py](opencode/parsers/opencode.py). A target repo selects
`harness: opencode` and `model_profile: opencode-default`.

To run a role eval on OpenCode, follow the steps in
[Run on OpenCode](../../evals/README.md#run-on-opencode).

`stone render` writes the role file of each role that a selected profile uses, and the project
config `opencode.json`. A profile can have a label, `ci:issue-opened`, or schedule trigger. For each
one, render also writes a CI workflow and a read-only CI copy of the role file (see
[CI triggers](#ci-triggers)). It writes no hook or check yet. Without K6 in CI, the permission rules
are the only control on a protected path. A later issue adds the checks and the G3 workflow.
`stone eval` also uses the adapter.

## Mapping

| Concept | Target | Format | Support | Fallback |
| --- | --- | --- | --- | --- |
| Instruction file (repo) | `AGENTS.md` in the repo root | Markdown | full | none. OpenCode does not read `CLAUDE.md`. |
| Instruction file (user) | `~/.config/opencode/AGENTS.md` | Markdown | full | none. |
| Skill | `.opencode/skills/<name>/SKILL.md`. OpenCode also loads `.claude/skills/<name>/SKILL.md`, unless `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1`. | Markdown | full | Linked docs that `AGENTS.md` names. |
| Role | `.opencode/agents/<role>.md` with `description`, `mode`, `model`, `permissions`, and `steps` | Markdown with YAML frontmatter | partial | Separate `opencode run` sessions with a role prompt. A path rule limits the file tools, not the shell (D39). |
| Fresh session for each role | One `opencode run` for each role | process or command | full | none. P2 needs it. |
| Headless run | `opencode run "<prompt>"` | process or command | full | none. CI needs it. |
| Eval run | [opencode/eval.yaml](opencode/eval.yaml): the argv for each variant, the env, the parser, and the role tool list | YAML | full for a role | No guidance or trigger command yet. `stone eval` names the reason. |
| Select the role for a headless run | `opencode run --agent <role>` loads `.opencode/agents/<role>.md` | process or command | full | none. Tested on 2.2.6 (2026-11-08). |
| Model for each role | `--model <provider>/<model>[#variant]`, or `model` in the role file | process or command | full | One model for all roles. |
| Permissions | The ordered `permissions` list in the role file, and the list in `opencode.json` | Markdown with YAML frontmatter, JSON | partial | Run in a container with no secrets. The role file rules come after the config rules, so they win. |
| Hook before a file edit | none | not applicable | none | The `edit` path rules in each role file. Check K6 in CI is not rendered yet. |
| Hook before the session ends | none | not applicable | none | Gate G3 in CI. |
| CI trigger | Workflows `.github/workflows/cornerstone-<profile>-<trigger>.yml` for the label, `ci:issue-opened`, and schedule triggers. Each runs `opencode run --agent <role>-ci` | YAML (GitHub Actions) | partial | Run the role by hand. There is no `ci:dependency-pr` trigger. A role that needs the shell does not run in CI. |
| Render the role files and the settings | `stone render` writes `.opencode/agents/<role>.md` and merges `opencode.json` | Markdown, JSON | full | none. |
| Context guard hook (D115) | none | not applicable | none | Watch the context size by hand. Start a new session after a PR. |
| Token report (`stone usage`, D114) | none | not applicable | none | No `usage.yaml` yet, so `stone usage` stops with an error. `opencode stats` shows some usage data. |

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

The allowed actions are in `permission_actions` of [components.yaml](opencode/components.yaml).
`stone render` refuses a role file with another action.

### Protected paths

OpenCode has no hook before a file edit. So render puts `edit` rules at the end of each role file.
They give the same paths as the protect-paths hook of the reference adapter:

| Role | `edit` rules |
| --- | --- |
| implementer | Deny `paths.tests`, `paths.checks`, `paths.specs`, and the harness paths. |
| tester | Deny all. Allow `paths.tests`. Deny the harness paths. |
| planner | Deny all. Allow `paths.plans`. Deny the implementer paths. |
| investigator | Deny all. Allow `paths.reports`. Deny the harness paths. |
| shaper | No `edit`. Allow the ticket file if `tickets.source` is `file`. |
| reviewer | No `edit`. |

The harness paths are `.opencode/`, `opencode.json`, and `.cornerstone/`. With
`protect_instruction_files: true`, they also include each `AGENTS.md` file (D87).

How render writes a path as a rule:

- A rule resource is relative to the repo root. `*` matches any text, also `/`. So a folder
  `tests/` gives the rules `tests` and `tests/*`.
- OpenCode has no `[...]` class. A word of one-letter classes, such as `[Aa][Gg][Ee][Nn][Tt][Ss]`,
  gives the upper-case and the lower-case word. A mixed case such as `Agents.md` is not covered.
- A `**/` start gives the path at the root and the path in any folder.
- A glob rule can cover more paths than the core match (D62), because `*` also matches `/`.
- On a spike branch, the hook lets the investigator write anywhere. A role file cannot see the
  branch. So on OpenCode, the investigator writes only in `paths.reports` on each branch.

The #326 probes ran each role on OpenCode 2.2.6 and tried a write to each type of path. Each
allowed path was written, and each denied path gave `Permission denied: edit`.

### Project config

Render merges a `permissions` list into `opencode.json`. Other keys stay as they are. The list
denies `external_directory` and an `edit` of the harness paths. These rules apply to a session with
no role, for example a person who starts `opencode` in the repo. A role file starts with a deny-all
rule, and its rules come after the config rules, so the role file rules win.

## CI triggers

`stone render` writes one workflow for each profile trigger of the type label, `ci:issue-opened`,
or schedule (D119). The inputs, the job split, and the report framing are the same as in the
reference adapter ([claude-code.md](claude-code.md#trigger-workflows)). A `ci:dependency-pr` trigger
gives no file, and render prints a notice. The plan key is the repo secret `OPENCODE_API_KEY`. The
#325 spike tested these facts on OpenCode 2.2.6 ([report](../../docs/reports/2026-11-10-opencode-adapter-ci-spike.md)).

| Item | What the workflow does |
| --- | --- |
| Install | Downloads the `opencode-linux-x64.tar.gz` asset of the pinned version 2.2.6 from the release page. `sha256sum -c` checks it. npm has no 2.x build, so the workflow does not use npm. The version and the SHA-256 are in [values.py](opencode/values.py). |
| Role file | Runs `.opencode/agents/<role>-ci.md`, a copy of the role file with the step cap 30 and the rules `deny *`, then `allow read`, `grep`, and `glob`. It has no shell, `execute`, `webfetch`, or `edit`. |
| Run | `opencode --standalone run --agent <role>-ci --format json --archived "<prompt>"`. The prompt marks the event text as untrusted. |
| Event text | The job saves the issue or the issue list as `.cornerstone-event/event.json` in the checkout. The deny-all rule also denies a read outside the checkout. |
| Plan key | `OPENCODE_API_KEY` comes from the secret, and only as an env variable of the one step that runs OpenCode. No step writes it to a file. |
| Symlink | A step before the run fails the job on any symlink in the checkout. The read tool follows a symlink out of the checkout (spike). |
| Report | The role ends its last message with a JSON object `{"report": "..."}`. A step reads the text parts of the last message, then the last JSON object, with or without a code fence. If no object has a `report`, the job fails. |
| Post job | A second job has its own token. It frames the report and posts it, as in the reference adapter (D31, D38). The run job has no write token. |
| Limits | The role stops at 30 steps, and the job stops at 20 minutes (D38). |

`stone render` refuses a trigger in two cases. The first case is a CI copy that would allow `shell`,
`execute`, `webfetch`, `edit`, or `external_directory`. The second case is a first rule that does
not deny all actions. A role with the shell can read the plan key from the env of the process
(D39). The rules are in `ci_role` of [components.yaml](opencode/components.yaml).

A schedule workflow has a comment line with the result of the peak check. Render reads the peak
windows of the model of the first role in [rates.yaml](opencode/rates.yaml), and compares them with
the cron line in UTC. If a fire time is in a peak window, the comment starts with `WARNING`, and
render prints the same warning. The check does not narrow the fire times by the
month. If the cron line sets the day of the month, the check counts every weekday. So it can warn about
a time that never runs.

Limits of the CI triggers:

- A role that needs the shell, such as the implementer in CI, does not run. The read-only copy
  only reads. A profile step that needs the shell cannot run, and the role says so in the report.
- The CI roles cannot use the code index. `stone-index` has no MCP mode (spike).
- The run job reads the event text, and the role could write it into the report. The post job frames
  the report as quoted text, as in the reference adapter.
- Anyone can start the `ci:issue-opened` trigger, and each run costs plan usage. The step cap and
  the time limit are the only cost controls (D38).

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
| Cost | The sum of the `step_finish` cost. OpenCode reports 0 on the Go plan. Then `stone eval` estimates the cost from the token counts and `rates.yaml` (D116). A model with no rates shows "—". |
| Turns | The count of `step_finish` events. |
| Input, output, reasoning, cache tokens | The sum of the `step_finish` token counts. |
| Tool calls, tool bytes | The `tool_use` events and the bytes of their output. |

A field that the harness does not give shows "—". The #302 pilot found that the 0 on the Go plan is
not the billed cost, and found no `opencode.allowance` field.

`rates.yaml` gives the published token rates of each model, the source, and the read date (D116):

- The cost of a run uses the token counts. Reasoning tokens use the output rate.
- The start of a run selects the peak or the off-peak rate. DeepSeek V4.1 Flash has a peak rate
  from 01:00 to 04:00 and from 06:00 to 10:00 UTC, Monday to Friday.
- Before the first run, `stone eval` warns for each model that is in a peak window. It then
  continues.
- Each result file says that the cost is an estimate, and how many runs used the peak rate.
- When the plan page changes, update the rates and the read date.

Limits of this eval run:

- The `without` variant has no role file. OpenCode then uses its default agent, which allows all
  actions, and `--auto` approves each one. The step cap is also absent. So the lift between `with`
  and `without` mixes the role text, the permissions, and the step cap. It is not comparable to the
  reference adapter (D44). Run it only in a clean workspace with no secrets.

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

The #325 spike and the #326 probes tested these facts on OpenCode 2.2.6:

| Fact | Result |
| --- | --- |
| Repo instruction file `AGENTS.md` | **Yes.** |
| User instruction file `~/.config/opencode/AGENTS.md` | **Yes.** It follows `XDG_CONFIG_HOME`, only with `--standalone`. |
| `CLAUDE.md` fallback | **No.** OpenCode did not read `CLAUDE.md`, with or without `AGENTS.md`. |
| Skill path `.opencode/skills/<name>/SKILL.md` | **Yes.** `.claude/skills/<name>/SKILL.md` also loads. |
| Action names `read`, `grep`, `glob`, `edit` | **Yes.** A denied tool is not offered to the model. The `write` tool uses the `edit` action. |
| Action `external_directory` | **Yes.** The deny-all rule also denies it. |
| A clean global config removes each user-level rule | **Partial.** A clean `XDG_CONFIG_HOME` removes `~/.config/opencode`. The skills in `~/.agents/skills` still load. On a CI runner, `HOME` is clean. |
| An `edit` path rule | **Yes.** A relative resource such as `tests/*` denies a path at any depth. |
| A `[...]` class in a rule | **No.** `[Aa][Gg][Ee][Nn][Tt][Ss].[Mm][Dd]` did not match `AGENTS.md`. |
| Config rules and role rules | **Yes.** The role file rules come after the config rules. |

The #325 spike tested these facts in a private test repo on a GitHub runner (3 of 3 runs):

| Fact | Result |
| --- | --- |
| A pinned install from the release asset, with the SHA-256 check | **Yes.** |
| The plan key from the env variable `OPENCODE_API_KEY` | **Yes.** GitHub masks it in the log. |
| A report as a bare JSON object at the end of the last message | **Yes.** The model did not use a code fence in CI. |
| The read tool and a symlink in the checkout | **Follows it** to a text file outside the checkout. The workflow fails on a symlink. |

Unproven facts:

- `[TO CONFIRM]` the rendered trigger workflows on a GitHub runner. The unit tests and the golden
  files check the text. The spike workflow has the same install, run command, and key, but it is
  not a rendered workflow.
- `[TO CONFIRM]` that a role in the CI copy reads `.cornerstone-event/event.json` through the
  deny-all rule. The spike role read a file in the checkout.
- `[TO CONFIRM]` that the published token rates stay fixed.
- `[TO CONFIRM]` that the read tool refuses `/proc/self/environ`. Only a binary-file check stopped
  it in the spike, and the read tool follows a symlink in the repo to a path outside it.

## Decision record

| Field | Value |
| --- | --- |
| Date | 2026-11-10 |
| Status | full v1. It replaces eval-only v0 of 2026-11-08 (D112). |
| Reason | The #325 spike proved the instruction, skill, and action facts. A target repo needs the role files from render, not by hand. |
| Options | The role files and the project config (chosen). The same with the shared checks and the G3 workflow (a later issue). A copy of the reference checks (rejected: two copies to keep the same). |
| Risks | No K6 in CI yet, so the path rules are the only control. A path rule does not limit the shell. A glob rule can cover more or fewer paths than K6. No cost limit. The CI triggers are in D119. |
| Eval plan | The adapter unit tests, the golden files of a render, and a probe of each role on OpenCode. |
| Review | 2027-05-10 |
| Framework decision | D118 |

### CI triggers (D119)

| Field | Value |
| --- | --- |
| Date | 2026-11-10 |
| Status | partial: label, `ci:issue-opened`, and schedule. Read-only roles. |
| Reason | A private target repo needs to start a role from a GitHub event (issue #327). |
| Options | A read-only CI copy of the role file (chosen). A refusal for each role that has the shell (rejected: no shipped profile could use a trigger). The normal role file (rejected: it has the shell or `edit`). |
| Risks | The plan key is in the env of the process, and a symlink or a shell could expose it. The controls are the symlink check, the deny-all rule, and no shell. The rendered workflow has not run on a runner. |
| Eval plan | The unit tests of the render, the refusal, the report step, and the peak check. The golden files of each trigger. Run one rendered workflow in a private test repo before a release. |
| Review | 2027-05-10 |
| Framework decision | D119 |
