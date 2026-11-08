//! The query plans of the query statements: none scans a large table without an index.

mod common;

use common::{Fixture, stderr, stdout};
use rusqlite::Connection;

const NAMES: [&str; 11] = [
    "find-count",
    "find-rows",
    "file-hash",
    "is-indexed",
    "outline",
    "search-count",
    "search-rows",
    "python-files",
    "refs-into",
    "refs-out-of",
    "refs-target",
];

/// Tables where a full scan is a defect. `files` is not in the list: `python-files` scans it.
/// The virtual table `chunks` (FTS5) is not in the list either.
const GUARDED: [&str; 3] = ["symbols", "links", "chunk_rows"];

/// Returns each plan detail that scans a guarded table without an index.
fn unindexed_scans(details: &[String], tables: &[&str]) -> Vec<String> {
    details
        .iter()
        .filter(|detail| {
            tables.iter().any(|table| {
                let scan = format!("SCAN {table}");
                detail.strip_prefix(&scan).is_some_and(|rest| {
                    (rest.is_empty() || rest.starts_with(' '))
                        && !(rest.contains("USING") && rest.contains("INDEX"))
                })
            })
        })
        .cloned()
        .collect()
}

fn plan_of(conn: &Connection, sql: &str) -> Vec<String> {
    let mut statement = conn.prepare(&format!("EXPLAIN QUERY PLAN {sql}")).unwrap();
    statement
        .query_map([], |row| row.get::<_, String>(3))
        .unwrap()
        .map(Result::unwrap)
        .collect()
}

#[test]
fn plans_use_an_index_for_symbols_links_and_chunk_rows() {
    let fx = Fixture::new("plans");
    fx.write(
        "app.py",
        b"import os\n\n\ndef greet(name):\n    return os.getcwd() + name\n",
    );
    fx.write(
        "doc.md",
        b"# Title\n\nSome text about greet.\n\nSee [the app](app.py).\n",
    );
    let built = fx.build(&[]);
    assert_eq!(built.status.code(), Some(0), "stderr: {}", stderr(&built));

    let out = fx.run_in(
        &fx.root,
        &["plans", "--db", fx.default_db().to_str().unwrap()],
    );
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(&out));
    let text = stdout(&out);

    let mut details = Vec::new();
    for line in text.lines() {
        let (name, detail) = line.split_once('\t').expect("name TAB detail");
        assert!(NAMES.contains(&name), "unknown name {name:?}");
        details.push((name.to_string(), detail.to_string()));
    }
    for name in NAMES {
        assert!(
            details.iter().any(|(n, _)| n == name),
            "no plan line for {name}"
        );
    }
    for (name, detail) in &details {
        let bad = unindexed_scans(std::slice::from_ref(detail), &GUARDED);
        assert!(bad.is_empty(), "{name} scans without an index: {detail}");
    }
}

#[test]
fn detector_flags_a_scan_and_accepts_an_indexed_query() {
    let conn = Connection::open_in_memory().unwrap();
    conn.execute_batch(
        "CREATE TABLE symbols (id INTEGER PRIMARY KEY, name TEXT, kind TEXT);
         CREATE INDEX symbols_kind ON symbols(kind);",
    )
    .unwrap();

    let scan = plan_of(&conn, "SELECT id FROM symbols WHERE name = 'x'");
    let flagged = unindexed_scans(&scan, &["symbols"]);
    assert!(!flagged.is_empty(), "no scan flagged in {scan:?}");
    assert!(flagged[0].starts_with("SCAN symbols"));

    let indexed = plan_of(&conn, "SELECT id FROM symbols WHERE kind = 'fn'");
    assert!(
        unindexed_scans(&indexed, &["symbols"]).is_empty(),
        "indexed query flagged: {indexed:?}"
    );

    let literal = vec![
        "SCAN symbols USING INDEX x".to_string(),
        "SCAN chunks VIRTUAL TABLE INDEX 0:M1".to_string(),
    ];
    assert!(unindexed_scans(&literal, &["symbols"]).is_empty());
}
