//! Tests of `stone-index build`: the repo root, the index path, usage errors, and the repo
//! `.gitignore` line (AC 1, 12, 15).

mod common;

use std::fs;
use std::path::Path;

use common::{Fixture, stderr, stdout, summary};

#[test]
fn ac1_index_goes_to_repo_root_when_run_in_a_subfolder() {
    let fx = Fixture::new("root-sub");
    fx.git_dir();
    fx.write("top.md", b"# top\n");
    fx.write("a/b/deep.py", b"x = 1\n");
    let sub = fx.root.join("a").join("b");
    let out = fx.run_in(&sub, &["build"]);
    assert_eq!(summary(&out), (2, 0, 0));
    assert!(fx.default_db().is_file());
    assert!(!sub.join(".cornerstone").exists());
    assert_eq!(fx.paths(), vec!["a/b/deep.py", "top.md"]);
}

#[test]
fn ac1_git_file_as_in_a_worktree_marks_the_root() {
    let fx = Fixture::new("root-gitfile");
    fs::remove_dir_all(fx.root.join(".git")).unwrap();
    fs::write(fx.root.join(".git"), "gitdir: /nowhere\n").unwrap();
    fx.write("sub/f.py", b"x\n");
    let out = fx.run_in(&fx.root.join("sub"), &["build"]);
    assert_eq!(summary(&out), (1, 0, 0));
    assert!(fx.default_db().is_file());
    assert_eq!(fx.paths(), vec!["sub/f.py"]);
}

#[test]
fn ac1_no_git_puts_the_index_in_the_current_folder() {
    let fx = Fixture::new("root-nogit");
    if !fx.no_git() {
        eprintln!("skip: the temp folder is inside a git repo");
        return;
    }
    fx.write("a.md", b"a\n");
    fx.write("sub/b.md", b"b\n");
    let out = fx.run_in(&fx.root.join("sub"), &["build"]);
    assert_eq!(summary(&out), (1, 0, 0));
    assert!(fx.root.join("sub/.cornerstone/index.db").is_file());
    assert!(!fx.default_db().exists());
}

#[test]
fn ac1_db_option_sets_the_path_from_the_current_folder() {
    let fx = Fixture::new("root-db");
    fx.git_dir();
    fx.write("sub/a.md", b"a\n");
    let sub = fx.root.join("sub");
    let out = fx.run_in(&sub, &["build", "--db", "out/deeper/x.db"]);
    assert_eq!(summary(&out), (1, 0, 0));
    assert!(sub.join("out/deeper/x.db").is_file());
    assert!(!fx.default_db().exists());
    assert!(!sub.join(".cornerstone").exists());
    assert!(!fx.root.join(".cornerstone").exists());
}

#[test]
fn ac12_usage_errors_exit_2_with_stderr_and_no_stdout() {
    let fx = Fixture::new("usage");
    fx.write("a.md", b"a\n");
    let cases: [&[&str]; 6] = [
        &["build", "--bogus"],
        &["build", "--db"],
        &["build", "--max-file-size"],
        &["build", "--max-file-size", "abc"],
        &["bogus"],
        &[],
    ];
    for args in cases {
        let out = fx.run_in(&fx.root, args);
        assert_eq!(out.status.code(), Some(2), "args {args:?}");
        assert!(!stderr(&out).is_empty(), "args {args:?}");
        assert_eq!(stdout(&out), "", "args {args:?}");
    }
    assert!(!fx.root.join(".cornerstone").exists());
}

#[test]
fn ac12_file_that_is_not_a_database_is_a_broken_index() {
    let fx = Fixture::new("broken");
    fx.git_dir();
    fx.write("a.md", b"a\n");
    let db = fx.default_db();
    fs::create_dir_all(db.parent().unwrap()).unwrap();
    fs::write(
        &db,
        "this is plain text and not a SQLite database at all. ".repeat(10),
    )
    .unwrap();
    let out = fx.build(&[]);
    assert_eq!(out.status.code(), Some(2));
    assert!(stderr(&out).contains("broken index"), "{}", stderr(&out));
    assert_eq!(stdout(&out), "");
}

#[test]
fn ac12_successful_build_exits_0_with_empty_stderr() {
    let fx = Fixture::new("ok");
    fx.write("a.md", b"a\n");
    let out = fx.build(&[]);
    assert_eq!(out.status.code(), Some(0));
    assert_eq!(stderr(&out), "");
}

#[test]
fn ac15_repo_gitignore_has_the_index_line() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../.gitignore");
    let text = fs::read_to_string(path).unwrap();
    assert!(
        text.lines()
            .any(|line| line.trim() == ".cornerstone/index.db*")
    );
}

#[test]
fn ac15_the_index_files_are_not_indexed() {
    let fx = Fixture::new("self-skip");
    fx.write("a.md", b"a\n");
    summary(&fx.build(&[]));
    summary(&fx.build(&[]));
    let paths = fx.paths();
    assert_eq!(paths, vec!["a.md"]);
    assert!(
        paths
            .iter()
            .all(|p| !p.starts_with(".cornerstone/index.db"))
    );
}

#[test]
fn ac12_foreign_database_is_a_broken_index_and_is_kept() {
    let fx = Fixture::new("foreign");
    fx.write("a.md", b"a\n");
    let db = fx.root.join("other.db");
    let conn = rusqlite::Connection::open(&db).unwrap();
    conn.execute("CREATE TABLE users (name TEXT)", []).unwrap();
    conn.execute("INSERT INTO users VALUES ('ann')", [])
        .unwrap();
    drop(conn);
    let out = fx.build(&["--db", "other.db"]);
    assert_eq!(out.status.code(), Some(2));
    assert!(stderr(&out).contains("broken index"), "{}", stderr(&out));
    let conn = rusqlite::Connection::open(&db).unwrap();
    let count: i64 = conn
        .query_row("SELECT count(*) FROM users", [], |r| r.get(0))
        .unwrap();
    assert_eq!(count, 1);
}
