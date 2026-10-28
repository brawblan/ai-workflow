# Review of the early blocking of K7, K14, K15, K17, and the repo commands

Issue #112, Decision [D79](../../framework/README.md#decisions). Date of the review: 2026-10-28.

## Result

- 2 false positives, both in K17 rule 8. K17 counted a dotted token as more than one word. This PR
  fixes the word count.
- K7, K14, and the repo commands had no false positive.
- 1 flaky test failed the repo command step once. PR #101 covered its cause.
- K15 did not run. No profile of this repo renders it.

## Scope

| Item | Value |
| --- | --- |
| Merged PRs | 64: 27 into `dev`, 37 into `main`. All by the owner. 0 bot PRs. |
| Merge dates | 2026-10-21 13:38 UTC to 2026-10-28 03:09 UTC |
| Cut-off date | 2026-10-28. The owner removed the wait for 2026-11-05. |
| Runs | The runs from 2026-10-21 of the `cornerstone-checks` job (84 runs) and of the `stone` job (147 runs), with each attempt |
| Checks | K7, K14, K15, K17 (changed lines and PR body), and the repo command step `All checks` |

## Findings

A run link is `https://github.com/brawblan/ai-workflow/actions/runs/<run>`.

| PR | Check | Class | Cause | Run |
| --- | --- | --- | --- | --- |
| #100 | All checks | Flaky | A hook eval test got `OSError 39` (directory not empty) on the cleanup of a temporary folder. The re-run on the same commit passed. | 39610955353, attempt 1 |
| #101 | All checks | True | The new test of the PR did not simulate the cleanup error. Commit `80f6823` fixed the test. | 39613961145 |
| #129 | K17 body | True | 2 sentences of 27 and 26 words | 39702279027, 2 attempts |
| #131 | K14 | True | The PR body had none of the 4 sections. The 2 re-runs read the old body. | 39704853368, 3 attempts |
| #133 | K17 body | True | 2 sentences of 27 and 37 words (lines 3 and 27) | 39711432435 |
| #133 | K17 body | False positive | Line 6 has 22 words. K17 counted `0.6.3` and `0.6.4` as 3 words each, so it reported 26. | 39711432435 |
| #149 | K17 body | True | 1 sentence of 27 words | 39847297573 |
| #151 | K17 body | True | 1 sentence of 36 words | 39873628120, 2 attempts |
| #170 | K14 | True | The PR body had no Confidence section. | 40010211995 |
| #173 | K7 | True | A release PR with 2525 changed lines and no waiver. The author added a waiver. | 40021312264, 2 attempts |
| #173 | K17 body | True | 1 sentence of 35 words | 40021312204, 2 attempts |
| #196 | K17 body | False positive | The sentence has 24 words. K17 counted `1.4.0` as 3 words and `versioning.md` as 2, so it reported 27. | 40617842342 |

The word counts above use the fixed count. The replay used the first version of each PR body, from
the edit history of the PR. K17 on changed lines had no failure.

## Count by check

| Check | PRs that failed | Findings | True | False positive | Flaky |
| --- | --- | --- | --- | --- | --- |
| K7 | 1 | 1 | 1 | 0 | 0 |
| K14 | 2 | 2 | 2 | 0 | 0 |
| K15 | 0 | 0 | 0 | 0 | 0 |
| K17 | 6 | 9 | 7 | 2 | 0 |
| All checks | 2 | 2 | 1 | 0 | 1 |

Each K17 sentence is one finding. Only #196 failed for a false positive alone. #133 also had 2 true
findings.

## Out of scope

- K6 failed 3 merged PRs (#133, #149, #167). The issue does not ask for K6.
- The unit test step of the `stone` job failed on #131 for 2 runs. A copy of a git folder met a
  `maintenance.lock` file. PR #132 fixed this race.

## Notes

- In this repo, a re-run of a job and an edit of the PR body do not read a new PR body. The author must push, or
  close and open the PR again. #131 and #173 show this.
- Each release PR (#173, #183) was over the size limit and needed a waiver. This is the documented
  K7 behavior. `ci.branches` (D74) skips K7 on a PR into `main`, if the owner wants that.
- Bot PRs: the owner chose a manual path. See
  [customization.md](../../framework/customization.md#bot-prs-dependabot-renovate). K6 fails a bot
  commit on a protected path. Issue #201 tracks this gap.
