# Adapter: Claude Code

Status: draft v0. Facts marked `[TO CONFIRM]` must be tested on the current Claude Code version.

Model profiles for this harness: [claude-code/models/](claude-code/models/claude-5.yaml).

Templates: `claude-code/templates/`. The component list
[claude-code/components.yaml](claude-code/components.yaml) names the template and the target path of
each component that `stone render` writes.

## Mapping

| Concept | Target | Support | Notes |
| --- | --- | --- | --- |
| Instruction file (repo) | `AGENTS.md`, and `CLAUDE.md` with one line: `@AGENTS.md` | full | Same file for all harnesses that read `AGENTS.md`. |
| Instruction file (user) | `~/.claude/CLAUDE.md` | full | This repo links it from `global/`. |
| Instruction size (K15) | `.cornerstone/checks/instruction_size.py` counts the lines of `AGENTS.md` | full | `CLAUDE.md` has one line, so it does not count. |
| Skill | `.claude/skills/<name>/SKILL.md`, or a skill in the `workflow` plugin | full | Use `disable-model-invocation: true` for skills with side effects. |
| Role | `.claude/agents/<role>.md` with `name`, `description`, `tools`, `model` | partial | Tools can be limited. Paths cannot be limited by the role file. See "Protected paths". |
| Fresh session for each role | A separate `claude -p` run for each role | full | A sub-agent also has a fresh context, but the lead agent starts it. Use separate runs where P2 applies. |
| Headless run | `claude -p "<prompt>" --output-format json` | full | |
| Eval run | [claude-code/eval.yaml](claude-code/eval.yaml): the argv for each variant, the env, the tools of each role, and the JSON paths of the result | full | `stone eval` reads it (D26). `[TO CONFIRM]` that `--setting-sources project` keeps the user instruction file out of the run. |
| Select the role for a headless run | `claude -p --agent <role>` loads `.claude/agents/<role>.md` | full | Confirmed on 2026-10-18 (Claude Code 2.1): the tester and reviewer runs for `stone eval` followed their role files. `[TO CONFIRM]` if the `model` field of the role file or `--model` wins. |
| Hook before a file edit | `PreToolUse` hook with matcher `Edit\|Write` in `.claude/settings.json`. Exit code 2 blocks the edit. | full | |
| Hook before the session ends | `Stop` hook that runs the checks | full | Do not loop forever. The harness caps repeated blocks. |
| Model for each role | `model` field in the role file, from `defaults.role_models` in the model profile | full | |
| Permissions | `permissions` allow and deny lists in `.claude/settings.json`, and sandbox mode | full | |
| CI trigger | `anthropics/claude-code-action`, pinned to a commit SHA | full | v1.0.252 is `f27be6b65a4652f08a2ba3cff79114829b588967`. See "Trigger workflows". |
| CI authentication | Repository secret `CLAUDE_CODE_OAUTH_TOKEN`, made with `claude setup-token`. It is `[HARNESS_TOKEN]` in the core. | full | Uses the subscription, not an API key. `[TO CONFIRM]` usage limits for CI: the action docs do not give them. |

## Protected paths

The implementer must not change tests or checks (P2). This applies to a human implementer too. Use
two layers:

1. **Local hook.** The run script sets `STONE_ROLE=implementer`. A `PreToolUse` hook reads the role and
   the target path. It exits with code 2 if the path is protected. In a `pair` session, the hook
   uses the role of the human (default: implementer). The hook also limits the tester to the test
   paths and the planner to the plans path, and blocks each edit by the reviewer.
2. **CI check K6.** Each commit has the trailers `Role: <role>` and `Actor: human|agent`. A commit
   with no `Role:` trailer counts as an implementer commit. K6 fails if an implementer commit
   changes a protected path.

The CI check is the source of truth. The hook gives faster feedback. A git commit template can add
the trailers for human commits.

The protected paths are `paths.tests` and `paths.checks` from the repo config, plus `.claude/` and
`.cornerstone/`. These two folders hold the hook, the check, and the harness settings.

The hook makes the target path relative to the git work tree that holds the file. This is
necessary because `CLAUDE_PROJECT_DIR` is the main checkout, also in a linked worktree under
`.claude/worktrees/<name>/`. Thus a worktree gets the same rules as the main checkout. A file
outside the project repo is not blocked.

`stone render` writes the hook to `.cornerstone/hooks/protect-paths.py` and K6 to
`.cornerstone/checks/protected_paths.py`. It merges this entry into `.claude/settings.json` and keeps
the other keys. The hook catches edits by the file tools only. A shell command can still change a
file, and K6 catches that change in CI.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.cornerstone/hooks/protect-paths.py\""
          }
        ]
      }
    ]
  }
}
```

## Trigger workflows

`stone render` writes `.github/workflows/cornerstone-<profile>-<type>.yml` for each trigger of a
selected profile that is not `command` (D31). The templates are `workflows/trigger-<type>.yml`. The
shared run step is `workflows/parts/run-role.yml`.

Before the first run, add the repository secret `CLAUDE_CODE_OAUTH_TOKEN`. Make each trigger label,
and `profile:<id>` if two selected profiles use one label. For `ci:dependency-pr`, add the same
secret as a Dependabot secret too. A run that Dependabot starts gets only Dependabot secrets, and a
read-only token unless the workflow `permissions` raise it.

| Trigger | GitHub event | Run job token | Post job token | Report goes to |
| --- | --- | --- | --- | --- |
| `label:<name>` | `issues: [labeled]`, with the label name in the job `if` | `contents: read`, `issues: read` | `issues: write` | An issue comment |
| `schedule:<value>` | `schedule` (daily `0 6 * * *`, weekly `0 6 * * 1`, monthly `0 6 1 * *`, or the cron line), and `workflow_dispatch` | `contents: read`, `issues: read` | `issues: write` | A new issue |
| `ci:issue-opened` | `issues: [opened]` | `contents: read`, `issues: read` | `issues: write` | An issue comment |
| `ci:dependency-pr` | `pull_request: [opened, reopened]` by `dependabot[bot]` or `renovate[bot]` | `contents: read`, `pull-requests: read` | `pull-requests: write` | A PR comment |

The run job:

1. Checks out the repo with `persist-credentials: false`, so no token stays in `.git/config`.
2. Saves the event data with `gh` to `$RUNNER_TEMP/cornerstone/event.json`. The issue number comes
   to the step through `env`.
3. Starts `anthropics/claude-code-action` with these inputs:

| Input | Value | Why |
| --- | --- | --- |
| `claude_code_oauth_token` | `secrets.CLAUDE_CODE_OAUTH_TOKEN` | The harness secret |
| `github_token` | `github.token` | The job `permissions` limit this token. The action does not get its app token. |
| `prompt` | The role, the profile, the trigger, the event file path, and the profile steps | The pipeline gives the profile steps at run time (D24). |
| `claude_args` | `--agent <role> --model <model> --add-dir <event folder> --allowedTools "Read(./**),Read(/<event folder>/**)" --disallowedTools Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch --json-schema <report schema>` | The role reads and reports. It cannot change files or run commands. It reads only the checkout and the event folder (D32). Its only output is the report. |

The action returns the report in `structured_output`. The post job reads it from the job output and
gives it to `gh` through `env`.

The action checks that the actor has write access for issue events. For `schedule` and
`workflow_dispatch`, GitHub needs write access to start the run. Two entries in
`components.yaml` change this check with `values`:

| Trigger | Action input | Why |
| --- | --- | --- |
| `ci:issue-opened` | `allowed_non_write_users: '*'` | Any user can report a bug. The action then scrubs secrets from the environment of each command. The role has no shell, so the read path limit (D32) protects the secret, not the scrub. |
| `ci:dependency-pr` | `allowed_bots: 'dependabot[bot],renovate[bot]'` | The bot opens the PR. The job `if` accepts only these two authors. |

### Prompt-injection limits

Issue text, PR text, and release notes are untrusted. Bug-triage reads issues from any user. These
limits apply:

| Limit | Effect |
| --- | --- |
| No write token in the run job | An injected instruction cannot change the repo, issues, or labels. |
| Tool allowlist: Read, Grep, Glob | No shell, no edits, no web fetch. The only output is the report. |
| Read rules only for `./**` and the event folder | Read, Grep, and Glob cannot open a file outside the checkout, such as `/proc/self/environ` with the harness secret. An unscoped `Read` rule allows all paths, and the report is public (D32, dossier F12). |
| Event text in a file, not in the prompt or a `run` script | The text cannot inject shell commands (dossier F8). |
| The post job posts the report as text | A report cannot apply labels. The investigator proposes labels, and a human approves them and the severity at G4. |
| Bug-triage: the post job has only `issues: write` | No write token beyond comments and labels. No contents, PR, or workflow write. |
| GitHub redacts a job output that contains a secret | A report with the harness secret or the job token is not posted (dossier F9). |
| `github.token` expires when the job ends | A leaked token is read-only and short-lived. |

Limits that stay:

- The report can carry injected text or wrong labels. A human reads each report before acting.
- The run job can read all repo files. Do not keep private data in a repo that runs these workflows.
- The role has no web tools. A step that reads a web page, for example release notes, uses only the
  event data and the repo. Do that step in a local run (`command`) if the report needs more.
- The action process has the harness secret. The allowlist blocks the shell, and the Read rules
  block the files outside the checkout, but the risk is not zero (dossier F10, F12).
- GitHub redacts a secret in a job output only as plain text. An encoded secret (for example
  base64) is not redacted. Do not add an unscoped `Read`, `Grep`, or `Glob` rule.

## Modes

| Driver | How it runs in Claude Code |
| --- | --- |
| `agent` in CI | `claude-code-action` job, one job for each role |
| `agent` on a computer | A run script calls `claude -p` once for each role |
| `pair` | An interactive Claude Code session. The human approves each edit (manual permission mode). |
| `human` | No Claude Code session changes files. Claude Code can still run the tester and the reviewer. |

| Mode | Files that the generator adds |
| --- | --- |
| agent-centric | CI workflows for each role, label triggers, the run script |
| hybrid | The run script, skills to start each agent stage, CI workflows for Test and Review |
| human-centric | Skills to start the tester and the reviewer on the current branch, the commit template with trailers |

## Gates on GitHub

| Gate | GitHub feature |
| --- | --- |
| G1 | Issue form with required fields, and a label (default `agent-ready`) that a human adds |
| G2 | A plan PR that a human approves, or a `plan-approved` label from a human |
| G3 | Required status checks in branch protection or a ruleset |
| G4 | Required PR review |
| G5 | A deployment environment with required reviewers |

`stone render` writes K16 to `.github/workflows/cornerstone-k16.yml` for each profile that lists K16
(D30). The job runs on `pull_request_target`, so GitHub runs the workflow file from the base branch.
A spike branch cannot change or remove it. The job checks out no code and has `permissions: {}`
(dossier F11). It gets the branch names only through `env`. Add the `k16` job as a required status
check on the main branch.

## Role files (generated)

| Role | Tools | Default model |
| --- | --- | --- |
| shaper | Read, Grep, Glob, issue read and write | the strongest model |
| planner | Read, Grep, Glob, Write (plans path only, enforced by hook) | the strongest model |
| implementer | Read, Grep, Glob, Edit, Write, Bash | repo config |
| tester | Read, Grep, Glob, Edit, Write (tests path only, enforced by hook), Bash | repo config |
| reviewer | Read, Grep, Glob, Bash (read-only commands) | repo config |
| investigator | Read, Grep, Glob, Edit, Write (reports path, or a `spike/` branch, enforced by hook), Bash | repo config |

## Existing plugin skills

| Skill | Framework place | Change needed |
| --- | --- | --- |
| `project-setup` | full-project, Shape | Becomes the Shape step of `cornerstone-setup`. Stays usable alone. |
| `sdd-plan`, `sdd-build` | Plan, Build | Removed in plugin 0.5.0 (D18). The planner, implementer, and tester role files do this work. |
| `ticket-delivery` | Verify, Deliver | Done in plugin 0.4.0: it collects the tester, reviewer, and check output as evidence. It does not self-verify. |
| `dev-pr` | Deliver | Done in plugin 0.4.0: the PR evidence sections (K14) and the role trailers. |
| `backlog-sequencer` | Intake | No change. |
| `ste-writing` | Writing standard ([writing.md](../writing.md)) | Load it in each role that writes human-facing text. Add the blind A/B eval. K17 covers the measurable rules. |
