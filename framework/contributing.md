# Change the framework

Rules for a PR that changes `framework/`. `AGENTS.md` points here.

- Open the PR into `branches.integration` (`dev` in this repo). A release is a PR from `dev` into
  `main`. See the release checklist in [versioning.md](versioning.md).
- Keep the core neutral. Put each harness, vendor, model, or spec-tool name in `framework/adapters/`.
  `stone check` fails on a vendor name in the core.
- When you change a profile, update the gates table in `framework/gates.md` in the same PR.
- Record each design decision in the "Decisions" table of `framework/README.md` (D1, D2, ...).
- Support each new rule with evidence. Add the source to the dossier and cite its ID.
- Give each new component (rule, skill, role, hook, check) an eval plan and a review date (P5).
- If a PR adds, renames, or removes a config key, or changes a generated file, add it to the newest
  entry of `framework/upgrades.yaml`. See [versioning.md](versioning.md).

## Checks for this repo only

`stone check-rules` tests rules that `AGENTS.md` states for this repo. R1 tests the action pins.
R2 tests the plugin version bump. R4 tests the commit message format.
`stone render` does not write them for a target repo (D78, D97). To add a rule check, add it to
`stone/src/stone/repo_rules.py`, and replay it on the merged PRs (D45).
