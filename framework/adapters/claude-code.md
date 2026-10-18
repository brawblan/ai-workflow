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
| Skill | `.claude/skills/<name>/SKILL.md`, or a skill in the `workflow` plugin | full | Use `disable-model-invocation: true` for skills with side effects. |
| Role | `.claude/agents/<role>.md` with `name`, `description`, `tools`, `model` | partial | Tools can be limited. Paths cannot be limited by the role file. See "Protected paths". |
| Fresh session for each role | A separate `claude -p` run for each role | full | A sub-agent also has a fresh context, but the lead agent starts it. Use separate runs where P2 applies. |
| Headless run | `claude -p "<prompt>" --output-format json` | full | |
| Select the role for a headless run | `[TO CONFIRM]` flag or setting that loads one agent file | partial | Fallback: pass the role file text with the prompt. |
| Hook before a file edit | `PreToolUse` hook with matcher `Edit\|Write` in `.claude/settings.json`. Exit code 2 blocks the edit. | full | |
| Hook before the session ends | `Stop` hook that runs the checks | full | Do not loop forever. The harness caps repeated blocks. |
| Model for each role | `model` field in the role file, from `defaults.role_models` in the model profile | full | |
| Permissions | `permissions` allow and deny lists in `.claude/settings.json`, and sandbox mode | full | |
| CI trigger | `anthropics/claude-code-action`, pinned to a commit SHA | full | |
| CI authentication | Repository secret `[CLAUDE_CODE_OAUTH_TOKEN]`, made with `claude setup-token` | full | Uses the subscription, not an API key. `[TO CONFIRM]` usage limits for CI. |

## Protected paths

The implementer must not change tests or checks (P2). This applies to a human implementer too. Use
two layers:

1. **Local hook.** The run script sets `STONE_ROLE=implementer`. A `PreToolUse` hook reads the role and
   the target path. It exits with code 2 if the path is protected. In a `pair` session, the hook
   uses the role of the human (default: implementer). The hook also limits the tester to the test
   paths, and blocks each edit by the reviewer.
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

## Role files (generated)

| Role | Tools | Default model |
| --- | --- | --- |
| shaper | Read, Grep, Glob, issue read and write | the strongest model |
| planner | Read, Grep, Glob, Write (plans path only, enforced by hook) | the strongest model |
| implementer | Read, Grep, Glob, Edit, Write, Bash | repo config |
| tester | Read, Grep, Glob, Edit, Write (tests path only, enforced by hook), Bash | repo config |
| reviewer | Read, Grep, Glob, Bash (read-only commands) | repo config |
| investigator | Read, Grep, Glob, Bash | repo config |

## Existing plugin skills

| Skill | Framework place | Change needed |
| --- | --- | --- |
| `project-setup` | full-project, Shape | Becomes the Shape step of `cornerstone-setup`. Stays usable alone. |
| `sdd-plan`, `sdd-build` | Plan, Build | Removed in plugin 0.5.0 (D18). The planner, implementer, and tester role files do this work. |
| `ticket-delivery` | Verify, Deliver | Done in plugin 0.4.0: it collects the tester, reviewer, and check output as evidence. It does not self-verify. |
| `dev-pr` | Deliver | Done in plugin 0.4.0: the PR evidence sections (K14) and the role trailers. |
| `backlog-sequencer` | Intake | No change. |
| `ste-writing` | Writing standard ([writing.md](../writing.md)) | Load it in each role that writes human-facing text. Add the blind A/B eval. K17 covers the measurable rules. |
