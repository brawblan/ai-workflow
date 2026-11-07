//! The SQL statements of the query commands. `PLANS` lists each one, so the `plans` command can
//! show its query plan and a test can find a scan of a large table.

/// The columns of a symbol row. `read_row` in `query.rs` reads them in this order.
macro_rules! symbol_columns {
    () => {
        "path, line, end_line, kind, name, qualified_name, level, id, parent"
    };
}

/// The columns of a link row.
macro_rules! link_columns {
    () => {
        "path, line, kind, target, resolved"
    };
}

macro_rules! symbol_filter {
    () => {
        "(qualified_name = ?1 OR name = ?1) AND (?2 IS NULL OR kind = ?2)"
    };
}

macro_rules! chunk_from {
    () => {
        "FROM chunks JOIN chunk_rows AS block ON block.id = chunks.rowid
         JOIN files ON files.path = block.path
         WHERE chunks MATCH ?1 AND (?2 IS NULL OR block.path GLOB ?2)"
    };
}

pub const FIND_COUNT: &str = concat!("SELECT count(*) FROM symbols WHERE ", symbol_filter!());

pub const FIND_ROWS: &str = concat!(
    "SELECT ",
    symbol_columns!(),
    " FROM symbols WHERE ",
    symbol_filter!(),
    " ORDER BY path, line LIMIT ?3"
);

pub const FILE_HASH: &str = "SELECT hash FROM files WHERE path = ?1";

pub const IS_INDEXED: &str = "SELECT count(*) > 0 FROM files WHERE path = ?1";

pub const OUTLINE: &str = concat!(
    "SELECT ",
    symbol_columns!(),
    " FROM symbols WHERE path = ?1 ORDER BY line, id"
);

pub const SEARCH_COUNT: &str = concat!("SELECT count(*) ", chunk_from!());

pub const SEARCH_ROWS: &str = concat!(
    "SELECT block.path, block.line, files.hash ",
    chunk_from!(),
    " ORDER BY bm25(chunks), block.path, block.line LIMIT ?3"
);

pub const PYTHON_FILES: &str = "SELECT path FROM files WHERE language = 'python' ORDER BY path";

/// The links that point into a file.
pub const REFS_INTO: &str = concat!(
    "SELECT ",
    link_columns!(),
    " FROM links WHERE resolved = ?1 ORDER BY path, line, id"
);

/// The links that start in a file.
pub const REFS_OUT_OF: &str = concat!(
    "SELECT ",
    link_columns!(),
    " FROM links WHERE path = ?1 ORDER BY line, id"
);

/// The links whose target text is a name.
pub const REFS_TARGET: &str = concat!(
    "SELECT ",
    link_columns!(),
    " FROM links WHERE target = ?1 ORDER BY path, line, id"
);

/// Each statement above with a short name.
pub const PLANS: &[(&str, &str)] = &[
    ("find-count", FIND_COUNT),
    ("find-rows", FIND_ROWS),
    ("file-hash", FILE_HASH),
    ("is-indexed", IS_INDEXED),
    ("outline", OUTLINE),
    ("search-count", SEARCH_COUNT),
    ("search-rows", SEARCH_ROWS),
    ("python-files", PYTHON_FILES),
    ("refs-into", REFS_INTO),
    ("refs-out-of", REFS_OUT_OF),
    ("refs-target", REFS_TARGET),
];
