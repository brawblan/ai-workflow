# stone

The Cornerstone CLI. Version 0.1 has two commands:

| Command | Does |
| --- | --- |
| `stone check` | Validates the framework: profile frontmatter, gate rules, check IDs, the gates table, relative links, and P12 (no vendor names in the core). If `.cornerstone/config.yaml` exists, it validates it too. |
| `stone check-writing` | Check K17. Tests human-facing Markdown against the measurable rules of the [writing standard](../framework/writing.md). |

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

4. Make K17 fail on errors. Use this mode after the 2-week warning period:

   ```bash
   stone check-writing --diff origin/main --mode block
   ```

Add `--format github` to show the findings as annotations in a GitHub Actions run.

## Outputs

Each finding is one line: path, line, severity, check, and a message with the fix.

```text
framework/principles.md:68: error: K17: Rule 8: The sentence has 26 words. The limit for a description is 25. Split the sentence.
```

| Exit code | Meaning |
| --- | --- |
| 0 | No blocking finding. In `--mode warn`, K17 always exits with 0. |
| 1 | One or more blocking findings. |
| 2 | Wrong arguments. |

## Errors

| Finding | Fix |
| --- | --- |
| A K17 finding on a correct use of a word | Add `<!-- ste-ignore -->` at the end of that line. A reviewer checks each mark. |
| `No framework folder` | Run `stone` from the repo root, or pass `--framework <path>`. |

## Limits

- K17 skips agent-facing files (skills, `AGENTS.md`, `CLAUDE.md`, `.claude/`, templates), code, inline code, URLs, and quoted text.
- In `--diff` mode, K17 reports a finding only if the sentence starts on a changed line.
- The tense test (rule 2) and the passive test (rule 11) are warnings, because they also match some adjectives.

## Test

```bash
python -m unittest discover -s stone/tests
```
