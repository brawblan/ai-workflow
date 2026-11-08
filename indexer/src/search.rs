//! The `search` query: the blocks of text with the best FTS5 bm25 rank for some words.

use std::collections::HashMap;
use std::fmt::Write;
use std::path::Path;

use rusqlite::{Connection, Result, params};

use crate::cli::Format;
use crate::query::{json_string, plain};
use crate::sql;
use crate::update::{self, CHUNK_LINES};

/// One hit: the first line of a block that has the most of the words. With `--context`, a hit is a
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

/// The words of a text, as FTS5 splits it: each run of letters and digits.
pub fn words(text: &str) -> Vec<String> {
    text.split(|character: char| !character.is_alphanumeric())
        .filter(|word| !word.is_empty())
        .map(str::to_lowercase)
        .collect()
}

/// The terms of a query. A run of words in double quotes is one term, a phrase. Each other word
/// is a term. A term is a list of words: one word, or the words of a phrase in order. An open
/// quote runs to the end of the query.
pub fn terms(query: &str) -> Vec<Vec<String>> {
    let mut terms = Vec::new();
    for (index, part) in query.split('"').enumerate() {
        let found = words(part);
        if index % 2 == 1 {
            if !found.is_empty() {
                terms.push(found);
            }
        } else {
            terms.extend(found.into_iter().map(|word| vec![word]));
        }
    }
    terms
}

/// The blocks that have all the `terms`, or at least one with `any`, the best bm25 rank first. `glob` limits the
/// paths, with the SQLite `GLOB` rules. The index has no text, so the function reads each file
/// under `root`. It skips a hit in a file whose content hash is not the hash of the index, and
/// a block with no line that has a word. With `context` above 0, each hit has that many lines
/// before and after it, and the ranges that touch or overlap in one file are one hit.
pub fn search(
    conn: &Connection,
    root: &Path,
    terms: &[Vec<String>],
    any: bool,
    glob: Option<&str>,
    limit: usize,
    context: usize,
) -> Result<Hits> {
    let tx = conn.unchecked_transaction()?;
    let quoted: Vec<String> = terms
        .iter()
        .map(|term| format!("\"{}\"", term.join(" ")))
        .collect();
    let terms_text = quoted.join(if any { " OR " } else { " AND " });
    let total: i64 = tx.query_row(sql::SEARCH_COUNT, params![terms_text, glob], |row| {
        row.get(0)
    })?;
    let limit_value = i64::try_from(limit).unwrap_or(i64::MAX);
    let blocks = tx
        .prepare(sql::SEARCH_ROWS)?
        .query_map(params![terms_text, glob, limit_value], |row| {
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
            let (offset, text) = best_line(&block, terms)?;
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

/// How many of the `terms` a line has. A phrase counts if its words are in the line in order.
fn score(line: &str, terms: &[Vec<String>]) -> usize {
    let found = words(line);
    terms
        .iter()
        .filter(|term| {
            found
                .windows(term.len())
                .any(|window| window == term.as_slice())
        })
        .count()
}

/// The offset and the text of the line of a block with the most of the `terms`, the first one if
/// two lines have the same number. The text has no space at the ends and a space for each tab.
/// If a phrase runs over a line break, a line with one word of it is the hit line. `None` if no
/// line has a word.
fn best_line(lines: &[&str], terms: &[Vec<String>]) -> Option<(i64, String)> {
    let mut best: Option<(usize, usize)> = None;
    for (index, line) in lines.iter().enumerate() {
        let count = score(line, terms);
        if count > 0 && best.is_none_or(|(_, top)| count > top) {
            best = Some((index, count));
        }
    }
    if best.is_none() {
        // A phrase can run over a line break: no line has all its words, but FTS5 matched it.
        let flat: Vec<Vec<String>> = terms
            .iter()
            .flatten()
            .map(|word| vec![word.clone()])
            .collect();
        best = lines
            .iter()
            .position(|line| score(line, &flat) > 0)
            .map(|index| (index, 1));
    }
    let (index, _) = best?;
    let offset = i64::try_from(index).unwrap_or(0);
    Some((offset, lines[index].trim().replace('\t', " ")))
}

/// Text: one line for each hit, as `path:line: text`, in `max_bytes` bytes at most. A hit that
/// does not fit, and each hit after it, is not printed. JSON: one object with `results` and
/// `omitted`, with no byte cap.
pub fn render(hits: &Hits, format: Format, max_bytes: usize) -> String {
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
    let mut printed = 0;
    for (index, hit) in hits.rows.iter().enumerate() {
        let text = render_hit(hit, index > 0);
        if out.len() + text.len() > max_bytes {
            break;
        }
        out.push_str(&text);
        printed += 1;
    }
    let cut = hits.rows.len() - printed;
    let more = hits.omitted + cut;
    if more > 0 {
        let advice = if cut > 0 {
            "--limit or --max-bytes"
        } else {
            "--limit"
        };
        let _ = writeln!(out, "({more} more results not printed. Use {advice}.)");
    }
    out
}

/// The text lines of one hit. A hit with context starts with a line `--` if it is not the first.
fn render_hit(hit: &Hit, separate: bool) -> String {
    let mut out = String::new();
    if hit.lines.is_empty() {
        let (path, text) = (plain(&hit.path), plain(&hit.text));
        let _ = writeln!(out, "{path}:{}: {text}", hit.line);
        return out;
    }
    if separate {
        out.push_str("--\n");
    }
    for (number, text, is_hit) in &hit.lines {
        let sign = if *is_hit { ':' } else { '-' };
        let (path, text) = (plain(&hit.path), plain(text));
        let _ = writeln!(out, "{path}{sign}{number}{sign} {text}");
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
