//! Shared helpers: a temporary fixture repo, a child process runner, and index readers.
#![allow(dead_code)]

use std::fs::{self, File};
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, UNIX_EPOCH};

use rusqlite::Connection;

pub const BIN: &str = env!("CARGO_BIN_EXE_stone-index");
pub const OLD_MTIME: u64 = 1_700_000_000;

static COUNTER: AtomicUsize = AtomicUsize::new(0);

/// A temporary folder with a `repo` folder and a `home` folder. Drop removes both.
pub struct Fixture {
    base: PathBuf,
    pub root: PathBuf,
    pub home: PathBuf,
}

impl Fixture {
    pub fn new(name: &str) -> Fixture {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let base = std::env::temp_dir().join(format!("si-{}-{n}-{name}", std::process::id()));
        let _ = fs::remove_dir_all(&base);
        let root = base.join("repo");
        let home = base.join("home");
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(home.join("xdg").join("git")).unwrap();
        fs::create_dir_all(root.join(".git")).unwrap();
        Fixture { base, root, home }
    }

    /// Writes a file under the root with a fixed old modified time.
    pub fn write(&self, rel: &str, content: &[u8]) {
        let path = self.root.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, content).unwrap();
        self.set_mtime(rel, OLD_MTIME);
    }

    pub fn set_mtime(&self, rel: &str, secs: u64) {
        let file = File::options()
            .write(true)
            .open(self.root.join(rel))
            .unwrap();
        file.set_modified(UNIX_EPOCH + Duration::from_secs(secs))
            .unwrap();
    }

    pub fn remove(&self, rel: &str) {
        fs::remove_file(self.root.join(rel)).unwrap();
    }

    /// Removes the default `.git` folder. Returns false if a folder above the fixture has `.git`.
    pub fn no_git(&self) -> bool {
        fs::remove_dir_all(self.root.join(".git")).unwrap();
        self.root.ancestors().all(|dir| !dir.join(".git").exists())
    }

    pub fn git_dir(&self) {
        fs::create_dir_all(self.root.join(".git")).unwrap();
    }

    pub fn global_ignore(&self, text: &str) {
        fs::write(self.home.join("xdg").join("git").join("ignore"), text).unwrap();
    }

    pub fn command(&self, cwd: &Path, args: &[&str]) -> Command {
        let mut command = Command::new(BIN);
        command
            .args(args)
            .current_dir(cwd)
            .env("HOME", &self.home)
            .env("XDG_CONFIG_HOME", self.home.join("xdg"));
        command
    }

    pub fn run_in(&self, cwd: &Path, args: &[&str]) -> Output {
        self.command(cwd, args)
            .output()
            .expect("stone-index must start")
    }

    /// Runs `stone-index build` with extra arguments in the root.
    pub fn build(&self, extra: &[&str]) -> Output {
        let mut args = vec!["build"];
        args.extend_from_slice(extra);
        self.run_in(&self.root, &args)
    }

    pub fn default_db(&self) -> PathBuf {
        self.root.join(".cornerstone").join("index.db")
    }

    pub fn conn(&self) -> Connection {
        Connection::open(self.default_db()).unwrap()
    }

    pub fn paths(&self) -> Vec<String> {
        let conn = self.conn();
        let mut statement = conn
            .prepare("SELECT path FROM files ORDER BY path")
            .unwrap();
        statement
            .query_map([], |row| row.get(0))
            .unwrap()
            .map(Result::unwrap)
            .collect()
    }

    pub fn hash(&self, rel: &str) -> String {
        self.conn()
            .query_row("SELECT hash FROM files WHERE path = ?1", [rel], |row| {
                row.get(0)
            })
            .unwrap()
    }

    pub fn mtime_ns(&self, rel: &str) -> i64 {
        self.conn()
            .query_row("SELECT mtime_ns FROM files WHERE path = ?1", [rel], |row| {
                row.get(0)
            })
            .unwrap()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.base);
    }
}

pub fn stdout(out: &Output) -> String {
    String::from_utf8_lossy(&out.stdout).into_owned()
}

pub fn stderr(out: &Output) -> String {
    String::from_utf8_lossy(&out.stderr).into_owned()
}

/// Checks that the build worked and prints exactly one summary line. Returns the three counts.
pub fn summary(out: &Output) -> (usize, usize, usize) {
    assert_eq!(out.status.code(), Some(0), "stderr: {}", stderr(out));
    let text = stdout(out);
    let line = text.strip_suffix('\n').expect("stdout ends with a newline");
    assert!(!line.contains('\n'), "more than one line: {text:?}");
    let words: Vec<&str> = line.split(' ').collect();
    assert_eq!(words.len(), 8, "bad summary: {line:?}");
    assert_eq!(&words[1], &"parsed,");
    assert_eq!(&words[3], &"unchanged,");
    assert_eq!(&words[5], &"removed");
    assert_eq!(&words[6], &"in");
    let seconds = words[7].strip_suffix('s').expect("seconds end with s");
    let (whole, fraction) = seconds.split_once('.').expect("seconds have a dot");
    assert!(!whole.is_empty() && whole.bytes().all(|b| b.is_ascii_digit()));
    assert!(fraction.len() == 2 && fraction.bytes().all(|b| b.is_ascii_digit()));
    let count = |word: &str, suffix: &str| -> usize {
        word.strip_suffix(suffix)
            .unwrap_or(word)
            .parse()
            .expect("count is a number")
    };
    (
        count(words[0], ""),
        count(words[2], ""),
        count(words[4], ""),
    )
}
