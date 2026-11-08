# Use the code index

Use this guide to decide whether to keep the code index, turn it off, or use another indexer. The
index is `stone-index`, a local SQLite index of the files in a repo (D104). An agent asks the index
where a symbol is, and reads fewer files.

| | |
| --- | --- |
| Default | On. `stone render` adds the rule, the permission, and the build hook (D111). |
| Opt out | `code_index: none` in `.cornerstone/config.yaml` |
| Another indexer | `code_index` with `command`, `rule`, and `build` |
| Install | Render does not install `stone-index`. Install it yourself. |
| Reference | [indexer/README.md](../../indexer/README.md) |

## Result first

- The index lowered the mean cost in each eval. The saving over all scenarios is inside the noise.
- The clear saving is on large tasks over many files. Scenario M3 cost 25 percent less with
  `rule-show` than with `none`.
- The fixtures are synthetic. The trials used one model.
- Keep the index if your repo is large. Turn it off if it adds no value for your repo.

## What the index does

The build walks the repo, parses each file with tree-sitter, and writes the index to
`.cornerstone/index.db`. Later builds read only the files that changed. The index covers Python,
TypeScript, JavaScript, C, C++, C#, Rust, and Markdown. Other text files keep only their words.

| Command | What it does |
| --- | --- |
| `stone-index build` | Makes or updates the index. |
| `stone-index find <name>` | Prints the symbols with this name. |
| `stone-index show <name>` | Prints the lines of each symbol with this name. |
| `stone-index outline <path>` | Prints the symbols of one file. |
| `stone-index refs <path or module>` | Prints the links into a file and out of it. |
| `stone-index search "<words>"` | Prints the lines of the blocks that have all the words. |

Each query command updates the index first. `--no-update` skips this step. Options and exit codes:
[indexer/README.md](../../indexer/README.md#commands).

## Install

The release has an archive and a wheel for five targets: Linux x86-64 and arm64, macOS x86-64 and
arm64, and Windows x86-64. `SHA256SUMS` has the checksum of each file.

| Option | Command |
| --- | --- |
| Archive | Download `stone-index-vX.Y.Z-<target>.tar.gz` (`.zip` for Windows) and `SHA256SUMS`. Test the checksum, extract the archive, and put `stone-index` on your `PATH`. |
| Wheel | `uv tool install <wheel URL>` or `pipx install <wheel URL>` |
| Cargo | `cargo install --locked --git https://github.com/brawblan/ai-workflow --tag vX.Y.Z stone-index` |
| Clone | `cargo build --release --locked` in `indexer/` |

If `stone-index` is not on `PATH`, `stone index` prints the install commands and exits with code 2.
The rule that render adds starts with "If `stone-index` is on PATH", so a session without the
command ignores it. Details: [Install](../../indexer/README.md#install).

## Opt out, or use another indexer

The key `code_index` in `.cornerstone/config.yaml` sets the index. Run `stone render` after you
change it. The next render removes the entries that it added before. Full rules:
[Code index](../../framework/customization.md#code-index-code_index).

Opt out. This adds no rule, no permission, and no hook:

```yaml
code_index: none
```

Use another indexer. The `rule` has 1 to 3 lines, and its first line starts with the guard. The
`build` is optional:

```yaml
code_index:
  command: my-index
  rule: |
    - If `my-index` is on PATH, ask it before you search or read code.
    - Use `my-index query "<words>"`.
  build: my-index update .
```

## What the measurements show

### Evals

The eval `guidance.index` (`evals/index-guidance/`) compares three variants with the same prompt and
the same tool set:

- `none`: no text about the index.
- `rule`: the 2-line rule.
- `rule-show`: the rule, and one line that tells the agent to use `show` or `search --context`, not
  a whole-file read.

Each run used one model. Cost is the mean cost of a run in USD. SE is the standard error of the mean.

| Eval | Variant | Runs | Mean cost (SE) | Mean output tokens | Pass rate | Source |
| --- | --- | --- | --- | --- | --- | --- |
| 8 small scenarios, 224 files | `none` | 24 | 0.04369 (not in the record) | 238.5 | 24 of 24 | D107 |
| | `rule` | 24 | 0.04307 (not in the record) | 186.9 | 24 of 24 | D107 |
| 4 multi-file scenarios, 624 files | `none` | 36 | 0.05273 (0.00351) | 463.1 | 36 of 36 | D109 |
| | `rule` | 36 | 0.05215 (0.00286) | 400.7 | 36 of 36 | D109 |
| | `rule-show` | 36 | 0.05055 (0.00229) | 324.1 | 36 of 36 | D109 |

- D107: the difference of `rule` and `none` is $0.00062. The standard error of the difference is
  $0.00104. So the difference is less than 1 SE.
- D109: `rule` minus `none` is -$0.00058 (SE 0.00453, 0.13 SE). `rule-show` minus `rule` is
  -$0.00159 (SE 0.00366, 0.44 SE). Neither is a difference that the run shows.
- D109: 3 M3 runs failed the first grader, and the answers were right. The grader changed after
  the run, and the pass rates are now 36 of 36. The decision is the same before and after.
- Output tokens are lower with the rule: 22 percent in D107, and 13 percent (`rule`) and 30 percent
  (`rule-show`) in D109.

### Large multi-file task (M3)

M3 asks for a call chain over 3 files of 221 to 240 lines each. This is where the index saves the
most. The record gives no SE for M3, and each cell has 3 trials.

| Variant | M3 mean cost | Change from `none` | Source |
| --- | --- | --- | --- |
| `none` | $0.1167 | None | D109 |
| `rule` | $0.1038 | -11 percent | D109 |
| `rule-show` | $0.0873 | -25 percent | D109 |

### Search after the fix (X7)

In D109, scenario X7 ran `search "<phrase>" --context 5`. It matched any word and returned about 12
KB, and `rule-show` cost $0.0625 in each trial. D110 changed `search` to match all words and to cap
its text output at 4000 bytes. The eval ran again with 3 trials for each variant (PR #284).

| Variant | Cost before (D109) | Cost after (PR #284, SE) | Pass rate after |
| --- | --- | --- | --- |
| `none` | about $0.04 | $0.0429 (0.0019) | 1.00 |
| `rule` | about $0.04 | $0.0465 (0.0004) | 1.00 |
| `rule-show` | $0.0625 | $0.0559 (0.0134) | 1.00 |

`rule-show` minus `none` is +$0.0130 (SE 0.0135). This is within 2 SE. The runs are small, so
they do not show that `rule-show` is better or worse.

### Speed and size

The times below come from different PRs. The code, the repo state, and the machine load differed
between the PRs. So do not compare the rows of one column across PRs. Each PR measured on a Mac,
with a release build.

| Repo | PR | Code state | Files | First build | No-change build | Query | Index size |
| --- | --- | --- | --- | --- | --- | --- | --- |
| vscode `1745a4a6` | #265 | Symbols only, no FTS table | 20,621 | 6.53 s (8 cores) | 0.21 s | `find` with update 0.19 s; with `--no-update` under 0.01 s | 70 MB |
| vscode `1745a4a6` | #266 | Symbols and links. Before the FTS table. Same session as the next two rows. | 20,621 | 7.2 s | 0.19 s | Not given | 70 MB |
| vscode `1745a4a6` | #266 | FTS5 with the text in the index (not kept) | 20,621 | 31.0 s | 0.19 s | Not given | 593 MB |
| vscode `1745a4a6` | #266 | Contentless FTS5 (kept) | 20,621 | 17.7 s | 0.19 s | `search "tool search" --no-update` 0.02 s | 230 MB |
| vscode `1745a4a6` | #280 | Before the PR (`origin/dev`), `bench.sh 10`, median | 20,621 | 23.04 s | 0.2315 s | `find` 0.005 s; `show` 0.006 s; `outline` 0.005 s; `refs` 0.005 s; `search` 0.037 s (all `--no-update`) | 231.7 MB |
| vscode `1745a4a6` | #280 | After the PR (same session, same queries) | 20,621 | 22.795 s | 0.2215 s | Same as the row above | 231.7 MB |
| opencv | #268 | C and C++ added | 6,298 | 5.79 s | 0.16 s | Not given | Not given |
| tokio | #276 | Rust added | 890 | 4.55 s | 0.01 s | Not given | Not given |

Why the vscode first-build time goes from 6.53 s to 23.04 s:

- The index grew. PR #266 added the links and the FTS5 table, and the work of the build grew with them.
- The machine load differed. The 7.2 s and 17.7 s rows ran together in one session. The 6.53 s row and the #280 rows ran in other
  sessions.
- The no-change build stays near 0.2 s in each PR. This is the time that the session-start hook takes
  when the repo has not changed.

Two attempts to make the index smaller or faster did not meet their limits, so PR #280 did not keep
them (D108). `detail=column` made the vscode index 8.5 percent smaller (231.7 MB to 212.0 MB). The
limit was 25 percent. A page cache of 64 MB did not make the cold build faster: 21.4 s and 21.2 s.

## Limits

| Limit | What it means |
| --- | --- |
| The saving is inside the noise | Over all scenarios, the cost difference is less than 1 SE (D107: under 1 SE; D109: 0.13 SE for `rule` and 0.44 SE for `rule-show`). The data does not show a cost saving on small tasks. |
| The clear saving is on large tasks | M3 cost 11 to 25 percent less. It has 3 trials for each variant and no SE in the record. |
| The fixtures are synthetic | Generated code has regular names. It can favor the index more than a real repo does. |
| One model | Every trial used one model. Another model can give other results. |
| A large repo can need a manual first build | The hook stops the build after 120 seconds. The build writes one transaction, so a stopped first build writes nothing. Run `stone-index build` by hand once (D111). |
| A search for a word that is not in the code finds nothing | Use `--any` for at least one of the words (D110). |

D111 plans an eval on a real repo with the hook on and off. The review date is 2027-05-07.

## Sources

| Source | What it holds |
| --- | --- |
| D104 to D111 in the [decision log](../../framework/README.md#decisions) | Choices and eval results |
| PRs #265, #266, #268, #276, #280, #284 | Build time, size, and X7 data |
| [indexer/README.md](../../indexer/README.md) | Commands, install, benchmarks |
| [Customization](../../framework/customization.md#code-index-code_index) | The `code_index` key |
