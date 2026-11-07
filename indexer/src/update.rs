//! The incremental update: index new and changed files, and remove the rows of gone files.

use std::collections::{HashMap, HashSet};
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use rayon::prelude::*;
use rusqlite::{Connection, Result, TransactionBehavior, params};
use xxhash_rust::xxh3::xxh3_64;

use crate::db;
use crate::lang;
use crate::symbols::{self, Symbol};
use crate::walk::{self, Candidate};

/// A file with a NUL byte in this many first bytes is binary, and the index skips it.
const BINARY_CHECK_BYTES: u64 = 8192;

/// A file changed less than this long before the build can change again with the same modified
/// time. The index then stores the modified time 0, so the next build reads the file again.
const RACY_WINDOW: Duration = Duration::from_secs(2);

#[derive(Default)]
pub struct Summary {
    pub parsed: usize,
    pub unchanged: usize,
    pub removed: usize,
    pub elapsed: Duration,
}

impl fmt::Display for Summary {
    fn fmt(&self, out: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            out,
            "{} parsed, {} unchanged, {} removed in {:.2}s",
            self.parsed,
            self.unchanged,
            self.removed,
            self.elapsed.as_secs_f64()
        )
    }
}

/// The row of a file in the index, as the last build wrote it.
struct Stored {
    size: i64,
    mtime_ns: i64,
    hash: String,
}

/// A file that the update read, with the facts to write.
struct Prepared<'a> {
    candidate: &'a Candidate,
    hash: String,
    lines: i64,
    language: Option<&'static str>,
    symbols: Vec<Symbol>,
}

/// Brings the index at `db_path` up to date with the files under `root`.
/// The update is one write transaction, so a second build waits for the first.
pub fn run(
    conn: &mut Connection,
    root: &Path,
    db_path: &Path,
    max_size: u64,
) -> std::result::Result<Summary, String> {
    let start = Instant::now();
    let describe = |error: rusqlite::Error| db::describe(&error);
    let tx = conn
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(describe)?;
    db::ensure_schema(&tx)?;
    let mut summary = sync(&tx, root, db_path, max_size).map_err(describe)?;
    tx.commit().map_err(describe)?;
    summary.elapsed = start.elapsed();
    Ok(summary)
}

fn sync(conn: &Connection, root: &Path, db_path: &Path, max_size: u64) -> Result<Summary> {
    let racy_from = now_ns().saturating_sub(i64::try_from(RACY_WINDOW.as_nanos()).unwrap_or(0));
    let stored = stored_files(conn)?;
    let candidates = walk::files(root, max_size, &index_files(db_path));
    let mut summary = Summary::default();
    let mut seen = HashSet::new();
    let mut changed = Vec::new();
    for candidate in &candidates {
        let old = stored.get(&candidate.path);
        if old.is_some_and(|old| old.size == candidate.size && old.mtime_ns == candidate.mtime_ns) {
            summary.unchanged += 1;
            seen.insert(candidate.path.as_str());
        } else {
            changed.push(candidate);
        }
    }
    let prepared: Vec<Prepared> = changed
        .into_par_iter()
        .filter_map(|candidate| prepare(candidate, stored.get(&candidate.path)))
        .collect();
    for prepared in prepared {
        seen.insert(prepared.candidate.path.as_str());
        let old = stored.get(&prepared.candidate.path);
        if write(conn, &prepared, old, racy_from)? {
            summary.parsed += 1;
        } else {
            summary.unchanged += 1;
        }
    }
    summary.removed = remove_gone(conn, &stored, &seen)?;
    Ok(summary)
}

fn now_ns() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |age| i64::try_from(age.as_nanos()).unwrap_or(i64::MAX))
}

/// The index file and the SQLite files next to it. The walk skips them.
fn index_files(db_path: &Path) -> Vec<PathBuf> {
    let mut paths = vec![db_path.to_path_buf()];
    for suffix in ["-wal", "-shm", "-journal"] {
        let mut name = db_path.as_os_str().to_owned();
        name.push(suffix);
        paths.push(PathBuf::from(name));
    }
    paths
}

fn stored_files(conn: &Connection) -> Result<HashMap<String, Stored>> {
    let mut statement = conn.prepare("SELECT path, size, mtime_ns, hash FROM files")?;
    let rows = statement.query_map([], |row| {
        let stored = Stored {
            size: row.get(1)?,
            mtime_ns: row.get(2)?,
            hash: row.get(3)?,
        };
        Ok((row.get(0)?, stored))
    })?;
    rows.collect()
}

/// Reads a file, and parses it if the content hash changed. Returns `None` if the read fails or
/// the file is binary. The update calls it on many threads at once.
fn prepare<'a>(candidate: &'a Candidate, old: Option<&Stored>) -> Option<Prepared<'a>> {
    let bytes = read_text(&candidate.abs)?;
    let hash = format!("{:016x}", xxh3_64(&bytes));
    let language = lang::language(&candidate.path);
    let changed = old.is_none_or(|old| old.hash != hash);
    let newlines = bytes.iter().filter(|&&byte| byte == b'\n').count();
    let last_line = usize::from(!bytes.is_empty() && !bytes.ends_with(b"\n"));
    Some(Prepared {
        candidate,
        hash,
        lines: i64::try_from(newlines + last_line).unwrap_or(i64::MAX),
        language,
        symbols: match language {
            Some(language) if changed => symbols::symbols(language, &bytes),
            _ => Vec::new(),
        },
    })
}

/// Reads the first 8 KB, and the rest only if the first part has no NUL byte.
fn read_text(path: &Path) -> Option<Vec<u8>> {
    let mut file = File::open(path).ok()?;
    let mut bytes = Vec::new();
    (&mut file)
        .take(BINARY_CHECK_BYTES)
        .read_to_end(&mut bytes)
        .ok()?;
    if bytes.contains(&0) {
        return None;
    }
    file.read_to_end(&mut bytes).ok()?;
    Some(bytes)
}

/// Writes the row of one file. Returns false if only the size or the modified time changed.
/// A new or changed file gets a new row, so `ON DELETE CASCADE` removes its old rows in the
/// other tables.
fn write(
    conn: &Connection,
    prepared: &Prepared,
    old: Option<&Stored>,
    racy_from: i64,
) -> Result<bool> {
    let candidate = prepared.candidate;
    let mtime_ns = if candidate.mtime_ns >= racy_from {
        0
    } else {
        candidate.mtime_ns
    };
    if old.is_some_and(|old| old.hash == prepared.hash) {
        conn.execute(
            "UPDATE files SET size = ?2, mtime_ns = ?3 WHERE path = ?1",
            params![candidate.path, candidate.size, mtime_ns],
        )?;
        return Ok(false);
    }
    conn.execute("DELETE FROM files WHERE path = ?1", [&candidate.path])?;
    conn.execute(
        "INSERT INTO files (path, size, mtime_ns, hash, language, lines)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
        params![
            candidate.path,
            candidate.size,
            mtime_ns,
            prepared.hash,
            prepared.language,
            prepared.lines
        ],
    )?;
    write_symbols(conn, &candidate.path, &prepared.symbols)?;
    Ok(true)
}

fn write_symbols(conn: &Connection, path: &str, symbols: &[Symbol]) -> Result<()> {
    let mut insert = conn.prepare_cached(
        "INSERT INTO symbols (name, qualified_name, kind, path, line, end_line, parent, level)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
    )?;
    let mut ids = Vec::with_capacity(symbols.len());
    for symbol in symbols {
        let parent = symbol.parent.map(|index: usize| ids[index]);
        let params = params![
            symbol.name,
            symbol.qualified_name,
            symbol.kind,
            path,
            symbol.line,
            symbol.end_line,
            parent,
            symbol.level
        ];
        ids.push(insert.insert(params)?);
    }
    Ok(())
}

/// Deletes the rows of each stored file that the walk did not keep. Returns the count.
fn remove_gone(
    conn: &Connection,
    stored: &HashMap<String, Stored>,
    seen: &HashSet<&str>,
) -> Result<usize> {
    let mut removed = 0;
    for path in stored.keys().filter(|path| !seen.contains(path.as_str())) {
        removed += conn.execute("DELETE FROM files WHERE path = ?1", [path])?;
    }
    Ok(removed)
}
