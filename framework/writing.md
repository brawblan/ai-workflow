# Writing standard

Human-facing text in the framework and in each target repo follows ASD-STE100 (Simplified Technical
English, STE). The goal is text that a reviewer understands on the first read. This lowers the cost
of each gate (P10, P11).

STE is a component like any other. It stays only while the evidence shows that it helps (P5).

## Rule source

The rules and the shared dictionary are in one file:
[`plugins/workflow/skills/ste-writing/references/ste.md`](../plugins/workflow/skills/ste-writing/references/ste.md).
This file does not copy them. It refers to them by number (for example "rule 8").

Each target repo MAY add a project dictionary, by default `docs/style/ste.md`. Its terms come first.

## Scope

| Text | Main reader | Standard |
| --- | --- | --- |
| PR body, commit message | human | STE |
| Plan artifact, decision log, progress notes | human | STE |
| Test report, review findings, findings report, triage comment | human | STE |
| Check failure messages (K1 to K17) | human and agent | STE |
| Agent replies to a human (chat, PR comments) | human | STE |
| Framework docs and repo docs (`README`, `docs/`) | human | STE |
| Instruction file, skills, role files | agent | The model profile decides. Use STE only where an eval shows a gain. |
| Code, code blocks, inline code, URLs, quotes | — | Not in scope |

Apply the standard to new text, and to text that you change for another reason. Do not rewrite old
text only for style. A style-only rewrite makes a large diff with no change in meaning (P10).

## Enforcement

Two parts, by the P6 order (check before skill):

| Part | Covers | How |
| --- | --- | --- |
| Check K17 | The rules that a program can test | Runs on the new and changed lines of human-facing files and of the PR body |
| Writing skill | The rules that need judgment | The role that writes a human-facing artifact loads the skill before it writes |

### What K17 tests

| Rule in `ste.md` | K17 test | Result |
| --- | --- | --- |
| 1. Dictionary terms | A term from a "Do not use" column appears | fail |
| 2. Simple tenses | A progressive verb form ("is running") appears | warning only (adjectives such as "is missing" also match) |
| 5. Vague words | A word from the vague-word list appears | fail |
| 8. Sentence length | A procedure sentence has more than 20 words, or a description sentence more than 25 | fail |
| 11. Active voice | A procedure step looks passive (a form of "be" plus a past participle) | warning only |
| 13. Paragraph length | A paragraph has more than 6 sentences | fail |

Rules 3, 4, 6, 7, 9, 10, 12, 14, and 15 need judgment. The writing skill and the reviewer role cover
them.

The dictionary test can also match a correct use of a word in another sense. To mark a false
positive, add `<!-- ste-ignore -->` at the end of that line. The reviewer checks each mark.

K17 starts as a warning for 2 weeks in each repo, as for every new check (see
[checks.md](checks.md#rules-for-checks)). Then it blocks new and changed text. In this repo it
blocks since D45, after a replay on the merged PRs found no false positive.

## Evidence (P5)

The manifest has no entry for the writing standard (D51). `stone render` writes a manifest entry
only for a rendered component, and K17 and the `ste-writing` skill are not rendered components. A
human reviews the standard every 6 months. The human records the result in the PR that changes it.

| Measure | How | Keep STE when |
| --- | --- | --- |
| Review time | Lifecycle metric "Human time" at G2 and G4, before and after STE | Human time does not increase |
| Rework | Lifecycle metric "Rework" | Rework does not increase |
| Blind A/B | Each quarter, a human rates 10 pairs of the same artifact, one in STE and one not. The human does not know which is which. Question: "Which one is faster to understand and act on?" | STE wins 6 or more of 10 pairs |

If STE loses on a type of text (for example commit messages), remove that type from the scope. Record
the result in that PR.

For agent-facing text, the [adapter-refresh](profiles/adapter-refresh.md) evals decide. Run each
affected eval with the STE version and with the vendor-style version. Keep the version that wins.
