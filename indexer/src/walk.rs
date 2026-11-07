//! The repo root, and the walk over the files that the index can hold.

use std::fs::Metadata;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use ignore::WalkBuilder;

/// A file that the walk found, with the facts that tell if it changed.
pub struct Candidate {
    /// The path from the repo root, with `/` between the parts.
    pub path: String,
    pub abs: PathBuf,
    pub size: i64,
    pub mtime_ns: i64,
}

/// The folder with `.git` (a folder or a worktree file), or `start` if no folder has it.
pub fn repo_root(start: &Path) -> PathBuf {
    start
        .ancestors()
        .find(|dir| dir.join(".git").exists())
        .unwrap_or(start)
        .to_path_buf()
}

/// Each regular file under `root` that the git ignore rules keep, not larger than `max_size`.
/// It also skips `.git` and the paths in `skip`.
pub fn files(root: &Path, max_size: u64, skip: &[PathBuf]) -> Vec<Candidate> {
    let walker = WalkBuilder::new(root)
        .hidden(false)
        .require_git(false)
        .filter_entry(|entry| entry.file_name() != ".git")
        .build();
    walker
        .filter_map(Result::ok)
        .filter(|entry| entry.file_type().is_some_and(|kind| kind.is_file()))
        .filter(|entry| !skip.iter().any(|path| path == entry.path()))
        .filter_map(|entry| {
            let metadata = entry.metadata().ok()?;
            if metadata.len() > max_size {
                return None;
            }
            candidate(root, entry.path(), &metadata)
        })
        .collect()
}

fn candidate(root: &Path, abs: &Path, metadata: &Metadata) -> Option<Candidate> {
    let relative = abs.strip_prefix(root).ok()?;
    let parts: Vec<_> = relative
        .components()
        .map(|part| part.as_os_str().to_string_lossy())
        .collect();
    Some(Candidate {
        path: parts.join("/"),
        abs: abs.to_path_buf(),
        size: i64::try_from(metadata.len()).ok()?,
        mtime_ns: mtime_ns(metadata),
    })
}

fn mtime_ns(metadata: &Metadata) -> i64 {
    metadata
        .modified()
        .ok()
        .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
        .map_or(0, |age| i64::try_from(age.as_nanos()).unwrap_or(i64::MAX))
}
