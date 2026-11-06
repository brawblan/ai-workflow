//! The command line: the commands and their options.

use std::path::PathBuf;
use std::slice::Iter;

/// The default of `--max-file-size`: 1 MB.
pub const DEFAULT_MAX_FILE_SIZE: u64 = 1_048_576;

pub const USAGE: &str = "usage: stone-index build [--db PATH] [--max-file-size BYTES]
       stone-index --version";

pub enum Command {
    Version,
    Build(IndexOptions),
}

/// The options of each command that updates the index.
pub struct IndexOptions {
    pub db: Option<PathBuf>,
    pub max_file_size: u64,
}

pub fn parse(args: &[String]) -> Result<Command, String> {
    match args.split_first() {
        Some((flag, [])) if flag == "--version" || flag == "-V" => Ok(Command::Version),
        Some((command, rest)) if command == "build" => {
            parse_index_options(rest).map(Command::Build)
        }
        Some((other, _)) => Err(format!("unknown command or option: {other}")),
        None => Err("no command".to_string()),
    }
}

fn parse_index_options(args: &[String]) -> Result<IndexOptions, String> {
    let mut options = IndexOptions {
        db: None,
        max_file_size: DEFAULT_MAX_FILE_SIZE,
    };
    let mut args = args.iter();
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--db" => options.db = Some(PathBuf::from(value(&mut args, arg)?)),
            "--max-file-size" => options.max_file_size = parse_bytes(value(&mut args, arg)?)?,
            _ => return Err(format!("unknown option: {arg}")),
        }
    }
    Ok(options)
}

fn value<'a>(args: &mut Iter<'a, String>, option: &str) -> Result<&'a str, String> {
    args.next()
        .map(String::as_str)
        .ok_or_else(|| format!("{option} needs a value"))
}

fn parse_bytes(text: &str) -> Result<u64, String> {
    text.parse()
        .map_err(|_| format!("--max-file-size needs a number of bytes, not {text:?}"))
}
