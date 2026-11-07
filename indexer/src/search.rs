//! The `search` query: the blocks of text with the best FTS5 bm25 rank for some words.

use std::fmt::Write;

use rusqlite::{Connection, Result, params};

use crate::cli::Format;
use crate::query::{json_string, plain};

/// One hit: the first line of a block that has one of the words.
pub struct Hit {
    path: String,
    line: i64,
    text: String,
}

pub struct Hits {
    pub rows: Vec<Hit>,
    pub omitted: usize,
}

/// The words of a search, as FTS5 splits text: each run of letters and digits.
pub fn words(text: &str) -> Vec<String> {
    text.split(|character: char| !character.is_alphanumeric())
        .filter(|word| !word.is_empty())
        .map(str::to_lowercase)
        .collect()
}

/// The blocks that have at least one of `words`, the best bm25 rank first. `glob` limits the
/// paths, with the SQLite `GLOB` rules.
pub fn search(
    conn: &Connection,
    words: &[String],
    glob: Option<&str>,
    limit: usize,
) -> Result<Hits> {
    let tx = conn.unchecked_transaction()?;
    let quoted: Vec<String> = words.iter().map(|word| format!("\"{word}\"")).collect();
    let terms = quoted.join(" OR ");
    let from = "FROM chunks JOIN chunk_rows AS block ON block.id = chunks.rowid
         WHERE chunks MATCH ?1 AND (?2 IS NULL OR block.path GLOB ?2)";
    let total: i64 = tx.query_row(
        &format!("SELECT count(*) {from}"),
        params![terms, glob],
        |row| row.get(0),
    )?;
    let sql = format!(
        "SELECT block.path, block.line, block.text {from}
         ORDER BY bm25(chunks), block.path, block.line LIMIT ?3"
    );
    let limit_value = i64::try_from(limit).unwrap_or(i64::MAX);
    let rows = tx
        .prepare(&sql)?
        .query_map(params![terms, glob, limit_value], |row| {
            let text: String = row.get(2)?;
            let (offset, line) = first_match(&text, words);
            Ok(Hit {
                path: row.get(0)?,
                line: row.get::<_, i64>(1)? + offset,
                text: line,
            })
        })?
        .collect::<Result<Vec<_>>>()?;
    let omitted = usize::try_from(total)
        .unwrap_or(0)
        .saturating_sub(rows.len());
    Ok(Hits { rows, omitted })
}

/// The offset and the text of the first line of a block with one of the words, with no space at
/// the ends and a space for each tab. The words are in lower case.
fn first_match(block: &str, words: &[String]) -> (i64, String) {
    let lines: Vec<&str> = block.split('\n').collect();
    let index = lines
        .iter()
        .position(|line| {
            let line = line.to_lowercase();
            words.iter().any(|word| line.contains(word.as_str()))
        })
        .unwrap_or(0);
    let offset = i64::try_from(index).unwrap_or(0);
    let line = lines.get(index).copied().unwrap_or("");
    (offset, line.trim().replace('\t', " "))
}

/// Text: one line for each hit, as `path:line: text`. JSON: one object with `results` and
/// `omitted`.
pub fn render(hits: &Hits, format: Format) -> String {
    let mut out = String::new();
    if format == Format::Json {
        let rows: Vec<String> = hits
            .rows
            .iter()
            .map(|hit| {
                let (path, text) = (json_string(&hit.path), json_string(&hit.text));
                format!("{{\"path\":{path},\"line\":{},\"text\":{text}}}", hit.line)
            })
            .collect();
        let _ = writeln!(
            out,
            "{{\"results\":[{}],\"omitted\":{}}}",
            rows.join(","),
            hits.omitted
        );
        return out;
    }
    for hit in &hits.rows {
        let _ = writeln!(
            out,
            "{}:{}: {}",
            plain(&hit.path),
            hit.line,
            plain(&hit.text)
        );
    }
    if hits.omitted > 0 {
        let _ = writeln!(
            out,
            "({} more results not printed. Use --limit.)",
            hits.omitted
        );
    }
    out
}
