# Principles

<!-- Guide: Keep the rules short: each one is a MUST that a reviewer can check. Remove each Guide
comment when you fill the file. -->

Version: 1.0.0

Each change MUST follow these rules. If a change cannot follow a rule, change the rule first, in its
own PR.

## Rules

<!-- Guide: 5 to 12 rules. Each rule: a short name, the MUST, and the scope. Examples follow. -->

1. **Security.** Secrets live only in <secret store>. Never put secrets in code or in committed files.
2. **Tests.** Each change adds unit tests for the code it touches. Exempt: <entrypoints, thin SDK wrappers>.
3. **Ownership.** Keep each change in the folder that owns it. See [tech-stack.md](tech-stack.md#ownership).
4. **Errors.** Validate input at each trust boundary. Do not fail silently.
5. **Gates.** Before merge, <lint, typecheck, tests> pass.
6. <name>. <rule>

## Working style

- Make the smallest change that solves the problem.
- Reuse existing helpers and patterns before you add new ones.
- Put follow-up work in an issue, not in a code comment.

## Amend

Amend by PR. Increase the version:

- MAJOR: remove or redefine a rule.
- MINOR: add a rule or expand guidance.
- PATCH: wording, links, typos.
