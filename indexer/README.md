# stone-index

`stone-index` is the code indexer of Cornerstone (D104). It keeps a local SQLite index of the files
in a repo. An agent can then ask the index where a symbol is, and read fewer files.

This version has the `build` command only. The symbol parsers and the query commands come in the
next versions (issue #255).

## Install

Install Rust with `rustup`. Then run this command in `indexer/`:

```sh
cargo install --locked --path .
```

## Commands

| Command | What it does |
| --- | --- |
| `stone-index build` | Makes or updates the index of the repo. |
| `stone-index --version`, `stone-index -V` | Prints the name and the version. |

### build

`build` finds the repo root, walks the files, and writes the index. The repo root is the nearest
folder, from the current folder up, that has `.git`. If no folder has `.git`, the root is the
current folder.

| Option | Default | What it does |
| --- | --- | --- |
| `--db <path>` | `.cornerstone/index.db` in the repo root | Sets the path of the index. A relative path starts at the current folder. |
| `--max-file-size <bytes>` | `1048576` (1 MB) | Skips each file that is larger. |

The walk follows `.gitignore`, `.git/info/exclude`, and the global git ignore file, also with no git.
It also follows `.ignore` files. It skips the `.git` folder, symbolic links, and a file with a NUL
byte in its first 8 KB.

The build is incremental:

- It reads a file again only if the size or the modified time changed.
- It writes the row of a file again only if the content hash changed.
- It removes the rows of each file that is gone, ignored, binary, or too large.
- If the schema version of the index is not the version of the binary, it makes a new index.

The build prints one summary line, for example `3 parsed, 120 unchanged, 1 removed in 0.05s`.

The index uses SQLite WAL mode. If two builds run at the same time, the second build waits for the
first, for a maximum of 10 minutes.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The command worked. |
| 2 | A usage error, or a broken index. To fix a broken index, delete the file and run `build`. |

## The index

| Table | Columns |
| --- | --- |
| `meta` | `key`, `value`. The key `schema_version` holds the schema version. |
| `files` | `path`, `size`, `mtime_ns`, `hash`, `language`, `lines` |
| `symbols` | `id`, `name`, `qualified_name`, `kind`, `path`, `line`, `end_line`, `parent` |

The index holds each text file. The `language` column is empty for a language that the indexer
does not parse. The `symbols` table is empty in this version.
