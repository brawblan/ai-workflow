//! `stone-index`: the code indexer of Cornerstone. It has `build`, `find`, `outline`, and
//! `--version`.

mod cli;
mod db;
mod lang;
mod query;
mod symbols;
mod update;
mod walk;

use std::env;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::process::ExitCode;

use cli::{Command, IndexOptions, Query, USAGE};
use rusqlite::Connection;
use update::Summary;

const NAME: &str = env!("CARGO_PKG_NAME");
const VERSION: &str = env!("CARGO_PKG_VERSION");

/// The path of the index from the repo root, if `--db` does not set one.
const DEFAULT_DB: &str = ".cornerstone/index.db";

/// The exit code of a query with no results.
const EXIT_NO_RESULTS: u8 = 1;

/// The exit code for a usage error or a broken index.
const EXIT_ERROR: u8 = 2;

/// The current folder, the repo root, and the index path of one command.
struct Place {
    cwd: PathBuf,
    root: PathBuf,
    db_path: PathBuf,
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    let result = match cli::parse(&args) {
        Ok(Command::Version) => Ok(format!("{NAME} {VERSION}\n")),
        Ok(Command::Build(options)) => build(&options).map(|summary| format!("{summary}\n")),
        Ok(Command::Find(query)) => return run_query(&query, true),
        Ok(Command::Outline(query)) => return run_query(&query, false),
        Err(message) => return fail(&format!("{message}\n{USAGE}")),
    };
    match result {
        Ok(text) => {
            print!("{text}");
            ExitCode::SUCCESS
        }
        Err(message) => fail(&message),
    }
}

fn place(options: &IndexOptions) -> Result<Place, String> {
    let cwd =
        env::current_dir().map_err(|error| format!("cannot read the current folder: {error}"))?;
    let root = walk::repo_root(&cwd);
    let db_path = options
        .db
        .as_ref()
        .map_or_else(|| root.join(DEFAULT_DB), |path| cwd.join(path));
    Ok(Place { cwd, root, db_path })
}

fn build(options: &IndexOptions) -> Result<Summary, String> {
    open_updated(&place(options)?, options).map(|(_, summary)| summary)
}

/// Opens the index, and brings it up to date with the files.
fn open_updated(place: &Place, options: &IndexOptions) -> Result<(Connection, Summary), String> {
    let db_path = &place.db_path;
    if let Some(parent) = db_path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("cannot make {}: {error}", parent.display()))?;
    }
    let with_path = |message: String| format!("{}: {message}", db_path.display());
    let mut conn = db::open(db_path).map_err(|error| with_path(db::describe(&error)))?;
    let summary =
        update::run(&mut conn, &place.root, db_path, options.max_file_size).map_err(with_path)?;
    Ok((conn, summary))
}

/// Opens the index with no update. The index must exist and have the schema of this binary.
fn open_existing(place: &Place) -> Result<Connection, String> {
    let db_path = &place.db_path;
    let with_path = |message: String| format!("{}: {message}", db_path.display());
    if !db_path.is_file() {
        return Err(with_path(
            "no index. Run `stone-index build` first.".to_string(),
        ));
    }
    let conn = db::open(db_path).map_err(|error| with_path(db::describe(&error)))?;
    db::check_current(&conn).map_err(with_path)?;
    Ok(conn)
}

/// Runs `find` (if `is_find`) or `outline`. Exit 0 with results, 1 with none, and 2 on an error.
fn run_query(query: &Query, is_find: bool) -> ExitCode {
    let result = place(&query.index).and_then(|place| {
        let conn = if query.update {
            open_updated(&place, &query.index)?.0
        } else {
            open_existing(&place)?
        };
        let describe = |error| format!("{}: {}", place.db_path.display(), db::describe(&error));
        if is_find {
            let results = query::find(&conn, &query.target, query.kind.as_deref(), query.limit);
            return results.map(|results| (results, None)).map_err(describe);
        }
        // A path with no row gets a hint, so an agent can tell a wrong path from a file with
        // no symbols.
        let path = repo_path(&place, &query.target)?;
        let results = query::outline(&conn, &path, query.limit).map_err(describe)?;
        let indexed =
            !results.rows.is_empty() || query::is_indexed(&conn, &path).map_err(describe)?;
        let hint = (!indexed).then(|| format!("{path} is not in the index"));
        Ok((results, hint))
    });
    match result {
        Ok((results, hint)) => {
            print!("{}", query::render(&results, query.format));
            if let Some(hint) = hint {
                eprintln!("{NAME}: {hint}");
            }
            if results.rows.is_empty() && results.omitted == 0 {
                ExitCode::from(EXIT_NO_RESULTS)
            } else {
                ExitCode::SUCCESS
            }
        }
        Err(message) => fail(&message),
    }
}

/// The path of a file from the repo root, with `/` between the parts. A relative `path` starts
/// at the current folder. The repo root is a real path, so the function resolves the symbolic
/// links in a path that exists. It resolves `.` and `..` as text in a path that does not exist.
fn repo_path(place: &Place, path: &str) -> Result<String, String> {
    let joined = place.cwd.join(path);
    let full = fs::canonicalize(&joined).unwrap_or_else(|_| lexical(&joined));
    let relative = full
        .strip_prefix(&place.root)
        .map_err(|_| format!("{path} is not in the repo {}", place.root.display()))?;
    let parts: Vec<_> = relative
        .components()
        .map(|part| part.as_os_str().to_string_lossy())
        .collect();
    Ok(parts.join("/"))
}

fn lexical(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::ParentDir => {
                out.pop();
            }
            Component::CurDir => {}
            other => out.push(other),
        }
    }
    out
}

fn fail(message: &str) -> ExitCode {
    eprintln!("{NAME}: {message}");
    ExitCode::from(EXIT_ERROR)
}
