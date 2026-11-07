# stone-index

`stone-index` is the code indexer of Cornerstone (D104). It keeps a local SQLite index of the files
in a repo. An agent can then ask the index where a symbol is, and read fewer files.

## Install

Each release has an archive and a wheel of `stone-index` for each of these five targets:

| Platform | Target |
| --- | --- |
| Linux x86-64 | `x86_64-unknown-linux-gnu` |
| Linux arm64 | `aarch64-unknown-linux-gnu` |
| macOS x86-64 | `x86_64-apple-darwin` |
| macOS arm64 | `aarch64-apple-darwin` |
| Windows x86-64 | `x86_64-pc-windows-msvc` |

The file `SHA256SUMS` of the release has the checksum of each file.
The Linux files need glibc 2.28 or later. Use one of these four options.

| Option | Command |
| --- | --- |
| Archive | Download `stone-index-vX.Y.Z-<target>.tar.gz` (`.zip` for Windows) and `SHA256SUMS` from the release. Test the checksum, extract the archive, and put `stone-index` on your `PATH`. |
| Wheel | `uv tool install <wheel URL>` or `pipx install <wheel URL>`. The wheel holds only the binary. `pip install <wheel URL>` also works. |
| Cargo | `cargo install --locked --git https://github.com/brawblan/ai-workflow --tag vX.Y.Z stone-index` |
| Clone | `cargo build --release --locked` in `indexer/`. The binary is `target/release/stone-index`. |

To test the checksum of a download, run this command in the download folder:

```sh
sha256sum --check --ignore-missing SHA256SUMS
```

On macOS, use `shasum -a 256 --check --ignore-missing SHA256SUMS`. The Cargo and Clone options
need Rust. The file `rust-toolchain.toml` sets the version.

`stone index <args>` runs `stone-index <args>` from your `PATH`. If `stone-index` is not on your
`PATH`, it prints the install commands and exits with code 2.

## Commands

| Command | What it does |
| --- | --- |
| `stone-index build` | Makes or updates the index of the repo. |
| `stone-index find <name>` | Prints the symbols with this name. |
| `stone-index outline <path>` | Prints the symbols of one file. |
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
- If a file changed in the 2 seconds before the build, or has a modified time in the future, the
  next build reads it again. Thus a second edit with the same size and modified time is not lost.
- It reads the first 8 KB of a file first. It reads the rest only if the file is not binary. A
  binary file has no row, so each build reads its first 8 KB again.
- It writes the row of a file again only if the content hash changed.
- It removes the rows of each file that is gone, ignored, binary, or too large.
- If the schema version of the index is not the version of the binary, it makes a new index.
- The file at the index path can be another SQLite database, with no `meta` or `files` table. The
  build then stops and changes nothing.

The build prints one summary line, for example `3 parsed, 120 unchanged, 1 removed in 0.05s`.

The index uses SQLite WAL mode. If two builds run at the same time, the second build waits for the
first, for a maximum of 10 minutes. This is also true for a new index.

### find

`find <name>` prints each symbol whose qualified name is `<name>`, or whose last part is `<name>`.
For a heading, the name is the heading text. The output is in path and line order, one line for
each symbol:

```text
stone/src/stone/evals.py:190 function find_component
```

`--kind <kind>` prints only the symbols of that kind, for example `--kind method`. The section
[Symbols](#symbols) lists the kinds.

### outline

`outline <path>` prints the symbols of one file in line order, one line for each symbol, as
`line kind name`. The path can be absolute, or relative to the current folder. If the index has no
row for the path, a line on stderr says so. The exit code is then 1. The output indents each code
symbol two spaces for each parent above it, and each heading two spaces for each level above 1:

```text
3 class Parser
  4 method parse
```

### Query options

`find` and `outline` have these options. They also have `--db` and `--max-file-size` of `build`.
`--max-file-size` has no effect with `--no-update`. Put `--` before a name or a path that starts
with `-`.

| Option | Default | What it does |
| --- | --- | --- |
| `--limit <n>` | `20` | Prints a maximum of `n` symbols. If the limit cuts the results, the last text line gives the number of symbols that it did not print. |
| `--format text\|json` | `text` | `json` prints one object: `results` (a list of symbols) and `omitted` (the number that the limit cut). |
| `--no-update` | Off | Reads the index as it is. With no option, the command first updates the index, as `build` does, and prints no summary. |

Each JSON result has `path`, `line`, `end_line`, `kind`, `name`, `qualified_name`, and `level`.
`level` is `null` for a code symbol. An `outline` result also has `depth`, the indent level from 0.
The text output shows each control character in a name as `?`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The command worked. For `find` and `outline`: there are results. |
| 1 | `find` or `outline` found no results. |
| 2 | A usage error, a broken index, no index with `--no-update`, or a lock that another process held for more than 10 minutes. |

If the error says "broken index", make sure that no other build runs. Then delete the index file and
run `build`.

## The index

| Table | Columns |
| --- | --- |
| `meta` | `key`, `value`. The key `schema_version` holds the schema version. |
| `files` | `path`, `size`, `mtime_ns`, `hash`, `language`, `lines` |
| `symbols` | `id`, `name`, `qualified_name`, `kind`, `path`, `line`, `end_line`, `parent`, `level` |

The index holds each text file. The `language` column is empty for a language that the indexer
does not parse.

## Symbols

The build parses each new or changed file with tree-sitter, on all cores. A syntax error does not stop the build.
The index keeps each symbol that tree-sitter finds in the file.

| Language | Extensions | Kinds |
| --- | --- | --- |
| Python | `.py`, `.pyi` | `function`, `class`, `method` |
| TypeScript | `.ts`, `.mts`, `.cts`, `.tsx` | `function`, `class`, `method`, `interface`, `type`, `enum`, `namespace`, `constant` |
| JavaScript | `.js`, `.mjs`, `.cjs`, `.jsx` | `function`, `class`, `method`, `constant` |
| Markdown | `.md`, `.markdown` | `heading` |

- A function in a class is a `method`. A class field with a function value is also a `method`.
  A function in a function is a `function`. A method in an object literal is not a symbol.
- `constant` is an exported `const`, also with `declare`. An exported `const` with a function
  value is a `function`. A `declare function` is a `function`.
- A decorated Python definition starts on the line of its first decorator.
- The index keeps symbols to a nesting depth of 32. It skips deeper symbols.
- The qualified name of a code symbol joins the names of its parents with `.`, for example
  `Parser.parse`.
- The qualified name of a heading is its text, because heading text can have a `.` in it.
- The `level` of a heading is 1 to 6. The parent of a heading is the nearest heading before it with
  a lower level. A heading ends on the line before the next heading of the same or a higher level.
- The name of a heading has no closing `#` sequence. A heading on more than one line gets one
  line, with a space between the lines.
