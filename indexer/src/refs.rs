//! The `refs` query: the links into a file or a module, and the links out of it.

use std::fmt::Write;

use rusqlite::{Connection, Result};

use crate::cli::Format;
use crate::query::{self, json_string, plain};
use crate::resolve::Resolver;

pub struct Ref {
    path: String,
    line: i64,
    kind: String,
    target: String,
    resolved: String,
}

/// The links in and out, and the count of the links that the limit cut.
pub struct Refs {
    pub incoming: Vec<Ref>,
    pub outgoing: Vec<Ref>,
    pub omitted: usize,
}

const COLUMNS: &str = "path, line, kind, target, resolved";

/// The links of `path` if the index has that file. Else the links of the Python module `name`,
/// or the links whose target text is `name`. Each group keeps at most `limit` links.
pub fn refs(conn: &Connection, path: Option<&str>, name: &str, limit: usize) -> Result<Refs> {
    let tx = conn.unchecked_transaction()?;
    let file = match path {
        Some(path) if query::is_indexed(&tx, path)? => Some(path.to_string()),
        _ => module_file(&tx, name)?,
    };
    let (incoming, outgoing) = match &file {
        Some(file) => (
            select(&tx, "resolved = ?1 ORDER BY path, line, id", file)?,
            select(&tx, "path = ?1 ORDER BY line, id", file)?,
        ),
        None => (
            select(&tx, "target = ?1 ORDER BY path, line, id", name)?,
            Vec::new(),
        ),
    };
    let mut omitted = 0;
    let mut cut = |mut rows: Vec<Ref>| {
        omitted += rows.len().saturating_sub(limit);
        rows.truncate(limit);
        rows
    };
    let (incoming, outgoing) = (cut(incoming), cut(outgoing));
    Ok(Refs {
        incoming,
        outgoing,
        omitted,
    })
}

/// The Python file of the dotted module `name`, from the files of the index.
fn module_file(conn: &Connection, name: &str) -> Result<Option<String>> {
    let paths = conn
        .prepare("SELECT path FROM files WHERE language = 'python' ORDER BY path")?
        .query_map([], |row| row.get::<_, String>(0))?
        .collect::<Result<Vec<_>>>()?;
    Ok(Resolver::new(paths.iter().map(String::as_str)).module("", name))
}

fn select(conn: &Connection, filter: &str, value: &str) -> Result<Vec<Ref>> {
    conn.prepare(&format!("SELECT {COLUMNS} FROM links WHERE {filter}"))?
        .query_map([value], |row| {
            Ok(Ref {
                path: row.get(0)?,
                line: row.get(1)?,
                kind: row.get(2)?,
                target: row.get(3)?,
                resolved: row.get(4)?,
            })
        })?
        .collect()
}

/// Text: an `in` line and an `out` line, each with its links as `path:line kind target`. JSON:
/// one object with `in`, `out`, and `omitted`.
pub fn render(refs: &Refs, format: Format) -> String {
    let mut out = String::new();
    if format == Format::Json {
        let rows = |rows: &[Ref]| rows.iter().map(json_row).collect::<Vec<_>>().join(",");
        let (incoming, outgoing) = (rows(&refs.incoming), rows(&refs.outgoing));
        let omitted = refs.omitted;
        let _ = writeln!(
            out,
            "{{\"in\":[{incoming}],\"out\":[{outgoing}],\"omitted\":{omitted}}}"
        );
        return out;
    }
    if refs.incoming.is_empty() && refs.outgoing.is_empty() && refs.omitted == 0 {
        return out;
    }
    for (group, rows) in [("in", &refs.incoming), ("out", &refs.outgoing)] {
        let _ = writeln!(out, "{group}");
        for row in rows {
            let (path, target) = (plain(&row.path), plain(&row.target));
            let _ = writeln!(out, "{path}:{} {} {target}", row.line, row.kind);
        }
    }
    if refs.omitted > 0 {
        let _ = writeln!(
            out,
            "({} more results not printed. Use --limit.)",
            refs.omitted
        );
    }
    out
}

fn json_row(row: &Ref) -> String {
    format!(
        "{{\"path\":{},\"line\":{},\"kind\":{},\"target\":{},\"resolved\":{}}}",
        json_string(&row.path),
        row.line,
        json_string(&row.kind),
        json_string(&row.target),
        json_string(&row.resolved),
    )
}
