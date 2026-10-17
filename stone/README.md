# stone

The Cornerstone CLI. Version 0.1 has one command:

| Command | Does |
| --- | --- |
| `stone check` | Validates the framework: profile frontmatter, gate rules, check IDs, the gates table, relative links, and P12 (no vendor names in the core). If `.cornerstone/config.yaml` exists, it validates it too. |

The other commands in [the generator design](../framework/generator/design.md) are not built yet.

## Prerequisites

- Python 3.11 or later

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

2. To show the findings as annotations in a GitHub Actions run, add `--format github`.

## Outputs

Each finding is one line: path, line, severity, check, and a message with the fix.

```text
framework/profiles/demo.md:1: error: stone check: The check 'K99' is not in checks.md. Add it there first.
```

| Exit code | Meaning |
| --- | --- |
| 0 | No finding. |
| 1 | One or more blocking findings. |
| 2 | Wrong arguments. |

## Errors

| Finding | Fix |
| --- | --- |
| `No framework folder` | Run `stone` from the repo root, or pass `--framework <path>`. |
| A link in a template points to no file | Not a finding. `stone check` skips `templates/` folders, because their links resolve in the target repo. |

## Test

```bash
python -m unittest discover -s stone/tests
```
