# stone

The Cornerstone CLI. Version 0.7 has six commands:

| Command | Does |
| --- | --- |
| `stone check` | Validates the framework: profile frontmatter, gate rules, check IDs, the gates table, relative links, and P12 (no vendor names in the core). If `.cornerstone/config.yaml` exists, it validates it too. Check K18: if `constitution/personas.md` exists, it validates its format. It also tests each persona ID and job story ID in the plans. K18 findings are warnings for the first 2 weeks. Check K19: if the repo has spec deltas or specs, it tests the deltas, the `apply_order` values, and the specs against a replay. K19 findings are warnings for the first 2 weeks. |
| `stone check-writing` | Check K17. Tests human-facing Markdown against the measurable rules of the [writing standard](../framework/writing.md). |
| `stone check-evidence` | Check K14. Fails if a required section of a PR body is missing or empty: Evidence, Decision log, Review findings, or Confidence. |
| `stone spec apply <plan>` | Applies the spec delta of one plan (`<plans>/<plan>.spec.md`). It gives the delta the next `apply_order`, and writes the specs in `<specs>/`. It stops if a spec is not the same as a replay of the applied deltas. See [Specs](../framework/workflow-model.md#specs). |
| `stone spec sync` | After a merge of the base branch: gives the applied deltas the orders 1 to n, and writes the specs from a replay. It overwrites a spec that is not the same as the replay. |
| `stone render` | Writes the generated files and `.cornerstone/manifest.yaml` into a target repo. Version 0.4 supports the single-ticket and app-slice profiles: role files, the protected-path hook, check K6, and the G3 CI workflow. Version 0.7 adds a K14 step on the PR body to that workflow. Version 0.8 renders the roles of all 10 profiles, with the new investigator role. It writes the G3 workflow and K6 only for a profile that has them (D24, D25). |

The other commands in [the generator design](../framework/generator/design.md) are not built yet.

## Prerequisites

- Python 3.11 or later
- git (for `--diff`)

## Install

Run this from the repo root:

```bash
pip install ./stone
```

## Use

1. Validate the framework:

   ```bash
   stone check
   ```

2. Test files or folders in full:

   ```bash
   stone check-writing framework docs README.md
   ```

3. Test only the lines that changed since a base branch:

   ```bash
   stone check-writing --diff origin/main
   ```

   The diff starts at the merge base of the base branch and `HEAD`. It ends at the working tree.
   Thus K17 tests your commits, staged changes, unstaged changes, and new Markdown files. You can
   run it before `git commit`.

4. Make K17 fail on errors. Use this mode after the 2-week warning period:

   ```bash
   stone check-writing --diff origin/main --mode block
   ```

Add `--format github` to show the findings as annotations in a GitHub Actions run.

5. Test a PR body for the evidence sections (K14). Use `-` to read the body from standard input:

   ```bash
   gh pr view <number> --json body --jq .body | stone check-evidence -
   ```

   K14 warns by default. Add `--mode block` to fail on findings after the 2-week warning period.
   Add `--section <name>` for each section that your repo requires. It replaces the default list.

6. Render the generated files into a target repo. Write `.cornerstone/config.yaml` first (see
   [customization.md](../framework/customization.md)):

   ```bash
   stone render --root <target-repo> --framework <this-repo>/framework --dry-run
   ```

   Remove `--dry-run` to write the files. A second run changes only the files whose input changed.
   The G3 workflow installs stone from the tag `v<framework_version>` for its K14 step. Use
   0.5.0 or later. Render warns about an earlier version.

7. Commit the render output alone, with the trailers `Role: generator` and `Actor: human`. K6 counts
   a commit with no `Role:` trailer as an implementer commit, and the output is in protected paths.

## Outputs

Each finding is one line: path, line, severity, check, and a message with the fix.

```text
framework/principles.md:68: error: K17: Rule 8: The sentence has 26 words. The limit for a description is 25. Split the sentence.
```

| Exit code | Meaning |
| --- | --- |
| 0 | No blocking finding. In `--mode warn`, K17 and K14 always exit with 0. `render`: no drift. |
| 1 | One or more blocking findings. `render`: an input is not valid, and no file was written. |
| 2 | Wrong arguments, or `check-evidence` cannot read the PR body. `render`: drift in one or more files. Render did not change those files. |

`stone render` logs one line for each file to standard error: `wrote`, `skipped`, or `drift`.

## Errors

| Finding | Fix |
| --- | --- |
| A K17 finding on a correct use of a word | Add `<!-- ste-ignore -->` at the end of that line. A reviewer checks each mark. |
| `No framework folder` | Run `stone` from the repo root, or pass `--framework <path>`. |
| `render`: `'<field>' is a TODO value` | Write the real value in `.cornerstone/config.yaml`. |
| `render`: `drift <path>` | A person changed a generated file. Move the change to the repo config. Then delete the file and render again. |

## Limits

- K17 skips agent-facing files (skills, `AGENTS.md`, `CLAUDE.md`, `.claude/`, templates), code, inline code, URLs, and quoted text.
- In `--diff` mode, K17 reports a finding only if the sentence starts on a changed line.
- In `--diff` mode, K17 tests each line of an untracked Markdown file. It skips a file that git ignores.
- The tense test (rule 2) and the passive test (rule 11) are warnings, because they also match some adjectives.
- K14 finds a section by a heading (`## Evidence`) or a line with only bold text (`**Evidence**`). It does not judge if the content is true. The reviewer and the human do that.
- `render` supports only the `claude-code` harness. It skips a profile with a role that the adapter has no file for, with a log line.
- `render` does not write K7, K15, K16, or the trigger workflows yet. The [roadmap](../framework/README.md#roadmap) lists them for v1.
- `render` does not check `framework_version` against the framework folder. Check out the tag yourself.
- `render` does not read profile overrides (`.cornerstone/profiles/`) yet.
- If the hook entry in `.claude/settings.json` changes in a new framework version, `render` adds the new entry. Remove the old entry by hand.

## Test

```bash
python -m unittest discover -s stone/tests
```
