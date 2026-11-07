//! Tests of the incremental update, the summary, the schema reset, and concurrency
//! (AC 5, 6, 13, 14 and the file columns).

mod common;

use std::process::Stdio;

use common::{Fixture, summary};
use rusqlite::Connection;

const NEW_MTIME: u64 = 1_750_000_000;

fn two_files() -> Fixture {
    let fx = Fixture::new("update");
    fx.git_dir();
    fx.write("a.md", b"aaa\n");
    fx.write("b.py", b"bbb\n");
    fx
}

#[test]
fn ac6_first_build_counts_every_file_as_parsed() {
    let fx = two_files();
    assert_eq!(summary(&fx.build(&[])), (2, 0, 0));
}

#[test]
fn ac5_second_build_with_no_change_parses_nothing() {
    let fx = two_files();
    fx.build(&[]);
    assert_eq!(summary(&fx.build(&[])), (0, 2, 0));
}

#[test]
fn ac5_changed_content_is_parsed_and_the_hash_changes() {
    let fx = two_files();
    fx.build(&[]);
    let before = fx.hash("a.md");
    fx.write("a.md", b"zzz\n");
    fx.set_mtime("a.md", NEW_MTIME);
    assert_eq!(summary(&fx.build(&[])), (1, 1, 0));
    assert_ne!(fx.hash("a.md"), before);
}

#[test]
fn ac5_touched_file_is_unchanged_and_its_mtime_is_stored() {
    let fx = two_files();
    fx.build(&[]);
    let before = fx.mtime_ns("a.md");
    let hash = fx.hash("a.md");
    fx.set_mtime("a.md", NEW_MTIME);
    assert_eq!(summary(&fx.build(&[])), (0, 2, 0));
    assert_eq!(fx.hash("a.md"), hash);
    assert_ne!(fx.mtime_ns("a.md"), before);
    assert_eq!(fx.mtime_ns("a.md"), NEW_MTIME as i64 * 1_000_000_000);
    assert_eq!(summary(&fx.build(&[])), (0, 2, 0));
}

#[test]
fn ac5_deleted_file_is_removed_with_its_row() {
    let fx = two_files();
    fx.build(&[]);
    fx.remove("a.md");
    assert_eq!(summary(&fx.build(&[])), (0, 1, 1));
    assert_eq!(fx.paths(), vec!["b.py"]);
}

#[test]
fn ac5_file_that_becomes_ignored_is_removed() {
    let fx = two_files();
    fx.build(&[]);
    fx.write(".gitignore", b"a.md\n");
    assert_eq!(summary(&fx.build(&[])), (1, 1, 1));
    assert_eq!(fx.paths(), vec![".gitignore", "b.py"]);
}

#[test]
fn ac5_file_that_becomes_binary_is_removed() {
    let fx = two_files();
    fx.build(&[]);
    fx.write("a.md", b"a\0b\n");
    fx.set_mtime("a.md", NEW_MTIME);
    assert_eq!(summary(&fx.build(&[])), (0, 1, 1));
    assert_eq!(fx.paths(), vec!["b.py"]);
}

#[test]
fn ac5_file_that_becomes_too_large_is_removed() {
    let fx = two_files();
    fx.build(&[]);
    fx.write("a.md", b"aaaaaaaaaaaaaaaa\n");
    fx.set_mtime("a.md", NEW_MTIME);
    assert_eq!(summary(&fx.build(&["--max-file-size", "8"])), (0, 1, 1));
    assert_eq!(fx.paths(), vec!["b.py"]);
}

#[test]
fn ac13_wrong_schema_version_makes_a_new_index() {
    let fx = two_files();
    fx.build(&[]);
    {
        let conn = fx.conn();
        conn.execute(
            "UPDATE meta SET value = '999' WHERE key = 'schema_version'",
            [],
        )
        .unwrap();
        conn.execute("CREATE TABLE junk(x)", []).unwrap();
    }
    assert_eq!(summary(&fx.build(&[])), (2, 0, 0));
    assert_new_schema(&fx.conn());
}

#[test]
fn ac13_missing_meta_table_makes_a_new_index() {
    let fx = two_files();
    fx.build(&[]);
    {
        let conn = fx.conn();
        conn.execute("DROP TABLE meta", []).unwrap();
        conn.execute("CREATE TABLE junk(x)", []).unwrap();
    }
    assert_eq!(summary(&fx.build(&[])), (2, 0, 0));
    assert_new_schema(&fx.conn());
}

fn assert_new_schema(conn: &Connection) {
    let version: String = conn
        .query_row(
            "SELECT value FROM meta WHERE key = 'schema_version'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(version, "3");
    let junk: i64 = conn
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE name = 'junk'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(junk, 0);
}

#[test]
fn ac14_two_builds_at_the_same_time_keep_the_index_sound() {
    let fx = Fixture::new("concurrent");
    fx.git_dir();
    for i in 0..300 {
        fx.write(
            &format!("d{}/f{i}.py", i % 10),
            format!("x = {i}\n").as_bytes(),
        );
    }
    for round in 0..3 {
        if round == 2 {
            fx.remove("d0/f0.py");
        } else {
            let _ = std::fs::remove_dir_all(fx.root.join(".cornerstone"));
        }
        let spawn = || {
            fx.command(&fx.root, &["build"])
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .unwrap()
        };
        let (first, second) = (spawn(), spawn());
        let mut sums = Vec::new();
        for child in [first, second] {
            sums.push(summary(&child.wait_with_output().unwrap()));
        }
        sums.sort();
        if round != 2 {
            assert_eq!(sums, vec![(0, 300, 0), (300, 0, 0)], "round {round}");
        }
        let expected = if round == 2 { 299 } else { 300 };
        assert_eq!(fx.paths().len(), expected, "round {round}");
        let conn = fx.conn();
        let check: String = conn
            .query_row("PRAGMA integrity_check", [], |r| r.get(0))
            .unwrap();
        assert_eq!(check, "ok");
        let mode: String = conn
            .query_row("PRAGMA journal_mode", [], |r| r.get(0))
            .unwrap();
        assert_eq!(mode, "wal");
    }
}

#[test]
fn files_have_the_language_of_the_extension() {
    let fx = Fixture::new("language");
    let cases = [
        ("a.py", Some("python")),
        ("a.md", Some("markdown")),
        ("a.ts", Some("typescript")),
        ("a.tsx", Some("tsx")),
        ("a.js", Some("javascript")),
        ("a.jsx", Some("jsx")),
        ("a.xyz", None),
        ("Makefile", None),
    ];
    for (name, _) in cases {
        fx.write(name, b"x\n");
    }
    summary(&fx.build(&[]));
    for (name, expected) in cases {
        let got: Option<String> = fx
            .conn()
            .query_row("SELECT language FROM files WHERE path = ?1", [name], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(got.as_deref(), expected, "{name}");
    }
}

#[test]
fn files_have_a_line_count() {
    let fx = Fixture::new("lines");
    let cases: [(&str, &[u8], i64); 5] = [
        ("empty.txt", b"", 0),
        ("one.txt", b"a", 1),
        ("nl.txt", b"a\n", 1),
        ("nonl.txt", b"a\nb", 2),
        ("three.txt", b"a\n\nb\n", 3),
    ];
    for (name, content, _) in cases {
        fx.write(name, content);
    }
    summary(&fx.build(&[]));
    for (name, _, expected) in cases {
        let lines: i64 = fx
            .conn()
            .query_row("SELECT lines FROM files WHERE path = ?1", [name], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(lines, expected, "{name}");
    }
}

#[test]
fn the_symbols_table_exists_and_is_empty() {
    let fx = two_files();
    fx.build(&[]);
    let count: i64 = fx
        .conn()
        .query_row("SELECT count(*) FROM symbols", [], |r| r.get(0))
        .unwrap();
    assert_eq!(count, 0);
}

#[test]
fn racily_clean_file_is_read_again_after_a_same_size_edit() {
    let fx = Fixture::new("racy");
    std::fs::write(fx.root.join("a.md"), b"aaa\n").unwrap();
    fx.build(&[]);
    assert_eq!(fx.mtime_ns("a.md"), 0);
    let before = fx.hash("a.md");
    let mtime = std::fs::metadata(fx.root.join("a.md"))
        .unwrap()
        .modified()
        .unwrap();
    std::fs::write(fx.root.join("a.md"), b"bbb\n").unwrap();
    let file = std::fs::File::options()
        .write(true)
        .open(fx.root.join("a.md"))
        .unwrap();
    file.set_modified(mtime).unwrap();
    assert_eq!(summary(&fx.build(&[])), (1, 0, 0));
    assert_ne!(fx.hash("a.md"), before);
}
