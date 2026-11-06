//! The SQLite index: open it, check the schema version, and make the tables.

use std::path::Path;
use std::time::Duration;

use rusqlite::{Connection, OptionalExtension, Result};

/// Change this number with each change to `SCHEMA`. A build then makes a new index.
pub const SCHEMA_VERSION: i64 = 1;

/// A second build waits this long for the first build to finish.
const BUSY_TIMEOUT: Duration = Duration::from_secs(600);

/// Each table that refers to `files` deletes its rows with the file (`ON DELETE CASCADE`).
const SCHEMA: &[&str] = &[
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE files (
        path TEXT PRIMARY KEY,
        size INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL,
        hash TEXT NOT NULL,
        language TEXT,
        lines INTEGER NOT NULL
    )",
    "CREATE TABLE symbols (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        qualified_name TEXT NOT NULL,
        kind TEXT NOT NULL,
        path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
        line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        parent INTEGER REFERENCES symbols(id) ON DELETE CASCADE
    )",
    "CREATE INDEX symbols_name ON symbols(name)",
    "CREATE INDEX symbols_qualified_name ON symbols(qualified_name)",
    "CREATE INDEX symbols_path_line ON symbols(path, line)",
];

/// Opens the index in WAL mode, so a reader does not wait for a build.
pub fn open(path: &Path) -> Result<Connection> {
    let conn = Connection::open(path)?;
    conn.busy_timeout(BUSY_TIMEOUT)?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "foreign_keys", "ON")?;
    Ok(conn)
}

/// Makes a new, empty index if the schema version is not `SCHEMA_VERSION`.
/// Call it in a write transaction. Returns true if it made a new index.
pub fn ensure_schema(conn: &Connection) -> Result<bool> {
    if stored_version(conn)? == Some(SCHEMA_VERSION) {
        return Ok(false);
    }
    drop_all_tables(conn)?;
    for statement in SCHEMA {
        conn.execute(statement, [])?;
    }
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?1)",
        [SCHEMA_VERSION.to_string()],
    )?;
    Ok(true)
}

fn stored_version(conn: &Connection) -> Result<Option<i64>> {
    let has_meta: bool = conn.query_row(
        "SELECT count(*) > 0 FROM sqlite_master WHERE type = 'table' AND name = 'meta'",
        [],
        |row| row.get(0),
    )?;
    if !has_meta {
        return Ok(None);
    }
    let value: Option<String> = conn
        .query_row(
            "SELECT value FROM meta WHERE key = 'schema_version'",
            [],
            |row| row.get(0),
        )
        .optional()?;
    Ok(value.and_then(|text| text.parse().ok()))
}

fn drop_all_tables(conn: &Connection) -> Result<()> {
    let names = conn
        .prepare(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'",
        )?
        .query_map([], |row| row.get::<_, String>(0))?
        .collect::<Result<Vec<_>>>()?;
    for name in names {
        let quoted = name.replace('"', "\"\"");
        conn.execute(&format!("DROP TABLE IF EXISTS \"{quoted}\""), [])?;
    }
    Ok(())
}
