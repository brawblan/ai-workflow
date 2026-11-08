//! The `show` query: the lines of each symbol that `find` matches.

use std::collections::HashSet;
use std::fmt::Write;
use std::path::Path;

use rusqlite::{Connection, Result};

use crate::cli::{Format, Query};
use crate::query::{self, Row, json_row, json_string, plain};
use crate::update;

/// The lines of one symbol. `None` if the file changed since the index. `more` is the count of
/// the lines that `--max-lines` cut.
pub struct Block {
    row: Row,
    lines: Option<Vec<String>>,
    more: usize,
}

pub struct Blocks {
    pub blocks: Vec<Block>,
    pub omitted: usize,
}

/// The symbols that `find` returns, each with its lines from the file. A file with a content
/// hash that is not the hash of the index is stale, and the function reads none of its lines.
pub fn show(conn: &Connection, root: &Path, query: &Query) -> Result<Blocks> {
    let found = query::find(conn, &query.target, query.kind.as_deref(), query.limit)?;
    let mut blocks = Vec::new();
    for row in found.rows {
        let indexed = query::file_hash(conn, &row.path)?;
        let text = update::read_text(&root.join(&row.path))
            .filter(|bytes| indexed.as_deref() == Some(update::hash(bytes).as_str()))
            .map(|bytes| String::from_utf8_lossy(&bytes).into_owned());
        let (lines, more) = match text {
            Some(text) => cut(&text, &row, query.max_lines),
            None => (None, 0),
        };
        blocks.push(Block { row, lines, more });
    }
    Ok(Blocks {
        blocks,
        omitted: found.omitted,
    })
}

/// The lines of the symbol, at most `max` of them, and the count of the lines that it cut.
fn cut(text: &str, row: &Row, max: usize) -> (Option<Vec<String>>, usize) {
    let start = usize::try_from(row.line - 1).unwrap_or(0);
    let count = usize::try_from(row.end_line - row.line + 1).unwrap_or(1);
    let all: Vec<String> = text
        .lines()
        .skip(start)
        .take(count)
        .map(|line| line.replace('\t', "    "))
        .collect();
    let more = all.len().saturating_sub(max);
    let kept = all.into_iter().take(max).collect();
    (Some(kept), more)
}

/// Text: a header and the lines for each symbol, `stale: <path>` once for each stale file, and a
/// last line with the count of the symbols that the limit cut. JSON: one object with `results`
/// and `omitted`. Each result has `lines` (or null if stale) and `more`.
pub fn render(blocks: &Blocks, format: Format) -> String {
    let mut out = String::new();
    if format == Format::Json {
        let rows: Vec<String> = blocks.blocks.iter().map(json_block).collect();
        let _ = writeln!(
            out,
            "{{\"results\":[{}],\"omitted\":{}}}",
            rows.join(","),
            blocks.omitted
        );
        return out;
    }
    let mut stale = HashSet::new();
    for block in &blocks.blocks {
        let row = &block.row;
        let path = plain(&row.path);
        let Some(lines) = &block.lines else {
            if stale.insert(&row.path) {
                let _ = writeln!(out, "stale: {path}");
            }
            continue;
        };
        let (kind, name) = (&row.kind, plain(&row.qualified_name));
        let _ = writeln!(out, "{path}:{}-{} {kind} {name}", row.line, row.end_line);
        for line in lines {
            let _ = writeln!(out, "{}", plain(line));
        }
        if block.more > 0 {
            let from = row.end_line - i64::try_from(block.more).unwrap_or(0) + 1;
            let _ = writeln!(
                out,
                "... {} more lines ({path}:{from}-{})",
                block.more, row.end_line
            );
        }
    }
    if blocks.omitted > 0 {
        let _ = writeln!(
            out,
            "({} more results not printed. Use --limit.)",
            blocks.omitted
        );
    }
    out
}

fn json_block(block: &Block) -> String {
    let lines = block.lines.as_ref().map_or_else(
        || "null".to_string(),
        |lines| {
            let items: Vec<String> = lines.iter().map(|line| json_string(line)).collect();
            format!("[{}]", items.join(","))
        },
    );
    json_row(
        &block.row,
        &format!(",\"lines\":{lines},\"more\":{}", block.more),
    )
}
