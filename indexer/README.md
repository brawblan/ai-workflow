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

On macOS, use `shasum -a 256 --check --ignore-missing SHA256SUMS`. The Cargo option needs Rust 1.99
or later as the default toolchain. The Clone option uses the version in `rust-toolchain.toml`.

`stone index <args>` runs `stone-index <args>` from your `PATH`. If `stone-index` is not on your
`PATH`, it prints the install commands and exits with code 2.

## Commands

| Command | What it does |
| --- | --- |
| `stone-index build` | Makes or updates the index of the repo. |
| `stone-index find <name>` | Prints the symbols with this name. |
| `stone-index outline <path>` | Prints the symbols of one file. |
| `stone-index refs <path or module>` | Prints the links into a file or a module, and the links out of it. |
| `stone-index search "<words>"` | Prints the lines of the blocks of text that best match the words. |
| `stone-index --version`, `stone-index -V` | Prints the name and the version. |

### build

`build` finds the repo root, walks the files, and writes the index. The repo root is the nearest
folder, from the current folder up, that has `.git`. If no folder has `.git`, the root is the
current folder.

| Option | Default | What it does |
| --- | --- | --- |
| `--db <path>` | `.cornerstone/index.db` in the repo root | Sets the path of the index. A relative path starts at the current folder. |
| `--max-file-size <bytes>` | `1048576` (1 MB) | Skips each file that is larger. |
| `--lang <ext>=<lang>` | None | Sets the language of a file extension. Repeat it for more extensions. `<lang>` is `python`, `markdown`, `typescript`, `tsx`, `javascript`, `jsx`, `c`, `cpp`, `csharp`, or `rust`. For example, `--lang h=c` reads `.h` files as C. Give the same option to each command, because a command that gets another language reads the file again. |

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

### refs

`refs <target>` takes a repo path or a module name. If the index has a file at the path, `refs`
prints two groups. `in` has the links whose target resolves to the file. `out` has the links of the
file.

Else, if the target is a Python module of the repo, `refs` uses its file. Else, `in` has the
links whose target text is the target, for example `react`. Each line is `path:line kind target`:

```text
in
stone/src/stone/cli.py:10 import stone.evals
out
stone/src/stone/evals.py:11 import json
```

The `--limit` applies to each group. A JSON result has `path`, `line`, `kind`, `target`, and
`resolved`. The section [Links](#links) tells which links the build reads.

### search

`search "<words>"` finds the blocks of text that have at least one of the words, with FTS5. The
best bm25 rank comes first. For each block, it prints the first line with one of the words, as
`path:line: text`. The line has no space at its ends. The index holds no text, so `search` reads
each file of a hit. It skips a hit in a file that changed after the update, for example with
`--no-update`:

```text
stone/src/stone/repo_rules.py:154: def check_version_bump(root: Path, base: str, skills: str = SKILLS,
```

A word is a run of letters and digits, with no case. A letter with a diacritic is not the same
letter: `resume` does not find `résumé`. `--path <glob>` searches only the paths that
match the glob, with the SQLite `GLOB` rules: `*` also matches `/`. A JSON result has `path`,
`line`, and `text`.

### Query options

`find`, `outline`, `refs`, and `search` have these options. They also have `--db` and `--max-file-size` of `build`.
`--max-file-size` has no effect with `--no-update`. `--lang` also works for these commands. Put `--` before a name or a path that starts
with `-`.

| Option | Default | What it does |
| --- | --- | --- |
| `--limit <n>` | `20` | Prints a maximum of `n` results. If the limit cuts the results, the last text line gives the number of symbols that it did not print. |
| `--format text\|json` | `text` | `json` prints one object: `results` (a list of symbols) and `omitted` (the number that the limit cut). |
| `--no-update` | Off | Reads the index as it is. With no option, the command first updates the index, as `build` does, and prints no summary. |

Each JSON result has `path`, `line`, `end_line`, `kind`, `name`, `qualified_name`, and `level`.
`level` is `null` for a code symbol. An `outline` result also has `depth`, the indent level from 0.
The text output shows each control character in a name as `?`.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The command worked. For a query: there are results. |
| 1 | A query found no results. |
| 2 | A usage error, a broken index, no index with `--no-update`, or a lock that another process held for more than 10 minutes. |

If the error says "broken index", make sure that no other build runs. Then delete the index file and
run `build`.

## The index

| Table | Columns |
| --- | --- |
| `meta` | `key`, `value`. The key `schema_version` holds the schema version. |
| `files` | `path`, `size`, `mtime_ns`, `hash`, `language`, `lines` |
| `symbols` | `id`, `name`, `qualified_name`, `kind`, `path`, `line`, `end_line`, `parent`, `level` |
| `links` | `id`, `path`, `line`, `kind`, `target`, `resolved`. `resolved` is empty if the target is not a file of the repo. |
| `chunk_rows` | `id`, `path`, `line`: one row for each block of at most 50 lines of a file. `line` is the first line of the block. |
| `chunks` | A contentless FTS5 table with the words of each block, with the `id` of its `chunk_rows` row. A trigger deletes it with its row. |

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
| C | `.c` | `function`, `struct`, `union`, `enum`, `typedef`, `macro` |
| C++ | `.cc`, `.cpp`, `.cxx`, `.hpp`, `.hh`, `.hxx`, `.h` | The C kinds, and `class`, `namespace`, `method` |
| C# | `.cs` | `namespace`, `class`, `struct`, `record`, `interface`, `enum`, `method`, `property` |
| Rust | `.rs` | `function`, `method`, `struct`, `enum`, `union`, `trait`, `mod`, `constant`, `static`, `type`, `macro` |
| Markdown | `.md`, `.markdown` | `heading` |

- A function in a class is a `method`. A class field with a function value is also a `method`.
  A function in a function is a `function`. A method in an object literal is not a symbol.
- `constant` is an exported `const`, also with `declare`. An exported `const` with a function
  value is a `function`. A `declare function` is a `function`.
- A decorated Python definition starts on the line of its first decorator.
- C and C++: a `macro` is a `#define` with a body. A `#define` with no body, for example a header
  guard, is not a symbol. A `struct`, `union`, `enum`, or `class` needs a body. A type that a
  declaration only names is not a symbol. The struct in `typedef struct {...} P;` has no name, so
  only `P` is a symbol. A `typedef struct N {...} N;` gives a `struct` and a `typedef`.
- C++: a function in a class, and a function with a scope in its name, is a `method`. A
  declaration of a method in a class is also a `method`. `void Parser::parse() {}` gets the
  qualified name `Parser.parse`, and `namespace a::b` gets the name `a.b`. A template is a symbol
  of the kind of its declaration, for example a `class` for a class template.
- C++: the build cannot tell a function in a namespace, `void ns::helper() {}`, from a method, so
  both are a `method`. A member template that a class only declares is not a symbol. A function
  pointer field is not a symbol. The name of a method has no template arguments: `Box<T>::put`
  gives `Box.put`.
- C++: `class EXPORT Name {...}` and `struct EXPORT Name {...}`, with an export macro, are read as
  `Name`. The grammar cannot read `class EXPORT Name : Base {...}`, so the index has no symbol for it. It also cannot read an empty `class EXPORT Name {};`.
- C#: a file-scoped `namespace A;` holds the declarations after it, so `class K` is `A.K`. A file-scoped namespace and `namespace A.B {}` are a `namespace`. A `record struct` is a
  `record`. A constructor, a field, and an event are not symbols.
- Rust: an item in `impl Type` or `impl Trait for Type` gets the qualified name `Type.item`, and a
  function there is a `method`. An item in `trait Trait` gets `Trait.item`. A generic type and a
  type with a path use only the name: `impl<T> a::Box<T>` gives `Box`. A `mod` is a symbol only if
  it has a body. A `macro` is a `macro_rules!` definition. The `impl` block has no symbol.
- The index keeps symbols to a nesting depth of 32. It skips deeper symbols.
- The qualified name of a code symbol joins the names of its parents with `.`, for example
  `Parser.parse`.
- The qualified name of a heading is its text, because heading text can have a `.` in it.
- The `level` of a heading is 1 to 6. The parent of a heading is the nearest heading before it with
  a lower level. A heading ends on the line before the next heading of the same or a higher level.
- The name of a heading has no closing `#` sequence. A heading on more than one line gets one
  line, with a space between the lines.

## Links

The build reads the links of each new or changed file. If a file is new or gone, it resolves each
link of the index again.

| Language | Kind | Links |
| --- | --- | --- |
| Python | `import` | `import a.b` gives `a.b`. `from m import a` gives `m.a`. `from m import *` gives `m`. |
| TypeScript, JavaScript | `import`, `export`, `require` | `import` and `export ... from` with a source. `require()` and `import()` with a string. |
| C, C++ | `include` | `#include "a.h"` gives `a.h`. `#include <a.h>` gives `<a.h>`. |
| C# | `using` | `using A.B;` gives `A.B`. `using static` and `using X = A.B;` also give `A.B`. |
| Rust | `mod`, `use` | `mod a;` gives `a`. `use a::{b, c::*};` gives `a::b` and `a::c`. An `as` name is not in the target. |
| Markdown | `link` | Relative links, also in table cells, and link reference definitions, with no `#anchor` and no `?query`. A link in a code span is not a link. |

The build resolves a target to a file of the repo where it can:

- A Python module: first a file next to the importer. Then a file whose path ends with the module
  path, as `.py`, `.pyi`, or `__init__.py`. A name with one part matches only from the repo root or
  from a top package, so `import logging` does not match `tools/logging.py`. If two files match,
  the file nearest to the importer wins. If `m.a` is not a
  module, the build uses `m`. A relative import starts at the folder of the file.
- A TypeScript or JavaScript target that starts with `./` or `../`: the path, then the path with
  each extension, then its `index` file. A `.js` target can also be a `.ts` file.
- A C or C++ `#include "..."` tries three paths in this order. First, the path from the folder of
  the file. Then, the path from the repo root. Last, the nearest file whose path ends with the
  target. An `#include <...>` stays text. A `using` stays text.
- A Rust `mod a;` is `a.rs` or `a/mod.rs` in the folder of the module of the file. That folder is
  the folder of the file for `main.rs`, `lib.rs`, and `mod.rs`. Else it is the folder with the
  name of the file. A `use crate::a::b::Item;` starts at the nearest `main.rs` or `lib.rs` at or
  above the file. It goes down each part that is a module file, and gives the last one. A `use` of
  an outside crate, and a `use` with `self` or `super`, stay text.
- A Markdown link: the relative path.

Other targets, for example an external package, keep only their target text.
