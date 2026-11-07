//! The command line: the commands and their options.

use std::path::PathBuf;
use std::slice::Iter;

use crate::lang::{self, Override};

/// The default of `--max-file-size`: 1 MB.
pub const DEFAULT_MAX_FILE_SIZE: u64 = 1_048_576;

/// The default of `--limit`.
pub const DEFAULT_LIMIT: usize = 20;

/// The default of `--limit` for `show`.
pub const DEFAULT_SHOW_LIMIT: usize = 5;

/// The default of `--max-lines`.
pub const DEFAULT_MAX_LINES: usize = 80;

pub const USAGE: &str =
    "usage: stone-index build [--db PATH] [--max-file-size BYTES] [--lang EXT=LANG]
       stone-index plans [--db PATH]
       stone-index find NAME [--kind KIND] [QUERY OPTIONS]
       stone-index show NAME [--kind KIND] [--max-lines N] [QUERY OPTIONS]
       stone-index outline PATH [QUERY OPTIONS]
       stone-index refs PATH|MODULE [QUERY OPTIONS]
       stone-index search WORDS [--path GLOB] [--context N] [QUERY OPTIONS]
       stone-index --version
query options: --limit N, --format text|json, --no-update, --db PATH, --max-file-size BYTES,
--lang EXT=LANG (repeatable, for example h=c),
and -- before a NAME or a PATH that starts with -";

pub enum Command {
    Version,
    Build(IndexOptions),
    Plans(IndexOptions),
    Find(Query),
    Show(Query),
    Outline(Query),
    Refs(Query),
    Search(Query),
}

/// The options of each command that updates the index.
pub struct IndexOptions {
    pub db: Option<PathBuf>,
    pub max_file_size: u64,
    pub langs: Vec<Override>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Format {
    Text,
    Json,
}

/// A `find` or an `outline` command. `target` is the name or the path.
pub struct Query {
    pub target: String,
    pub kind: Option<String>,
    pub path: Option<String>,
    pub limit: usize,
    pub max_lines: usize,
    pub context: usize,
    pub format: Format,
    pub update: bool,
    pub index: IndexOptions,
}

pub fn parse(args: &[String]) -> Result<Command, String> {
    match args.split_first() {
        Some((flag, [])) if flag == "--version" || flag == "-V" => Ok(Command::Version),
        Some((command, rest)) => match command.as_str() {
            "build" => parse_query(rest, false, &[], DEFAULT_LIMIT)
                .map(|query| Command::Build(query.index)),
            "plans" => parse_query(rest, false, &[], DEFAULT_LIMIT)
                .map(|query| Command::Plans(query.index)),
            "find" => parse_query(rest, true, &["--kind"], DEFAULT_LIMIT).map(Command::Find),
            "show" => parse_query(rest, true, &["--kind", "--max-lines"], DEFAULT_SHOW_LIMIT)
                .map(Command::Show),
            "outline" => parse_query(rest, true, &[], DEFAULT_LIMIT).map(Command::Outline),
            "refs" => parse_query(rest, true, &[], DEFAULT_LIMIT).map(Command::Refs),
            "search" => parse_query(rest, true, &["--path", "--context"], DEFAULT_LIMIT)
                .map(Command::Search),
            _ => Err(format!("unknown command or option: {command}")),
        },
        None => Err("no command".to_string()),
    }
}

/// Parses the options. A query command needs one target. `extra` holds the options of the
/// command, for example `--kind` of `find` or `--path` of `search`.
fn parse_query(
    args: &[String],
    is_query: bool,
    extra: &[&str],
    default_limit: usize,
) -> Result<Query, String> {
    let mut query = Query {
        target: String::new(),
        kind: None,
        path: None,
        limit: default_limit,
        max_lines: DEFAULT_MAX_LINES,
        context: 0,
        format: Format::Text,
        update: true,
        index: IndexOptions {
            db: None,
            max_file_size: DEFAULT_MAX_FILE_SIZE,
            langs: Vec::new(),
        },
    };
    let mut targets = Vec::new();
    let mut args = args.iter();
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--db" => query.index.db = Some(PathBuf::from(value(&mut args, arg)?)),
            "--max-file-size" => query.index.max_file_size = number(value(&mut args, arg)?, arg)?,
            "--lang" => query
                .index
                .langs
                .push(lang::parse_override(value(&mut args, arg)?)?),
            "--kind" if extra.contains(&"--kind") => {
                query.kind = Some(value(&mut args, arg)?.to_string())
            }
            "--path" if extra.contains(&"--path") => {
                query.path = Some(value(&mut args, arg)?.to_string());
            }
            "--max-lines" if extra.contains(&"--max-lines") => {
                query.max_lines = number(value(&mut args, arg)?, arg)?;
            }
            "--context" if extra.contains(&"--context") => {
                query.context = number(value(&mut args, arg)?, arg)?;
            }
            "--limit" if is_query => query.limit = number(value(&mut args, arg)?, arg)?,
            "--format" if is_query => query.format = format(value(&mut args, arg)?)?,
            "--no-update" if is_query => query.update = false,
            "--" if is_query => targets.extend(args.by_ref().cloned()),
            _ if is_query && !arg.starts_with("--") => targets.push(arg.clone()),
            _ => return Err(format!("unknown option: {arg}")),
        }
    }
    match (is_query, targets.as_slice()) {
        (false, []) => {}
        (true, [target]) => query.target.clone_from(target),
        (true, []) => return Err("the command needs a name or a path".to_string()),
        _ => return Err(format!("too many arguments: {}", targets.join(" "))),
    }
    Ok(query)
}

fn value<'a>(args: &mut Iter<'a, String>, option: &str) -> Result<&'a str, String> {
    args.next()
        .map(String::as_str)
        .ok_or_else(|| format!("{option} needs a value"))
}

fn number<T: std::str::FromStr>(text: &str, option: &str) -> Result<T, String> {
    text.parse()
        .map_err(|_| format!("{option} needs a number, not {text:?}"))
}

fn format(text: &str) -> Result<Format, String> {
    match text {
        "text" => Ok(Format::Text),
        "json" => Ok(Format::Json),
        _ => Err(format!("--format needs text or json, not {text:?}")),
    }
}
