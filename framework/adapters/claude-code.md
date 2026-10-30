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
| Skill | `.claude/skills/<name>/SKILL.md`, or a skill in the `cornerstone` plugin | full | Use `disable-model-invocation: true` for skills with side effects. |
| Role | `.claude/agents/<role>.md` with `name`, `description`, `tools`, `model` | partial | Tools can be limited. Paths cannot be limited by the role file. See "Protected paths". |
| Fresh session for each role | A separate `claude -p` run for each role | full | A sub-agent also has a fresh context, but the lead agent starts it. Use separate runs where P2 applies. |
| Headless run | `claude -p "<prompt>" --output-format json` | full | |
| Eval run | [claude-code/eval.yaml](claude-code/eval.yaml): the argv for each variant, the env, the tools of each role, and the JSON paths of the result | full | `stone eval` reads it (D26). `[TO CONFIRM]` that `--setting-sources project` keeps the user instruction file out of the run. For a hook eval, "without" removes the hook file and its entry in `.claude/settings.json`. If the entry stayed, `python3` could not open the file and would exit with code 2, so the harness would block each file-tool edit (D44). For a component that is not a role, both variants use `run.with`, so both load the same role file. |
| Select the role for a headless run | `claude -p --agent <role>` loads `.claude/agents/<role>.md` | full | Confirmed on 2026-10-18 (Claude Code 2.1): the tester and reviewer runs for `stone eval` followed their role files. `[TO CONFIRM]` if the `model` field of the role file or `--model` wins. |
| Hook before a file edit | `PreToolUse` hook with matcher `Edit\|Write\|MultiEdit\|NotebookEdit` in `.claude/settings.json`. Exit code 2 blocks the edit. | partial | The hook does not start for `Bash`, so it does not see a file write by a shell command (D39). K6 in CI is the control. |
| Role in the hook input | The hook input field `agent_type` | full | Confirmed on 2026-10-21 (Claude Code 2.1.292) with a hook that logged its input. `--agent tester` sent `agent_type: tester`, the `name` of the role file. A tester subagent sent `agent_type: tester` and an `agent_id`, also under a `--agent implementer` lead. A session with no role sent no `agent_type` (D55). |
| Hook before the session ends | `Stop` hook that runs the checks | full | Do not loop forever. The harness caps repeated blocks. |
| Model for each role | `model` field in the role file, from `defaults.role_models` in the model profile | full | |
| Permissions | `permissions` allow and deny lists in `.claude/settings.json`, and sandbox mode | full | |
| CI trigger | `anthropics/claude-code-action`, pinned to a commit SHA | full | v1.0.252 is `f27be6b65a4652f08a2ba3cff79114829b588967`. See "Trigger workflows". |
| CI authentication | Repository secret `CLAUDE_CODE_OAUTH_TOKEN`, made with `claude setup-token`. It is `[HARNESS_TOKEN]` in the core. | full | Uses the subscription, not an API key. `[TO CONFIRM]` usage limits for CI: the action docs do not give them. |

## Protected paths

The implementer must not change tests or checks (P2). This applies to a human implementer too. Use
two layers:

1. **Local hook.** A `PreToolUse` hook reads the role and the target path of a file tool. It exits
   with code 2 for a protected path. It does not see a `Bash` command. The hook finds the role in
   this order (D55):
   1. `agent_type` in the hook input, if it names a hook role. The harness sets it for a `--agent`
      session and in a subagent. In a subagent, it is the type of the subagent, not of the lead.
   2. The environment variable `STONE_ROLE`.
   3. `implementer`. A session with no role is an implementer, also in a `pair` session.

   The hook also limits the tester to the test paths and the planner to the plans path, and
   blocks each edit by the reviewer.
2. **CI check K6.** Each commit has the trailers `Role: <role>` and `Actor: human|agent`. A commit
   with no `Role:` trailer counts as an implementer commit. K6 fails if an implementer commit
   changes a protected path.

The CI check is the source of truth. The hook gives faster feedback. A git commit template can add
the trailers for human commits.

The protected paths are `paths.tests` and `paths.checks` from the repo config, plus `.claude/` and
`.cornerstone/`. These two folders hold the hook, the check, and the harness settings. With
`protect_instruction_files: true` (D87), the protected paths also hold `**/AGENTS.md`,
`**/CLAUDE.md`, and `**/CLAUDE.local.md`, in any case (D88). `instruction_files` in `components.yaml`
lists them, with a class of both cases for each letter. With the key on, K22
(`.cornerstone/checks/instruction_text.py`) also tests the text of each tracked instruction file (D89). A value can
be a glob. The hook and K6 import one match module, `.cornerstone/lib/path_match.py`, from the
template `claude-code/templates/lib/path_match.py` (D62). If the module is missing or broken, the
hook blocks each edit. `stone specialists` uses the same module for `when.paths` (D65).

The hook makes the target path relative to the git work tree that holds the file. This is
necessary because `CLAUDE_PROJECT_DIR` is the main checkout, also in a linked worktree under
`.claude/worktrees/<name>/`. Thus a worktree gets the same rules as the main checkout. A file
outside the project repo is not blocked.

`stone render` writes the hook to `.cornerstone/hooks/protect-paths.py` and K6 to
`.cornerstone/checks/protected_paths.py`. It merges this entry into `.claude/settings.json` and keeps
the other keys. The hook catches edits by the file tools only. A `Bash` command such as `sed -i`,
a `>` redirect, `tee`, `cp`, `mv`, `git checkout <ref> -- <path>`, or a script can still change a
file. The hook does not parse `Bash` commands, because a parse is partial (D39). The adapter does
not configure the sandbox for this. These are the limits:

| Shell write | Control |
| --- | --- |
| An implementer commit that changes a protected path | K6 fails in CI. |
| A commit with a false `Role:` trailer | None in CI. K6 reads the trailer. The reviewer and G4 are the control. |
| A tester, planner, investigator, or reviewer write outside its paths | None in CI. The reviewer and G4 are the control. |
| A role session that starts a subagent of a different role, for example an implementer that starts a tester | None in CI. The hook uses the role of the subagent (D55). The reviewer and G4 are the control. |
| A change that is not committed | Nothing to merge. |

The `hook.protect-paths` eval (`evals/hook-protect-paths/`) pins these limits for the implementer.

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
shared run step is `workflows/parts/run-role.yml`. The shared frame step of the post job is
`workflows/parts/frame-report.yml`.

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
| `claude_args` | `--agent <role> --model <model> --max-turns 30 --add-dir <event folder> --allowedTools "Read(./**),Read(/<event folder>/**)" --disallowedTools Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch --json-schema <report schema>` | The role reads and reports. It cannot change files or run commands. It reads only the checkout and the event folder (D32). Its only output is the report. It stops with an error after 30 turns (D38). |

The action returns the report in `structured_output`. The model returns it with the tool
`StructuredOutput`, which exists only in a run with `--json-schema`. With `--agent`, the `tools:`
list of the role file limits the tools of the run. So each role file lists `StructuredOutput` (D71).
Without it, the run ends with `subtype: success` and no `structured_output`, and the run job fails
(issue #166). In a session with no `--json-schema`, the name has no effect.

| Tested on | Version | Result |
| --- | --- | --- |
| Claude Code | 2.1.292 | `--agent` with `StructuredOutput` in `tools:` returns `structured_output`. Without it, no `structured_output`. |
| `anthropics/claude-code-action` | v1.0.252 | The run job fails with "Claude did not return structured_output" when the role file does not list the tool. |

The post job:

1. Reads the report from the job output through `env` (dossier F8).
2. Frames the report (D38). A fixed header says that a model wrote the text from untrusted event
   text. Each line of the report goes in a quote. A zero-width space after each `@` stops each
   mention, so the comment notifies no person or team. A zero-width space after each `</` stops an
   end tag, so the report cannot close the quote. The text looks the same.
3. Posts the framed file with `gh`.

Each job has a time limit (D38). The run job stops after 20 minutes, and the post job after 5
minutes. Without a limit, a job can run for 360 minutes (dossier F13). If the role stops at a limit,
the run job fails and the post job does not run.

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
| Tool allowlist: Read, Grep, Glob, StructuredOutput | No shell, no edits, no web fetch. The only output is the report. |
| Read rules only for `./**` and the event folder | Read, Grep, and Glob cannot open a file outside the checkout, such as `/proc/self/environ` with the harness secret. An unscoped `Read` rule allows all paths, and the report is public (D32, dossier F12). |
| Event text in a file, not in the prompt or a `run` script | The text cannot inject shell commands (dossier F8). |
| The post job posts the report as text | A report cannot apply labels. The investigator proposes labels, and a human approves them and the severity at G4. |
| The post job frames the report (D38) | A reader sees which text the model wrote. The report cannot notify a person or a team with a mention, and it cannot leave the quote (dossier F14). |
| A turn limit on the role and a time limit on each job (D38) | A spam issue or an injected loop cannot run the paid model for hours (dossier F13). |
| Bug-triage: the post job has only `issues: write` | No write token beyond comments and labels. No contents, PR, or workflow write. |
| GitHub redacts a job output that contains a secret | A report with the harness secret or the job token is not posted (dossier F9). |
| `github.token` expires when the job ends | A leaked token is read-only and short-lived. |

Limits that stay:

- The report can carry injected text or wrong labels. A human reads each report before acting.
  The frame marks the text, but a link in the quote still works.
- Each new issue from any account starts one run for `ci:issue-opened`. The limits cap the cost of
  one run, not the number of runs. The concurrency group is one issue, so it does not slow a flood
  of issues. The owner chose no author gate, because any user can report a bug (D38).
- The run job can read all repo files. Do not keep private data in a repo that runs these workflows.
- The role has no web tools. A step that reads a web page, for example release notes, uses only the
  event data and the repo. Do that step in a local run (`command`) if the report needs more.
- The action process has the harness secret. The allowlist blocks the shell, and the Read rules
  block the files outside the checkout, but the risk is not zero (dossier F10, F12).
- GitHub redacts a secret in a job output only as plain text. An encoded secret (for example
  base64) is not redacted. Do not add an unscoped `Read`, `Grep`, or `Glob` rule.

## Version pins

P9 says to pin the harness, its extensions, its plugins, and the framework (D91, dossier F20). This
table shows the state of each pin. Issue #225 closes the gaps.

| Dependency | Where it runs | Pin now | Gap |
| --- | --- | --- | --- |
| `anthropics/claude-code-action` | Trigger workflows | Commit SHA (v1.0.252) | None |
| Claude Code CLI | Trigger workflows | The action SHA fixes the version: v1.0.252 installs 2.1.302. | The action gets the CLI through `curl -fsSL https://claude.ai/install.sh \| bash -s -- <version>`. The script is not pinned or hashed. |
| `stone` | G3 workflow | The commit SHA in `framework_commit`, else the tag `v<framework_version>` (D92). PyYAML and setuptools have a version and hashes. | A repo with no `framework_commit` still installs from the tag. |
| Cornerstone plugin | Developer machines | The marketplace at a release tag, `brawblan/ai-workflow#vX.Y.Z` (D94). The plugin files come from that tag. | A tag, not a commit: the marketplace source has no `sha` field. Tag protection keeps the tag fixed. An add with no `#ref` follows `main`. |
| Release tags `v*` | GitHub repo | Two tag rulesets (D94): no update or deletion for anyone, and creation by an admin only. | The owner applies the rulesets. Until then, each tag can move. |
| Claude Code CLI and editor extension | Developer machines | None. Auto-update is on by default. | A bad release installs with no review. |

### Install the plugin from a pinned ref

The `cornerstone` entry in `.claude-plugin/marketplace.json` has a relative-path source. Thus the
plugin files come from the clone of the marketplace, at the ref of the marketplace. A pin of the
marketplace to a release tag also pins the plugin (dossier F21).

| Step | Command |
| --- | --- |
| Add the marketplace at a release tag | `/plugin marketplace add brawblan/ai-workflow#vX.Y.Z` |
| Install the plugin | `/plugin install cornerstone@brawblan` |
| Check the pin | `claude plugin marketplace list --json` shows `"ref": "vX.Y.Z"` for `brawblan`. |

For a team repo, put the pin in `.claude/settings.json`, so that a change to it is a reviewed diff.
`claude plugin marketplace add brawblan/ai-workflow#vX.Y.Z --scope project` writes the declaration.

```json
{
  "extraKnownMarketplaces": {
    "brawblan": {
      "source": { "source": "github", "repo": "brawblan/ai-workflow", "ref": "vX.Y.Z" }
    }
  },
  "enabledPlugins": { "cornerstone@brawblan": true }
}
```

To move the pin:

1. Read the plugin diff between the two tags: `git diff vX.Y.Z vA.B.C -- plugins/cornerstone`.
2. Change `ref` in the settings file in a PR. A human reviews it.
3. After the merge, run `/plugin marketplace update brawblan` and restart Claude Code.

Do not move the pin with a second `marketplace add`: it prints `already on disk` and keeps the old
source. Do not use `marketplace remove` either. It uninstalls the plugin and deletes its data. For a
user-scope add, change `ref` in `~/.claude/settings.json`.

| Choice | Gain | Cost |
| --- | --- | --- |
| Auto-update on (the `/plugin` menu, or `autoUpdate` in managed settings) | Fixes arrive with no action. | A bad push, or a moved ref, arrives with no review. |
| Auto-update off, marketplace at a tag (default for this repo) | Each change waits for a reviewed pin move (P9). | A security fix also waits for the pin move. |

Background auto-update is off for this marketplace by default. Keep it off. An update gets the
newest commit of the pinned ref, so a moved tag reaches each user. The tag rulesets below stop that.
A user gets a new copy only when `version` in `plugin.json` changes.

Facts to test:

- `[TO CONFIRM]` if `ref` takes a commit SHA. The docs say "branch or tag". Checked:
  https://code.claude.com/docs/en/plugins/marketplace-reference.md
- `[TO CONFIRM]` that `marketplace update` checks out the new ref after a change of `ref` in a
  settings file. Checked: https://code.claude.com/docs/en/plugins/cli-reference.md
- `[TO CONFIRM]` that a user-scope add writes `extraKnownMarketplaces` in `~/.claude/settings.json`.
  The docs say only "user settings". Checked: https://code.claude.com/docs/en/plugins/create-marketplace.md

### Protect the release tags

`stone upgrade` reads the commit of a release tag (D92), and the plugin pin follows a tag. Thus no
person may update or delete a `v*` tag. Only a repo admin may create one. Two tag rulesets do this
(dossier F22). A bypass actor bypasses each rule of its ruleset, so the rules with no bypass are in
a ruleset of their own.

| Ruleset | Rules | Bypass |
| --- | --- | --- |
| `release-tags-fixed` | `update`, `deletion`, `non_fast_forward` | None |
| `release-tags-create` | `creation` | Repository role admin |

The owner applies them once. It is a repo settings change, not a reviewed PR:

```bash
gh api -X POST repos/brawblan/ai-workflow/rulesets --input - <<'EOF'
{"name": "release-tags-fixed", "target": "tag", "enforcement": "active", "bypass_actors": [],
 "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
 "rules": [{"type": "update", "parameters": {"update_allows_fetch_and_merge": false}},
           {"type": "deletion"}, {"type": "non_fast_forward"}]}
EOF
gh api -X POST repos/brawblan/ai-workflow/rulesets --input - <<'EOF'
{"name": "release-tags-create", "target": "tag", "enforcement": "active",
 "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
 "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
 "rules": [{"type": "creation"}]}
EOF
```

To check them, read them back. Both must show `enforcement: active` and the include `refs/tags/v*`:

```bash
gh api repos/brawblan/ai-workflow/rulesets --jq '.[] | select(.target == "tag") | {id, name, enforcement}'
gh api repos/brawblan/ai-workflow/rulesets/<id> --jq '{rules: [.rules[].type], include: .conditions.ref_name.include, bypass: .bypass_actors}'
```

Do not test the rules with a push to an existing tag. If a ruleset is missing, that push moves the
tag. If a release is bad, do not move its tag. Release a new patch version.

- `[TO CONFIRM]` that `actor_id` 5 is the admin repository role. The docs do not list the IDs.
  Checked: https://docs.github.com/en/rest/repos/rules?apiVersion=2022-11-28

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
| G1 | Issue form with required fields, and a label (default `agent-ready`) that a human adds to ask for a readiness check (D41) |
| G2 | A plan PR that a human approves, or a `plan-approved` label from a human |
| G3 | Required status checks in branch protection or a ruleset |
| G4 | Required PR review |
| G5 | A deployment environment with required reviewers |

`stone render` writes K16 to `.github/workflows/cornerstone-k16.yml` for each profile that lists K16
(D30). The job runs on `pull_request_target`, so GitHub runs the workflow file from the base branch.
A spike branch cannot change or remove it. The job checks out no code and has `permissions: {}`
(dossier F11). It gets the branch names only through `env`. Add the `k16` job as a required status
check on the main branch and on the integration branch (D33).

### Env and secrets of the All checks step

`ci.env` and `ci.secrets` in the repo config add an `env:` block to the `All checks` step of the G3
job (#163). No other step and no role job gets it. A secret appears only as `${{ secrets.NAME }}`.
`stone check` fails a name that does not match `^[A-Z_][A-Z0-9_]*$`, a name in both keys, and a
`ci.env` value that has `${{`.

GitHub does not pass secrets to a PR from a fork. The variable is then empty. A test that needs a
secret must still skip when the variable is empty.

### G3 setup steps (`ci.setup`)

The G3 workflow `cornerstone-checks.yml` renders the steps of `ci.setup` before the `Install` step
(D73). The key `node` renders `actions/setup-node` v7.1.0, pinned to the commit
`949feb2413d6458794dcd2491c4babbbce0c15c1`, with `cache: npm`. A `uses` item of `ci.setup.steps` must
be pinned to a commit SHA of 40 characters. With `adoption: opt-in`, each step has the marker `if`.
Update the pin with a new tag SHA when you raise the action version.

## Role files (generated)

| Role | Tools | Default model |
| --- | --- | --- |
| shaper | Read, Grep, Glob, issue read and write | the strongest model |
| planner | Read, Grep, Glob, Write (plans path only, enforced by hook) | the strongest model |
| implementer | Read, Grep, Glob, Edit, Write, Bash | repo config |
| tester | Read, Grep, Glob, Edit, Write (tests path only, enforced by hook), Bash (the hook does not see it, D39) | repo config |
| reviewer | Read, Grep, Glob, Bash (read-only commands) | repo config |
| investigator | Read, Grep, Glob, Edit, Write (reports path, or a `spike/` branch, enforced by hook), Bash (the hook does not see it, D39) | repo config |

Each role file also lists `StructuredOutput`, so a trigger run can return its report (D71).

## Existing plugin skills

| Skill | Framework place | Change needed |
| --- | --- | --- |
| `project-setup` | full-project, Shape | Becomes the Shape step of `setup`. Stays usable alone. |
| `sdd-plan`, `sdd-build` | Plan, Build | Removed in plugin 0.5.0 (D18). The planner, implementer, and tester role files do this work. |
| `ticket-delivery` | Verify, Deliver | Done in plugin 0.4.0: it collects the tester, reviewer, and check output as evidence. It does not self-verify. Since plugin 0.7.0 it also branches, commits, and opens the PR with the evidence sections (K14) and the role trailers. It replaces `dev-pr`. |
| `ste-writing` | Writing standard ([writing.md](../writing.md)) | Load it in each role that writes human-facing text. Add the blind A/B eval. K17 covers the measurable rules. |
