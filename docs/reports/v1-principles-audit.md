# v1 principles audit

This report tests the repo against its own principles P1 to P12 before the `v1.0.0` tag.

- Date: 2026-10-19.
- Base: `origin/main` at commit `8e16299` (after PR #89).
- Sources: the framework files, `.github/workflows/`, `.cornerstone/`, `stone/src/`, the 61 merged
  PRs, the open issues, and the GitHub repo settings.
- This report changes no code and fixes no gap.

## Result

The repo follows 1 principle, partly follows 9, and has a gap in 2 (P3 and P5).

| Principle | Verdict | Reason |
| --- | --- | --- |
| P1 Checks decide | Partly | CI runs the checks, but K7, K14, and K17 only warn, and no check is a required status check. |
| P2 Writer and judge | Partly | K6 blocks implementer commits to protected paths. It trusts the `Role:` trailer and does not limit the tester. |
| P3 Judgment into inputs | Gap | No issue has all Definition of Ready fields, and no deterministic G1 check exists. |
| P4 Context budget | Partly | The files are small, but no check in this repo tests the instruction file or the skill size. |
| P5 Each component earns its place | Gap | All 10 manifest entries have `models_tested: []`. Few components have an eval. No job finds a past review date. |
| P6 Enforce what you can state | Partly | Many rules are checks, but some precise rules in `AGENTS.md` and the repo config have no check. |
| P7 Ceremony scales with risk | Follows | `stone check` rejects a profile without a plan form or valid gates, and compares them with `gates.md`. |
| P8 State in files | Partly | Decisions, the roadmap, and eval results are in files. No decision-log file was ever committed. |
| P9 Bounded autonomy | Partly | The workflows have minimum permissions and pinned actions. The `main` ruleset is disabled, and a direct push occurred. |
| P10 Volume is a cost | Partly | The limit is 600 lines. 11 of 36 PRs after K7 were over it, and K7 rejects 3 of their waivers. |
| P11 Make the work visible | Partly | K14 runs on each PR in warn mode. 16 of 44 PRs after K14 (PR #18) fail it. |
| P12 Neutral core | Partly | `stone check` passes, but D40 names two spec tools in the core, and `render.py` names a harness folder. |

## P1. Checks decide

Verdict: Partly.

| Evidence | Finding |
| --- | --- |
| `.github/workflows/cornerstone-checks.yml:32`, `:49` | K7 and K14 run with `--mode warn`. |
| `.github/workflows/stone.yml:39`, `:47` | K17 runs with `--mode warn`. The roadmap moves it to block on 2026-10-31 (issue #62). |
| `.github/workflows/cornerstone-checks.yml:56` | The "All checks" step runs `stone check-writing` with no `--mode`. The default is `warn` (`stone/src/stone/cli.py:48`). |
| GitHub ruleset `main` (id 25320579) | The ruleset is `disabled`. It has only the `deletion` and `non_fast_forward` rules. No check is a required status check. |
| PR #89 | K7 reported a warning (1149 lines, no waiver). The PR merged. |

What works:

- G3 runs in CI, outside the agent session (`cornerstone-checks.yml`, `stone.yml`).
- K6, the unit tests, and `stone check` fail the job.
- Each merged PR from #2 to #89 has only successful or skipped check runs. PR #1 has no check runs.

When the warn checks block:

| Check | Where | Block date in the roadmap | Issue |
| --- | --- | --- | --- |
| K17 | `stone.yml` | 2026-10-31 | #62 |
| K14 | `stone.yml` | 2 weeks after the K14 step is in that workflow. The step is not in `stone.yml` today. | #63 |
| K14, K7, K15 | G3 template | 2 weeks after stone 0.7 (PR #23), K7 (PR #26), and K15 (PR #27). All merged on 2026-10-18, so the earliest date is 2026-11-01. | #63 |
| K4, K5, K8, K10, K11, K12 | G3 step templates (`continue-on-error: true`) | 2 weeks after PR #30 | #63 |
| K18, K19 | `stone check` | 2 weeks after their merge | #64 |

The v1 exit criteria (`framework/README.md:194`) need K6, K7, K14, K15, and K16 to block. Thus the
tag cannot be on time before 2026-11-01.

Other findings:

- The G3 workflow installs stone from the tag `v0.5.0` (`cornerstone-checks.yml:37`). The
  `framework_version` in `.cornerstone/config.yaml:2` is `0.5.0`, but stone is `0.9.0`. K14 in G3
  runs the PR #18 code.
- The single-ticket profile lists K1, K2, and K9 (`framework/profiles/single-ticket.md:17`). This repo
  has no lint, type check, or complexity command (`.cornerstone/config.yaml:10`). So G3 does not run
  them, and `waivers: []` records no reason.

## P2. Separate the writer from the judge

Verdict: Partly.

| Evidence | Finding |
| --- | --- |
| `.cornerstone/checks/protected_paths.py:26-29` | K6 reads the last `Role:` trailer. Any value except `implementer` skips the commit. A false trailer passes (issue #81). |
| `framework/checks.md:66` and `protected_paths.py:28` | The doc and the code disagree. Rule 1 says a check is read-only for the implementer and the tester. K6 limits only the implementer. A `Role: tester` commit can change `.cornerstone/checks/`. |
| `framework/README.md:102` (D39) | The hook does not see a shell write. K6 is the only control in CI, and only for implementer commits. |

Commit trailers on `main` (206 commits that are not merges):

| Trailer | Count |
| --- | --- |
| `Role: implementer` | 86 |
| `Role: tester` | 54 |
| `Role: generator` | 22 |
| `Role: maintainer` | 2 |
| No `Role:` trailer | 42 |
| `Actor: agent` | 162 |
| `Actor: human` | 2 |

- Each commit that changes `stone/tests/` has `Role: tester` or no trailer. No implementer commit
  changes a test.
- 8 commits with no trailer change a K6 path. Two are squash merges (PRs #51 and #52), so the
  `Role:` trailers of the PR commits are lost on `main`. The other six are from PR #7 or earlier, before K6 ran in CI.
- The trailers do not show a different actor. Each tester and implementer commit has
  `Actor: agent`, and no trailer names a session.
- P2 says the pipeline MUST start the tester and the reviewer (`framework/principles.md:39`). The only
  pipeline in this repo is the label workflow. It starts the shaper only
  (`.github/workflows/cornerstone-single-ticket-label.yml:48`). A human or a parent session starts
  the tester and the reviewer.

## P3. Judgment goes into the inputs

Verdict: Gap.

| Evidence | Finding |
| --- | --- |
| Issues #38 to #85 (28 issues) | 0 of 28 have all the Definition of Ready fields. 23 have acceptance criteria. 2 have non-goals. None has a test oracle or a `Personas:` line. |
| `framework/gates.md:32`, `.github/` | Single-ticket sets G1 to `check`. No deterministic G1 check exists. The repo has no issue template. |
| `cornerstone-single-ticket-label.yml:66-71` | The label workflow asks a model (the shaper) to list the missing fields. That is a report, not a check. |

The Definition of Ready is in `framework/workflow-model.md:92`. Non-goals and the test oracle are
on lines 98 and 99.

## P4. Context is a budget

Verdict: Partly.

| Evidence | Finding |
| --- | --- |
| `AGENTS.md` (85 lines), `CLAUDE.md` (1 line) | The instruction file is under the 300-line limit. |
| `plugins/workflow/skills/*/SKILL.md` | The largest skill has 130 lines (`dev-pr`). Each description has 474 characters or fewer. The model profile limit is 500 lines. |
| `framework/principles.md:64` | The Enforce item needs a size check and a skill lint. K15 is not rendered here, because single-ticket does not list K15. `stone check` has no skill lint. |

`AGENTS.md` repeats facts that are also in the repo, for example the commands in
`.cornerstone/config.yaml:11-13`. The rule says that the file MUST contain only facts that the agent
cannot find. This is a small cost at 85 lines.

## P5. Each component earns its place

Verdict: Gap.

| Evidence | Finding |
| --- | --- |
| `.cornerstone/manifest.yaml:12` and the 9 other entries | Each entry has `models_tested: []`. The `role.tester` eval ran on a model (`evals/results/20261018-085807-role.tester-claude-opus-5-5.md`), but its entry is empty. |
| `framework/adapters/claude-code/components.yaml` | 17 component entries. Eval folders exist for 3 of them (`role.tester`, `role.planner`, `hook.protect-paths`). `hook.settings` shares the hook folder. Only the 2 role evals have a result. |
| `framework/principles.md:74` | No scheduled CI job opens an issue for a component past its review date. The first `review_by` is 2027-04-17. |

Other findings:

- The task names 22 components. I count 17 entries in `components.yaml`. With the 6 G3 steps, the
  count is 23. The owner can confirm the correct base.
- Each manifest entry has an owner (`brawblan`), an eval key, and a `review_by` date. `stone check`
  tests the eval key and the date (D43). It does not test `owner` or `models_tested`.
- `framework/writing.md:64` says the manifest has the entry `rule.writing-standard`. The manifest
  and `components.yaml` have no such entry. The doc and the code disagree.
- The plugin skills have no manifest entry. `AGENTS.md` asks for an eval plan and a review date for
  each new skill. Only `cornerstone-setup` has one, with the status "Planned. No eval has run."

## P6. Enforce what you can state

Verdict: Partly.

These rules are checks: K6, K7, K14, K17, the profile and gate rules, the D34 branch-name rule, and
the D43 component rule.

These precise rules have no check:

| Rule | Where | Possible check |
| --- | --- | --- |
| Pin each action to a commit SHA | `AGENTS.md:66` | A grep for `uses:` without a 40-character SHA. All pins pass today. |
| Pass event text through `env` | `AGENTS.md:67` | A scan of `run:` for `github.event`. All steps pass today. |
| Commit format `type(scope): summary` | `AGENTS.md:74` | A commit-message check |
| Increase the plugin version when a skill changes | `AGENTS.md:60` | A diff check |
| Never push to `main` | `AGENTS.md:73` | The disabled ruleset (see P9) |
| PR sections Summary to Rollback plan | `AGENTS.md:76` | K14 tests 4 other sections only |
| `function_lines: 60`, `cyclomatic: 10` | `.cornerstone/config.yaml:21-22` | K9. An approximate AST count finds 1 function over 60 lines and about 21 over a complexity of 10 in `stone/src/`. |

The manifest has no `instruction` entry, so the "why not a check" field (`framework/principles.md:83`)
has no entry to test.

## P7. Ceremony scales with risk

Verdict: Follows.

| Evidence | Finding |
| --- | --- |
| `stone/src/stone/framework_check.py:86-116` | `stone check` fails a profile without `plan_form` or `gates`, with a wrong gate value, or with a gate that differs from `gates.md`. |
| `framework_check.py:107` | A profile that builds code for a PR must set G3 to `required`. |
| `stone check` on this branch | 0 findings |

Note: render and check do not read `overrides` or `waivers` from the repo config (issue #78). A repo
can record a waiver to remove a gate, but no tool reads it.

## P8. Small units, fresh sessions, state in files

Verdict: Partly.

| Evidence | Finding |
| --- | --- |
| `framework/README.md:60-106`, `:112-198` | Decisions D1 to D43 and the roadmap are in a versioned file. |
| `evals/results/` | The eval results are committed files (D36). |
| `framework/adapters/claude-code/templates/agents/implementer.md:25` | The implementer writes the decision log at `docs/plans/<ticket-id>.decisions.md`. No such file was ever committed. The decision logs are in the PR bodies only. |

The 86 implementer commits did not write a decision-log file. Either the sessions did not use the
role file, or the file had no effect. I did not read the transcripts, so I cannot say which.

## P9. Bounded autonomy

Verdict: Partly.

| Evidence | Finding |
| --- | --- |
| Ruleset `main` (`enforcement: disabled`) | No PR requirement and no required check on `main`. Commit `94c5ebc` and its revert `2a5b2e7` went to `main` directly on 2026-10-17, after PR #2. |
| `.claude/agents/reviewer.md:4`, `.claude/agents/shaper.md:4` | Both roles have the shell tool. The reviewer "changes no file", but the shell can write (D39). |
| `cornerstone-single-ticket-label.yml:54`, `:77`, `:101` | The trigger role has the model secret, the untrusted issue text, and a public report. D32 limits the reads, and D38 frames the report. |

What works:

- Each workflow sets top-level `permissions` to `contents: read` or `{}`. Write scopes are on single
  jobs only.
- Each `uses:` in `.github/workflows/` and in the templates is pinned to a 40-character SHA.
- Event text reaches each `run:` step only through `env`.
- The trigger role has a turn limit and a job time limit (D38).
- Platform secret scanning and push protection are on. They cover K13.

## P10. Volume is a cost

Verdict: Partly.

| Evidence | Finding |
| --- | --- |
| `.cornerstone/config.yaml:20`, `.cornerstone/checks/change_size.py:16` | The limit is 600 changed lines. |
| PRs #27 to #89 | 11 of the 36 PRs after K7 (PR #26) are over 600 lines. |
| `change_size.py:47` | K7 accepts only a heading that starts with "Waiver (P10)". PRs #35 and #57 use "Size waiver (P10)". PR #89 has the waiver in a list item. K7 accepts none of the three. |

Over-limit PRs before K7: #1, #16, #18, #21, #22, #24, and #25. Their waivers do not use the K7
format, because K7 did not exist.

PR #89 is the example from the task. K7 warned: "The diff has 1149 changed lines. The limit for
single-ticket is 600." The body has no `Profile:` line. Its waiver is a list item, and the PR merged.

If K7 blocks with the current parser, it fails PRs that a human accepted. Fix the parser or the
waiver format first.

## P11. Make the work visible

Verdict: Partly.

| Evidence | Finding |
| --- | --- |
| `cornerstone-checks.yml:44-49` | K14 runs on each PR in warn mode. |
| `stone check-evidence --mode block` on each merged PR body | 16 of the 44 PRs from #19 to #89 fail. Examples: #68 to #73, #75, #76, #83, #84. |
| PRs #86, #87, #88, #89 | The 4 latest PRs pass K14. |

Most failures are docs-only PRs (the guides). This data can help the owner decide whether K14 needs
a docs exception before it blocks.

## P12. Neutral core, thin adapters

Verdict: Partly.

| Evidence | Finding |
| --- | --- |
| `stone check` | 0 findings. The check covers `*.md` in `framework/` outside `adapters/`. |
| `framework/README.md:103` (D40) | The core names two spec tools (Spec Kit and BMAD). The name list in `stone/src/stone/framework_check.py:29-30` does not have them. |
| `stone/src/stone/render.py:32` | The generator hard-codes the harness folder `.claude/`. The adapter does not give it. |

Other findings:

- The check reads only `*.md` files (`framework_check.py:135`). No other file type is in the core
  today.
- The name list has no model family names. A text search of the core found none.
- `framework/generator/design.md:154` assumes git and GitHub. P12 does not name the CI host, so this
  is not a break of the rule.

## Dossier citations

I picked 5 IDs at random (seed 20261019) from the IDs that the principles, decisions, and checks
cite.

| ID | Cited by | Exists | Does the source say it? |
| --- | --- | --- | --- |
| E1 | P8 | Yes | Not verifiable. S2 is talk notes with no public text. |
| B15 | P2 | Yes | Not verifiable. S1 is talk notes with no public text. |
| C3 | `framework/checks.md:62` | Yes | Not read. S21 is a book. The text agrees with the book's known definition of a fitness function. |
| F8 | D31, D38, the label workflow | Yes | Yes. S35 and S36 say to pass untrusted input through an environment variable. They name the issue title and the PR title. Neither names an issue label. |
| H2 | P3 | Yes | In part. The S12 page returned HTTP 403. Search results confirm "Humans steer. Agents execute." I did not confirm the second sentence. |

Note: the dossier IDs `D1` to `D11` and the decisions `D1` to `D43` use the same letter. P3 cites
dossier `D1`, which a reader can confuse with decision D1.

## Gaps for v1

Ranked by severity. Each line gives a suggested issue title.

1. High. The `main` ruleset has the status `disabled`, so no check can block a merge.
   Issue: `chore(repo): enable the main ruleset with PR-only merges and required G3 checks`.
2. High. K7, K14, K15, and K17 only warn. The v1 exit criteria need them to block.
   Issues #62 and #63 exist. The earliest date is 2026-11-01.
3. High. K7 rejects the waiver forms in PRs #35, #57, and #89.
   Issue: `fix(stone): make K7 accept the waiver forms of merged PRs, or document one exact form`.
4. Medium. `models_tested` is empty in all 10 manifest entries, and D43 does not test it.
   Issue: `fix(stone): write models_tested from eval results and test owner and models_tested (P5)`.
5. Medium. K6 does not limit the tester, but `framework/checks.md:66` says it does.
   Issue: `fix(framework): decide if K6 limits the tester (checks.md rule 1 vs protected_paths.py)`.
6. Medium. Single-ticket sets G1 to `check`, but no G1 check exists. No open issue meets the
   Definition of Ready. Issue: `feat(stone): add a G1 check for the Definition of Ready fields`.
7. Low. D40 names spec tools in the core, and the name list misses them.
   Issue: `fix(framework): move tool names out of D40 and extend the P12 name list`.
8. Low. `framework/writing.md:64` names a manifest entry that does not exist.
   Issue: `fix(framework): add rule.writing-standard to the manifest, or change writing.md`.

## Gaps after v1

- No scheduled job finds a past `review_by` (P5). Do it before 2027-04-17.
  Issue: `feat(stone): render a scheduled job that opens an issue for each past review date`.
- 13 of 17 components have no eval folder. The hook eval has no model run (roadmap 4g).
- This repo has no K1, K2, or K9 command. About 21 functions in `stone/src/` are over the complexity
  limit (approximate count).
- No skill lint, and no K15 in this repo (P4).
- No decision-log file in `docs/plans/` (P8). The owner decides: the file or the PR body.
- The pipeline does not start the tester and the reviewer (P2).
- K6 trusts the `Role:` trailer (issue #81). The hook does not see a shell write (D39).
- The reviewer and the shaper have the shell tool (P9).
- Squash merges lose the `Role:` trailers on `main` (PRs #51, #52).
- G3 installs stone from `v0.5.0`. `framework_version` did not move with stone 0.9.0.
- The P12 check reads only Markdown and has no model family names.
- The dossier IDs `D1` to `D11` and the decision IDs share a letter.
- Sources S1 and S2 are talk notes with no public text. B15 and E1 rest only on them.

## What I did not check

- Session transcripts. I cannot say if each session did one unit of work or if a tester ran in a
  fresh session.
- The reviews on each PR, and who approved G4.
- The eval runner, `evals/`, and `stone/tests/`. Another session works on them.
- An eval run. I ran no model.
- The full dossier. I tested 5 of 74 cited IDs.
- The text of S1, S2, and S21, and the full text of S12.
- Branch rules for branches other than `main`, and the GitHub App settings.
- The other 9 profiles in a target repo. This repo renders single-ticket only.
- Whether the guides in `docs/guides/` match the code.
