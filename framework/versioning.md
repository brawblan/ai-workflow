# Versioning and releases

Cornerstone uses version numbers in the form `X.Y.Z`. A release is a git tag `vX.Y.Z` of
`brawblan/ai-workflow`. A repo sets `framework_version` in its [repo config](customization.md) to
the tag that it uses. It sets `framework_commit` to the commit of that tag. The G3 workflow
installs `stone` from that commit, or from the tag if the key is not set (D92).

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

`dev` collects merged work. `main` holds only released code. Do the steps in this order.

1. On a branch from `dev`, run `python -m unittest discover -s stone/tests`, `stone check`, and
   `stone check-writing --diff origin/dev`.
2. In `upgrades.yaml`, set `released` of the newest entry to the date of the release.
3. Set the same version in `stone/pyproject.toml` and in `stone/src/stone/__init__.py`. Also set it in
   the line `Version X.Y.Z.` of `README.md` and of `website/content/index.md`. A unit test compares them.
4. If a skill changed, raise the version in the `plugin.json` file of the plugin.
5. Merge the changes of steps 2 to 4 into `dev` with a PR. Then open a release PR from `dev` into `main`. Wait for the checks
   `stone`, `checks`, and `build`.
6. The owner merges the release PR with a merge commit. Do not squash it: `dev` and `main` must keep
   the same history.
7. Check that the tag rules are active (see "Protect the release tags" below). Then tag the merge
   commit `vX.Y.Z`, and push the tag. The tag starts the `pages` workflow, which
   deploys the docs site. A push to `dev` or `main` does not deploy it. Copy the summary, the config
   changes, and the steps of the entry into the notes of the release.
8. Now move this repo to the new version. Run `stone upgrade --apply`. It sets `framework_version`
   and `framework_commit` in `.cornerstone/config.yaml`, and renders. Commit the config change
   alone, with `Role: human`. Then commit the generated files alone. Open this PR into `dev`. Do
   this after the tag exists, because `stone upgrade` reads the commit of the tag.

### Protect the release tags

`stone upgrade` reads the commit of a release tag (D92). A plugin install can pin a release tag too
(D94). Thus a moved tag changes the code that each repo and each machine runs (P9). The git host must
enforce these rules for each `v*` tag:

| Action | Who can do it |
| --- | --- |
| Create a tag | The owner only |
| Update or move a tag | No person, also not the owner |
| Delete a tag | No person, also not the owner |

Set up the rules once, and read them back before each release. The host commands are in the
adapter doc ([D94](README.md#decisions)). If a release is bad, do not move or delete its tag.
Release a new patch version.

## A docs change between releases

The site shows what is on `main`. A docs change in `dev` reaches the site at the next release. To
publish it before then, deploy the site by hand ([D75](README.md#decisions)):

1. Make sure that `dev` has no unreleased code. Run `git log --oneline origin/main..origin/dev`.
   If a commit changes code, wait for the next release.
2. Open a PR from `dev` into `main`. Do not set a version or push a tag.
3. The owner merges the PR with a merge commit.
4. Run `gh workflow run pages.yml --ref main`. The deploy job runs only from `main`.
