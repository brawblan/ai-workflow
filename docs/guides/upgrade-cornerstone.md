# Upgrade Cornerstone

Move a repo that already uses Cornerstone to a new version. Profile: (setup). Default mode:
agent-centric. A person approves the PR (G4).

For what a patch, minor, or major version means, see [Versioning](../../framework/versioning.md).

## Before you start

1. Update your clone of `brawblan/ai-workflow` to the tag that you want, and install `stone` from
   it: `pip install <clone>/stone`.
2. Make a branch: `git switch -c chore/cornerstone-upgrade`.
3. Run `stone check --framework <clone>/framework`. Fix each error first. Ignore a warning that says
   `framework_version` is older than the installed `stone`.

## Today

1. See the plan:

   ```bash
   stone upgrade --framework <clone>/framework
   ```

   It lists these items for each release between your version and the target:
   - The new config keys, with their defaults, and whether your config has them.
   - The renamed and removed keys.
   - The generated files that change, and the manual steps.

   It runs `stone render --dry-run` and reports the drift. Use `--to <version>` for a version other
   than the newest released one.
2. Do each action that the plan lists under "need a person". For example, rename or remove a config
   key, or fix the drift. The new optional keys need no action.
3. Apply the move:

   ```bash
   stone upgrade --framework <clone>/framework --apply
   ```

   It sets `framework_version` and runs `stone render`. It stops if an action is still open.
4. Do the manual steps of the plan.
5. Run `stone check --framework <clone>/framework` and your `commands.all_checks`.
6. Commit the generated files alone, with the trailers `Role: generator` and `Actor: agent`. Commit
   your config change in its own commit. Open the PR.

## Steps for each kind

| Kind | Also do |
| --- | --- |
| Patch | Nothing more. Read the summary. |
| Minor | Read the new keys. Use the ones that you want. Check the "files" list: a changed check or hook shows in the render diff. |
| Major | Do each step in order. Run the evals of the changed parts (`stone eval <component>`). Ask for a review of the render diff. |

## Use the skill

`/workflow:cornerstone-setup` has an upgrade step. It runs `stone upgrade`, asks only for the facts
that a new key needs, writes the config diff, and runs the render. Use it when the plan has actions.

## If something goes wrong

| Problem | What to do |
| --- | --- |
| `drift <path>` | A person changed a generated file. Restore it, or move the change to the config, delete the file, and render again. |
| `The version X is not in upgrades.yaml` | The framework folder is older than the target. Update your clone, or use `--to` with a listed version. |
| `framework_version ... is newer` | Your clone or your `stone` is older than the config. Update it. A downgrade is not supported. |
| A hand-written component (`source: repo`) | `stone render` keeps it. Check by hand that it still works with the new version. |

## Not built yet

- `stone upgrade --apply` does not add the new optional keys to the config. Add them by hand.
- There is no automatic rollback. Revert the PR.
