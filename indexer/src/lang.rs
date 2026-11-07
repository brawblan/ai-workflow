//! The language of a file, from its extension.

use std::path::Path;

/// The language name that the index stores, or `None` if the indexer does not parse the file.
pub fn language(path: &str) -> Option<&'static str> {
    let extension = Path::new(path).extension()?.to_str()?.to_ascii_lowercase();
    let name = match extension.as_str() {
        "py" | "pyi" => "python",
        "md" | "markdown" => "markdown",
        "ts" | "mts" | "cts" => "typescript",
        "tsx" => "tsx",
        "js" | "mjs" | "cjs" => "javascript",
        "jsx" => "jsx",
        _ => return None,
    };
    Some(name)
}
