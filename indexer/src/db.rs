//! The SQLite index: open it, check the schema version, and make the tables.

use std::path::Path;
use std::thread;
use std::time::{Duration, Instant};

use rusqlite::{Connection, Error, ErrorCode, OptionalExtension, Result};

/// Change this number with each change to `SCHEMA`, and with each parser change that changes the
/// rows. A build then makes a new index, so it parses each file again.
pub const SCHEMA_VERSION: i64 = 4;

/// A second build waits this long for the first build to finish.
const BUSY_TIMEOUT: Duration = Duration::from_secs(600);

/// The wait between two tries to set WAL mode.
const WAL_RETRY: Duration = Duration::from_millis(20);

/// Each table that refers to `files` deletes its rows with the file (`ON DELETE CASCADE`). The
/// contentless FTS5 table `chunks` has the same rowid as `chunk_rows`, and a trigger deletes it
/// with its row. A search reads the text from the file.
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
        parent INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
        level INTEGER
    )",
    "CREATE INDEX symbols_name ON symbols(name)",
    "CREATE INDEX symbols_qualified_name ON symbols(qualified_name)",
    "CREATE INDEX symbols_path_line ON symbols(path, line)",
    "CREATE TABLE links (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
        line INTEGER NOT NULL,
        kind TEXT NOT NULL,
        target TEXT NOT NULL,
        resolved TEXT NOT NULL
    )",
    "CREATE INDEX links_path ON links(path)",
    "CREATE INDEX links_target ON links(target)",
    "CREATE INDEX links_resolved ON links(resolved)",
    "CREATE TABLE chunk_rows (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
        line INTEGER NOT NULL
    )",
    "CREATE INDEX chunk_rows_path ON chunk_rows(path)",
    "CREATE VIRTUAL TABLE chunks USING fts5(
        text, content='', contentless_delete=1, tokenize='unicode61 remove_diacritics 0'
    )",
    "CREATE TRIGGER chunk_rows_delete AFTER DELETE ON chunk_rows BEGIN
        DELETE FROM chunks WHERE rowid = old.id;
    END",
];

/// What the file at the index path holds.
enum Contents {
    Empty,
    Index(Option<i64>),
    Foreign,
}

/// Opens the index in WAL mode, so a reader does not wait for a build.
pub fn open(path: &Path) -> Result<Connection> {
    let conn = Connection::open(path)?;
    conn.busy_timeout(BUSY_TIMEOUT)?;
    set_wal(&conn)?;
    conn.pragma_update(None, "foreign_keys", "ON")?;
    Ok(conn)
}

/// The text of an index error for the user.
pub fn describe(error: &Error) -> String {
    if error.sqlite_error_code() == Some(ErrorCode::DatabaseBusy) {
        format!("another process holds the index lock: {error}")
    } else {
        format!("broken index: {error}")
    }
}

/// SQLite does not call the busy handler when two processes set WAL mode on a new file at the same
/// time. One of them gets `SQLITE_BUSY` at once, so this function tries again until the timeout.
fn set_wal(conn: &Connection) -> Result<()> {
    let start = Instant::now();
    loop {
        match conn.pragma_update(None, "journal_mode", "WAL") {
            Err(error)
                if error.sqlite_error_code() == Some(ErrorCode::DatabaseBusy)
                    && start.elapsed() < BUSY_TIMEOUT =>
            {
                thread::sleep(WAL_RETRY);
            }
            result => return result,
        }
    }
}

/// Makes a new, empty index if the schema version is not `SCHEMA_VERSION`.
/// Call it in a write transaction. Returns true if it made a new index.
/// A database with other tables, and no `meta` or `files` table, is not an index. The function
/// then changes nothing and returns an error.
pub fn ensure_schema(conn: &Connection) -> std::result::Result<bool, String> {
    match contents(conn).map_err(|error| describe(&error))? {
        Contents::Index(Some(SCHEMA_VERSION)) => return Ok(false),
        Contents::Foreign => return Err(FOREIGN.to_string()),
        Contents::Empty | Contents::Index(_) => {}
    }
    make_schema(conn).map_err(|error| describe(&error))?;
    Ok(true)
}

/// The error for a database that is not an index.
const FOREIGN: &str =
    "broken index: the database is not a stone-index index. Use another --db path.";

/// An error if the file is not an index with the schema of this binary.
pub fn check_current(conn: &Connection) -> std::result::Result<(), String> {
    match contents(conn).map_err(|error| describe(&error))? {
        Contents::Index(Some(SCHEMA_VERSION)) => Ok(()),
        Contents::Foreign => Err(FOREIGN.to_string()),
        Contents::Empty | Contents::Index(_) => Err("broken index: the schema version is not \
             the version of this binary. Run `stone-index build`."
            .to_string()),
    }
}

fn make_schema(conn: &Connection) -> Result<()> {
    drop_all_tables(conn)?;
    for statement in SCHEMA {
        conn.execute(statement, [])?;
    }
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?1)",
        [SCHEMA_VERSION.to_string()],
    )?;
    Ok(())
}

fn contents(conn: &Connection) -> Result<Contents> {
    let names = conn
        .prepare("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")?
        .query_map([], |row| row.get::<_, String>(0))?
        .collect::<Result<Vec<_>>>()?;
    if names.is_empty() {
        return Ok(Contents::Empty);
    }
    if names.iter().any(|name| name == "meta") {
        return stored_version(conn).map(Contents::Index);
    }
    if names.iter().any(|name| name == "files") {
        return Ok(Contents::Index(None));
    }
    Ok(Contents::Foreign)
}

fn stored_version(conn: &Connection) -> Result<Option<i64>> {
    let value: Option<String> = conn
        .query_row(
            "SELECT value FROM meta WHERE key = 'schema_version'",
            [],
            |row| row.get(0),
        )
        .optional()?;
    Ok(value.and_then(|text| text.parse().ok()))
}

/// Drops each table, the virtual tables and then the newest first. A virtual table drops its own
/// tables. A table that refers to another table is newer, so it goes first: the foreign key check
/// of a drop needs the table that the key refers to.
fn drop_all_tables(conn: &Connection) -> Result<()> {
    let names = conn
        .prepare(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
             ORDER BY sql LIKE 'CREATE VIRTUAL TABLE%' DESC, rowid DESC",
        )?
        .query_map([], |row| row.get::<_, String>(0))?
        .collect::<Result<Vec<_>>>()?;
    for name in names {
        let quoted = name.replace('"', "\"\"");
        conn.execute(&format!("DROP TABLE IF EXISTS \"{quoted}\""), [])?;
    }
    Ok(())
}
