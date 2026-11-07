//! `stone-index`: the code indexer of Cornerstone. This version has `build` and `--version`.

mod cli;
mod db;
mod lang;
mod update;
mod walk;

use std::env;
use std::fs;
use std::process::ExitCode;

use cli::{Command, IndexOptions, USAGE};
use update::Summary;

const NAME: &str = env!("CARGO_PKG_NAME");
const VERSION: &str = env!("CARGO_PKG_VERSION");

/// The path of the index from the repo root, if `--db` does not set one.
const DEFAULT_DB: &str = ".cornerstone/index.db";

/// The exit code for a usage error or a broken index.
const EXIT_ERROR: u8 = 2;

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    match cli::parse(&args) {
        Ok(Command::Version) => {
            println!("{NAME} {VERSION}");
            ExitCode::SUCCESS
        }
        Ok(Command::Build(options)) => match build(&options) {
            Ok(summary) => {
                println!("{summary}");
                ExitCode::SUCCESS
            }
            Err(message) => fail(&message),
        },
        Err(message) => fail(&format!("{message}\n{USAGE}")),
    }
}

/// Finds the repo root and the index, then updates the index.
fn build(options: &IndexOptions) -> Result<Summary, String> {
    let cwd =
        env::current_dir().map_err(|error| format!("cannot read the current folder: {error}"))?;
    let root = walk::repo_root(&cwd);
    let db_path = options
        .db
        .as_ref()
        .map_or_else(|| root.join(DEFAULT_DB), |path| cwd.join(path));
    if let Some(parent) = db_path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("cannot make {}: {error}", parent.display()))?;
    }
    let with_path = |message: String| format!("{}: {message}", db_path.display());
    let mut conn = db::open(&db_path).map_err(|error| with_path(db::describe(&error)))?;
    update::run(&mut conn, &root, &db_path, options.max_file_size).map_err(with_path)
}

fn fail(message: &str) -> ExitCode {
    eprintln!("{NAME}: {message}");
    ExitCode::from(EXIT_ERROR)
}
