//! `stone-index`: the code indexer of Cornerstone. This version has `--version` only.

use std::env;
use std::process::ExitCode;

const NAME: &str = env!("CARGO_PKG_NAME");
const VERSION: &str = env!("CARGO_PKG_VERSION");

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    match args.as_slice() {
        [flag] if flag == "--version" || flag == "-V" => {
            println!("{NAME} {VERSION}");
            ExitCode::SUCCESS
        }
        _ => {
            eprintln!("usage: {NAME} --version");
            ExitCode::from(2)
        }
    }
}

#[cfg(test)]
mod tests {}
