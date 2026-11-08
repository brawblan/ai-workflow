//! Tests of the `stone-index` command line: the version flags and the usage error.

use std::process::{Command, Output};

const BIN: &str = env!("CARGO_BIN_EXE_stone-index");
const VERSION: &str = env!("CARGO_PKG_VERSION");

fn run(args: &[&str]) -> Output {
    Command::new(BIN)
        .args(args)
        .output()
        .expect("stone-index must start")
}

fn expected_version_line() -> String {
    format!("stone-index {VERSION}\n")
}

#[test]
fn long_flag_prints_name_and_version() {
    let out = run(&["--version"]);
    assert_eq!(out.status.code(), Some(0));
    assert_eq!(
        String::from_utf8_lossy(&out.stdout),
        expected_version_line()
    );
}

#[test]
fn short_flag_prints_the_same_output() {
    let long = run(&["--version"]);
    let short = run(&["-V"]);
    assert_eq!(short.status.code(), Some(0));
    assert_eq!(short.stdout, long.stdout);
    assert_eq!(
        String::from_utf8_lossy(&short.stdout),
        expected_version_line()
    );
}

#[test]
fn no_arguments_exit_2_with_usage_on_stderr() {
    let out = run(&[]);
    assert_eq!(out.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&out.stderr).contains("usage:"));
    assert!(out.stdout.is_empty());
}

#[test]
fn unknown_argument_exit_2_with_usage_on_stderr() {
    let out = run(&["--bogus"]);
    assert_eq!(out.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&out.stderr).contains("usage:"));
    assert!(out.stdout.is_empty());
}
