//! The language of a file, from its extension.

use std::path::Path;

/// The language names that `--lang` accepts.
pub const NAMES: &[&str] = &[
    "python",
    "markdown",
    "typescript",
    "tsx",
    "javascript",
    "jsx",
    "c",
    "cpp",
    "csharp",
    "rust",
];

/// A `--lang EXT=LANG` setting: a file extension in lower case, and the language that it gets.
pub type Override = (String, &'static str);

/// The language name that the index stores, or `None` if the indexer does not parse the file.
/// An override replaces the language of its extension.
pub fn language_with(path: &str, overrides: &[Override]) -> Option<&'static str> {
    let extension = Path::new(path).extension()?.to_str()?.to_ascii_lowercase();
    if let Some((_, name)) = overrides.iter().find(|(ext, _)| *ext == extension) {
        return Some(name);
    }
    let name = match extension.as_str() {
        "py" | "pyi" => "python",
        "md" | "markdown" => "markdown",
        "ts" | "mts" | "cts" => "typescript",
        "tsx" => "tsx",
        "js" | "mjs" | "cjs" => "javascript",
        "jsx" => "jsx",
        "c" => "c",
        "cc" | "cpp" | "cxx" | "hpp" | "hh" | "hxx" | "h" => "cpp",
        "cs" => "csharp",
        "rs" => "rust",
        _ => return None,
    };
    Some(name)
}

/// Reads `EXT=LANG`, for example `h=c`.
pub fn parse_override(text: &str) -> Result<Override, String> {
    let bad = || {
        format!(
            "--lang needs EXT=LANG, with LANG one of {}: {text:?}",
            NAMES.join(", ")
        )
    };
    let (extension, name) = text.split_once('=').ok_or_else(bad)?;
    let name = NAMES.iter().find(|known| **known == name).ok_or_else(bad)?;
    let extension = extension.trim_start_matches('.').to_ascii_lowercase();
    if extension.is_empty() {
        return Err(bad());
    }
    Ok((extension, name))
}
