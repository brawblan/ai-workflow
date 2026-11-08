//! The `find` and `outline` queries, and their text and JSON output.

use std::collections::HashMap;
use std::fmt::Write;

use rusqlite::{Connection, OptionalExtension, Result, Row as SqlRow, params};

use crate::cli::Format;
use crate::sql;

/// One symbol in the output. `depth` is set only for `outline`.
pub struct Row {
    pub path: String,
    pub line: i64,
    pub end_line: i64,
    pub kind: String,
    pub name: String,
    pub qualified_name: String,
    level: Option<i64>,
    depth: Option<usize>,
}

/// The rows to print, and the count of the rows that the limit cut.
pub struct Results {
    pub rows: Vec<Row>,
    pub omitted: usize,
}

/// The symbols whose qualified name or name (the last part) is `name`, in path and line order.
/// The name of a heading is its text.
pub fn find(conn: &Connection, name: &str, kind: Option<&str>, limit: usize) -> Result<Results> {
    // One read transaction, so the count and the rows come from the same state of the index.
    let tx = conn.unchecked_transaction()?;
    let total: i64 = tx.query_row(sql::FIND_COUNT, params![name, kind], |row| row.get(0))?;
    let rows = tx
        .prepare(sql::FIND_ROWS)?
        .query_map(
            params![name, kind, i64::try_from(limit).unwrap_or(i64::MAX)],
            |row| read_row(row).map(|(row, _, _)| row),
        )?
        .collect::<Result<Vec<_>>>()?;
    let omitted = usize::try_from(total)
        .unwrap_or(0)
        .saturating_sub(rows.len());
    Ok(Results { rows, omitted })
}

/// The content hash of the file at `path` in the index, if it has a row.
pub fn file_hash(conn: &Connection, path: &str) -> Result<Option<String>> {
    conn.query_row(sql::FILE_HASH, [path], |row| row.get(0))
        .optional()
}

/// True if the index has a row for the file at `path`.
pub fn is_indexed(conn: &Connection, path: &str) -> Result<bool> {
    conn.query_row(sql::IS_INDEXED, [path], |row| row.get(0))
}

/// The symbols of one file in line order. A code symbol is one level deeper than its parent. A
/// heading has the depth of its level, from 0.
pub fn outline(conn: &Connection, path: &str, limit: usize) -> Result<Results> {
    let all = conn
        .prepare(sql::OUTLINE)?
        .query_map([path], read_row)?
        .collect::<Result<Vec<_>>>()?;
    let mut depths: HashMap<i64, usize> = HashMap::new();
    let mut rows = Vec::new();
    for (mut row, id, parent) in all {
        let depth = match row.level {
            Some(level) => usize::try_from(level - 1).unwrap_or(0),
            None => parent
                .and_then(|parent| depths.get(&parent))
                .map_or(0, |depth| depth + 1),
        };
        depths.insert(id, depth);
        row.depth = Some(depth);
        rows.push(row);
    }
    let omitted = rows.len().saturating_sub(limit);
    rows.truncate(limit);
    Ok(Results { rows, omitted })
}

fn read_row(row: &SqlRow) -> Result<(Row, i64, Option<i64>)> {
    let symbol = Row {
        path: row.get(0)?,
        line: row.get(1)?,
        end_line: row.get(2)?,
        kind: row.get(3)?,
        name: row.get(4)?,
        qualified_name: row.get(5)?,
        level: row.get(6)?,
        depth: None,
    };
    Ok((symbol, row.get(7)?, row.get(8)?))
}

/// The output of a query. Text: one line for each row, and a last line with the count of the
/// rows that the limit cut. JSON: one object with `results` and `omitted`.
pub fn render(results: &Results, format: Format) -> String {
    let mut out = String::new();
    match format {
        Format::Text => {
            for row in &results.rows {
                let _ = match row.depth {
                    Some(depth) => {
                        let indent = "  ".repeat(depth);
                        writeln!(
                            out,
                            "{indent}{} {} {}",
                            row.line,
                            row.kind,
                            plain(&row.name)
                        )
                    }
                    None => writeln!(
                        out,
                        "{}:{} {} {}",
                        plain(&row.path),
                        row.line,
                        row.kind,
                        plain(&row.qualified_name)
                    ),
                };
            }
            if results.omitted > 0 {
                let _ = writeln!(
                    out,
                    "({} more results not printed. Use --limit.)",
                    results.omitted
                );
            }
        }
        Format::Json => {
            let rows: Vec<String> = results.rows.iter().map(|row| json_row(row, "")).collect();
            let _ = writeln!(
                out,
                "{{\"results\":[{}],\"omitted\":{}}}",
                rows.join(","),
                results.omitted
            );
        }
    }
    out
}

/// The text with each control character as `?`, so file content cannot send terminal escape
/// sequences.
pub fn plain(text: &str) -> String {
    text.chars()
        .map(|character| {
            if character.is_control() {
                '?'
            } else {
                character
            }
        })
        .collect()
}

/// The JSON object of a row. `extra` is more members, with a first comma, or empty.
pub fn json_row(row: &Row, extra: &str) -> String {
    let optional = |value: Option<String>| value.unwrap_or_else(|| "null".to_string());
    let mut text = format!(
        "{{\"path\":{},\"line\":{},\"end_line\":{},\"kind\":{},\"name\":{},\"qualified_name\":{},\"level\":{}",
        json_string(&row.path),
        row.line,
        row.end_line,
        json_string(&row.kind),
        json_string(&row.name),
        json_string(&row.qualified_name),
        optional(row.level.map(|level| level.to_string())),
    );
    if let Some(depth) = row.depth {
        let _ = write!(text, ",\"depth\":{depth}");
    }
    text.push_str(extra);
    text.push('}');
    text
}

pub fn json_string(text: &str) -> String {
    let mut out = String::from("\"");
    for character in text.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            control if control < ' ' => {
                let _ = write!(out, "\\u{:04x}", u32::from(control));
            }
            other => out.push(other),
        }
    }
    out.push('"');
    out
}
