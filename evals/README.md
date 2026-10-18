# Evals

An eval tests one component (a role, a skill, a rule) with the component and without it. The
runs use the same prompt and tools. Code graders check the result. See
[Eval design](../framework/lifecycle.md#eval-design) and decision D26 in the
[framework decisions](../framework/README.md).

How to read a table:

| Column | Meaning |
| --- | --- |
| Variant | `with` has the component. `without` does not. |
| pass^k | 1 if all k trials passed every check. Else 0. |
| Outcome | Rate of passed `outcome` checks (the behavior). |
| Contract | Rate of passed `contract` checks (the format of the component). |
| Cost, Tokens out, Seconds | Mean for each trial. |
| Errors | Trials that ended in an error. |

Runs are local. Run `stone eval <component-id>`. The command writes a result file to
`evals/results/`. Commit the file. This page reads those files at build time.

<!-- evals-index -->
