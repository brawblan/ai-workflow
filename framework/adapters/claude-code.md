# Adapter: Claude Code

Status: draft v0. Facts marked `[TO CONFIRM]` must be tested on the current Claude Code version.

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
| Model for each role | `model` field in the role file | full | |
| Permissions | `permissions` allow and deny lists in `.claude/settings.json`, and sandbox mode | full | |
| CI trigger | `anthropics/claude-code-action`, pinned to a commit SHA | full | |
| CI authentication | Repository secret `[CLAUDE_CODE_OAUTH_TOKEN]`, made with `claude setup-token` | full | Uses the subscription, not an API key. `[TO CONFIRM]` usage limits for CI. |

## Protected paths

The implementer must not change tests or checks (P2). Use two layers:

1. **Local hook.** The run script sets `AIWF_ROLE=implementer`. A `PreToolUse` hook reads the role and
   the target path. It exits with code 2 if the path is protected.
2. **CI check K6.** Each role commit has a trailer `Agent-Role: <role>`. K6 fails if a commit with
   `Agent-Role: implementer` changes a protected path.

The CI check is the source of truth. The hook gives faster feedback.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": ".ai-workflow/hooks/protect-paths.py" }
        ]
      }
    ]
  }
}
```

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
| `project-setup` | full-project, Shape | Read the profile and the repo config. |
| `sdd-plan` | Plan (OpenSpec) | Move to the OpenSpec section of [spec-tools.md](spec-tools.md). |
| `sdd-build` | Build (OpenSpec) | Split: implementer and tester run in separate sessions. |
| `ticket-delivery` | Verify, Deliver | Use the tester and reviewer output as evidence. Do not self-verify. |
| `dev-pr` | Deliver | Add the PR evidence sections (K14). |
| `backlog-sequencer` | Intake | No change. |
| `ste-writing` | Cross-cutting | Add an eval. |
