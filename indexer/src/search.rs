//! The `search` query: the blocks of text with the best FTS5 bm25 rank for some words.

use std::collections::HashMap;
use std::fmt::Write;
use std::path::Path;

use rusqlite::{Connection, Result, params};

use crate::cli::Format;
use crate::query::{json_string, plain};
use crate::sql;
use crate::update::{self, CHUNK_LINES};

/// One hit: the first line of a block that has one of the words. With `--context`, a hit is a
/// range of lines: `lines` has each line with its number, and true for a line with a word.
pub struct Hit {
    path: String,
    line: i64,
    text: String,
    lines: Vec<(i64, String, bool)>,
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
/// paths, with the SQLite `GLOB` rules. The index has no text, so the function reads each file
/// under `root`. It skips a hit in a file whose content hash is not the hash of the index, and
/// a block with no line that has a word. With `context` above 0, each hit has that many lines
/// before and after it, and the ranges that touch or overlap in one file are one hit.
pub fn search(
    conn: &Connection,
    root: &Path,
    words: &[String],
    glob: Option<&str>,
    limit: usize,
    context: usize,
) -> Result<Hits> {
    let tx = conn.unchecked_transaction()?;
    let quoted: Vec<String> = words.iter().map(|word| format!("\"{word}\"")).collect();
    let terms = quoted.join(" OR ");
    let total: i64 = tx.query_row(sql::SEARCH_COUNT, params![terms, glob], |row| row.get(0))?;
    let limit_value = i64::try_from(limit).unwrap_or(i64::MAX);
    let blocks = tx
        .prepare(sql::SEARCH_ROWS)?
        .query_map(params![terms, glob, limit_value], |row| {
            Ok((row.get(0)?, row.get(1)?, row.get(2)?))
        })?
        .collect::<Result<Vec<(String, i64, String)>>>()?;
    let rows: Vec<Hit> = blocks
        .into_iter()
        .filter_map(|(path, line, hash)| {
            let bytes = update::read_text(&root.join(&path))?;
            if update::hash(&bytes) != hash {
                return None;
            }
            let text = String::from_utf8_lossy(&bytes);
            let start = usize::try_from(line - 1).ok()?;
            let block: Vec<&str> = text.lines().skip(start).take(CHUNK_LINES).collect();
            let (offset, text) = first_match(&block, words)?;
            let line = line + offset;
            Some(Hit {
                path,
                line,
                text,
                lines: Vec::new(),
            })
        })
        .collect();
    let omitted = usize::try_from(total)
        .unwrap_or(0)
        .saturating_sub(rows.len());
    let rows = if context > 0 {
        expand(rows, root, context)
    } else {
        rows
    };
    Ok(Hits { rows, omitted })
}

/// Replaces each hit with a range of `context` lines before and after it. The ranges of one
/// file that touch or overlap are one hit. The order of the files is the order of the best hit.
fn expand(rows: Vec<Hit>, root: &Path, context: usize) -> Vec<Hit> {
    let mut order: Vec<String> = Vec::new();
    let mut by_path: HashMap<String, Vec<i64>> = HashMap::new();
    for hit in rows {
        if !by_path.contains_key(&hit.path) {
            order.push(hit.path.clone());
        }
        by_path.entry(hit.path).or_default().push(hit.line);
    }
    let context = i64::try_from(context).unwrap_or(i64::MAX / 4);
    let mut out = Vec::new();
    for path in order {
        let Some(bytes) = update::read_text(&root.join(&path)) else {
            continue;
        };
        let text = String::from_utf8_lossy(&bytes);
        let file: Vec<&str> = text.lines().collect();
        let last = i64::try_from(file.len()).unwrap_or(i64::MAX);
        let mut hit_lines = by_path.remove(&path).unwrap_or_default();
        hit_lines.sort_unstable();
        let mut ranges: Vec<(i64, i64)> = Vec::new();
        for &line in &hit_lines {
            let (start, end) = ((line - context).max(1), (line + context).min(last));
            match ranges.last_mut() {
                Some(range) if start <= range.1 + 1 => range.1 = range.1.max(end),
                _ => ranges.push((start, end)),
            }
        }
        for (start, end) in ranges {
            let lines: Vec<(i64, String, bool)> = (start..=end)
                .filter_map(|number| {
                    let index = usize::try_from(number - 1).ok()?;
                    let text = file.get(index)?.trim_end().replace('\t', "    ");
                    Some((number, text, hit_lines.binary_search(&number).is_ok()))
                })
                .collect();
            let first = hit_lines.iter().find(|line| (start..=end).contains(line));
            let line = first.copied().unwrap_or(start);
            let text = lines
                .iter()
                .find(|(number, _, _)| *number == line)
                .map_or_else(String::new, |(_, text, _)| text.trim().to_string());
            out.push(Hit {
                path: path.clone(),
                line,
                text,
                lines,
            });
        }
    }
    out
}

/// The offset and the text of the first line of a block with one of the words as a word, with
/// no space at the ends and a space for each tab. `None` if no line has one.
fn first_match(lines: &[&str], words: &[String]) -> Option<(i64, String)> {
    let index = lines
        .iter()
        .position(|line| self::words(line).iter().any(|word| words.contains(word)))?;
    let offset = i64::try_from(index).unwrap_or(0);
    Some((offset, lines[index].trim().replace('\t', " ")))
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
                let lines = json_lines(hit);
                format!(
                    "{{\"path\":{path},\"line\":{},\"text\":{text}{lines}}}",
                    hit.line
                )
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
    let mut previous: Option<&str> = None;
    for hit in &hits.rows {
        if hit.lines.is_empty() {
            let (path, text) = (plain(&hit.path), plain(&hit.text));
            let _ = writeln!(out, "{path}:{}: {text}", hit.line);
            continue;
        }
        if previous.is_some() {
            out.push_str("--\n");
        }
        previous = Some(&hit.path);
        for (number, text, is_hit) in &hit.lines {
            let sign = if *is_hit { ':' } else { '-' };
            let (path, text) = (plain(&hit.path), plain(text));
            let _ = writeln!(out, "{path}{sign}{number}{sign} {text}");
        }
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

/// The `lines` member of a hit with context, with a first comma. Empty if the hit has no context.
fn json_lines(hit: &Hit) -> String {
    if hit.lines.is_empty() {
        return String::new();
    }
    let lines: Vec<String> = hit
        .lines
        .iter()
        .map(|(number, text, is_hit)| {
            format!(
                "{{\"line\":{number},\"text\":{},\"hit\":{is_hit}}}",
                json_string(text)
            )
        })
        .collect();
    format!(",\"lines\":[{}]", lines.join(","))
}
