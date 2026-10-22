# Versioning and releases

Cornerstone uses version numbers in the form `X.Y.Z`. A release is a git tag `vX.Y.Z` of
`brawblan/ai-workflow`. A repo sets `framework_version` in its [repo config](customization.md) to
the tag that it uses. The G3 workflow installs `stone` from that tag.

## What a version number means

| Kind | When | What a repo must do |
| --- | --- | --- |
| Patch | A fix. No new config key. A generated file changes only to fix a defect. | Set the new version, and render again. |
| Minor | A new optional config key, a new command, or a new generated file. Every default keeps the old behavior. | The same as patch. Read the notes, and use the new keys if you want them. |
| Major | A config key is renamed or removed, a default changes, or a gate or a check changes its meaning. | Follow each manual step in the notes, in order. Run the evals that touch the changed parts. |

A change can make a check stricter for a repo that did not change its config. Then it is a major
change. Or it has a setting that keeps the old behavior until the repo opts in.

## The record of releases: `upgrades.yaml`

`framework/upgrades.yaml` has one entry for each release, newest first. `stone upgrade` reads it.
`stone check` tests it.

```yaml
versions:
  - version: 1.1.0
    kind: minor              # major, minor, or patch
    released: 2026-11-01     # a date, or null for the next release
    summary: One sentence.
    config:
      added:   [{key: delivery, default: ci, note: "..."}]
      renamed: [{from: old.key, to: new.key}]
      removed: [{key: old.key, note: "..."}]
    files:                   # generated files that change in a repo
      - {path: .cornerstone/checks/protected_paths.py, change: changed, note: "..."}
    steps:                   # manual steps, in order
      - "Text."
```

`stone check` fails when:

- A version is not in the form `X.Y.Z`, or the order is not newest first.
- The `kind` does not match the step from the next older version. A new major number is `major`. A
  new minor number is `minor`. Else it is `patch`.
- A patch release changes the config, or a minor release renames or removes a key.
- A release other than the newest has no date.

`stone check` also warns when `framework_version` in the repo config is not the version of the
installed `stone`.

## Rules for a change

1. A PR can add, rename, or remove a config key, or change a generated file. It must add the
   change to the newest entry of `upgrades.yaml`. If the newest entry has a date, add a new entry.
2. Pick the kind from the table above. When in doubt, pick the larger kind.
3. Record the decision in the Decisions table of the [framework README](README.md).

## Release checklist

1. Run `python -m unittest discover -s stone/tests`, `stone check`, and
   `stone check-writing --diff origin/main`.
2. In `upgrades.yaml`, set `released` of the newest entry to the date of the release.
3. Set the same version in `stone/pyproject.toml` and in `stone/src/stone/__init__.py`.
4. Set `framework_version` in this repo's `.cornerstone/config.yaml` to the version, and run
   `stone upgrade --apply`. Commit the generated files alone.
5. If a skill changed, raise the version in the `plugin.json` file of the plugin.
6. Merge. Tag the merge commit `vX.Y.Z`. Copy the summary, the config changes, and the steps of the
   entry into the notes of the release.
