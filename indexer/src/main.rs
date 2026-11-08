//! `stone-index`: the code indexer of Cornerstone. It has `build`, `find`, `show`, `outline`,
//! `refs`, `search`, and `--version`.

mod cli;
mod db;
mod lang;
mod links;
mod query;
mod refs;
mod resolve;
mod rules;
mod search;
mod show;
mod sql;
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
        Ok(Command::Plans(options)) => plans(&options),
        Ok(Command::Find(query)) => return run_query(&query, find),
        Ok(Command::Show(query)) => return run_query(&query, show),
        Ok(Command::Outline(query)) => return run_query(&query, outline),
        Ok(Command::Refs(query)) => return run_query(&query, refs),
        Ok(Command::Search(query)) => return run_query(&query, search),
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

/// The query plan of each SQL statement of the query commands, one line for each plan step:
/// `name<TAB>detail`. It does not update the index.
fn plans(options: &IndexOptions) -> Result<String, String> {
    let place = place(options)?;
    let conn = open_existing(&place)?;
    let mut out = String::new();
    for (name, statement) in sql::PLANS {
        let mut plan = conn
            .prepare(&format!("EXPLAIN QUERY PLAN {statement}"))
            .map_err(describe(&place))?;
        let nulls = vec![rusqlite::types::Null; plan.parameter_count()];
        let details = plan
            .query_map(rusqlite::params_from_iter(nulls), |row| {
                row.get::<_, String>(3)
            })
            .and_then(Iterator::collect::<rusqlite::Result<Vec<_>>>)
            .map_err(describe(&place))?;
        for detail in details {
            out.push_str(&format!("{name}\t{detail}\n"));
        }
    }
    Ok(out)
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
    let summary = update::run(&mut conn, &place.root, db_path, options).map_err(with_path)?;
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

/// The output of a query, true if it has no results, and a hint for stderr.
type Answer = (String, bool, Option<String>);

/// The query step of one command. It returns an `Answer` or an error message.
type Ask = fn(&Place, &Connection, &Query) -> Result<Answer, String>;

fn describe(place: &Place) -> impl Fn(rusqlite::Error) -> String {
    let path = place.db_path.display().to_string();
    move |error| format!("{path}: {}", db::describe(&error))
}

fn find(place: &Place, conn: &Connection, query: &Query) -> Result<Answer, String> {
    let results = query::find(conn, &query.target, query.kind.as_deref(), query.limit)
        .map_err(describe(place))?;
    let empty = results.rows.is_empty() && results.omitted == 0;
    Ok((query::render(&results, query.format), empty, None))
}

fn show(place: &Place, conn: &Connection, query: &Query) -> Result<Answer, String> {
    let blocks = show::show(conn, &place.root, query).map_err(describe(place))?;
    let empty = blocks.blocks.is_empty() && blocks.omitted == 0;
    Ok((show::render(&blocks, query.format), empty, None))
}

fn outline(place: &Place, conn: &Connection, query: &Query) -> Result<Answer, String> {
    // A path with no row gets a hint, so an agent can tell a wrong path from a file with
    // no symbols.
    let path = repo_path(place, &query.target)?;
    let results = query::outline(conn, &path, query.limit).map_err(describe(place))?;
    let indexed =
        !results.rows.is_empty() || query::is_indexed(conn, &path).map_err(describe(place))?;
    let hint = (!indexed).then(|| format!("{path} is not in the index"));
    let empty = results.rows.is_empty() && results.omitted == 0;
    Ok((query::render(&results, query.format), empty, hint))
}

/// The target is a path if it names a file of the index. Else it is a module name.
fn refs(place: &Place, conn: &Connection, query: &Query) -> Result<Answer, String> {
    let path = repo_path(place, &query.target).ok();
    let found =
        refs::refs(conn, path.as_deref(), &query.target, query.limit).map_err(describe(place))?;
    let empty = found.incoming.is_empty() && found.outgoing.is_empty() && found.omitted == 0;
    Ok((refs::render(&found, query.format), empty, None))
}

fn search(place: &Place, conn: &Connection, query: &Query) -> Result<Answer, String> {
    let terms = search::terms(&query.target);
    if terms.is_empty() {
        return Err("the search needs a word".to_string());
    }
    let glob = query.path.as_deref();
    let hits = search::search(
        conn,
        &place.root,
        &terms,
        query.any,
        glob,
        query.limit,
        query.context,
    )
    .map_err(describe(place))?;
    let empty = hits.rows.is_empty() && hits.omitted == 0;
    Ok((
        search::render(&hits, query.format, query.max_bytes),
        empty,
        None,
    ))
}

/// Runs a query command. Exit 0 with results, 1 with none, and 2 on an error.
fn run_query(query: &Query, ask: Ask) -> ExitCode {
    let result = place(&query.index).and_then(|place| {
        let conn = if query.update {
            open_updated(&place, &query.index)?.0
        } else {
            open_existing(&place)?
        };
        ask(&place, &conn, query)
    });
    match result {
        Ok((text, empty, hint)) => {
            print!("{text}");
            if let Some(hint) = hint {
                eprintln!("{NAME}: {hint}");
            }
            if empty {
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
