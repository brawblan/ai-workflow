# Eval plan: setup

| Item | Value |
| --- | --- |
| Component | `skill.setup` |
| Purpose | Collect the repo facts, write `.cornerstone/config.yaml`, and run `stone render` and `stone check`. |
| Principle | P3 (judgment goes into the inputs), P5 |
| Why not a check | A check cannot find the facts or interview the human. `stone check` validates the result. |
| Added | 2026-10-18 |
| Review by | 2027-04-18 |
| Status | Planned. No eval has run. |

## Scenarios

| # | Repo fixture | Pass when |
| --- | --- | --- |
| 1 | Python repo with `AGENTS.md` that lists all commands | No question about a command. `render` and `check` pass. |
| 2 | Node repo with commands only in `package.json` scripts | The config uses the exact script commands. |
| 3 | Repo with no test command anywhere | The config has `TODO(<owner>)` for `commands.test_unit`. The skill reports that `render` stops on it. |
| 4 | Repo with a hand-edited `.claude/agents/tester.md` | The skill reports drift and asks the user. It does not delete the file. |
| 5 | Repo with its own `.claude/settings.json` | The other settings keys stay after `render`. |

## Grader

Code-based first: parse the config, run `stone check`, and compare the field values with the
fixture. Count the interview questions. The skill fails a scenario if it asks for a fact that the
fixture has. Run the eval with and without the skill (the baseline is the CLI and
`customization.md` only).
