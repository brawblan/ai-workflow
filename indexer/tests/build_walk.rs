//! Tests of which files `stone-index build` indexes (AC 2).

mod common;

use common::{Fixture, summary};

const MAX: usize = 1_048_576;

fn built_paths(fx: &Fixture) -> Vec<String> {
    summary(&fx.build(&[]));
    fx.paths()
}

#[test]
fn ac2_gitignore_applies_with_a_git_folder() {
    let fx = Fixture::new("gi-git");
    fx.git_dir();
    fx.write(".gitignore", b"ignored.md\nbuild/\n");
    fx.write("ignored.md", b"x\n");
    fx.write("build/out.md", b"x\n");
    fx.write("kept.md", b"x\n");
    assert_eq!(built_paths(&fx), vec![".gitignore", "kept.md"]);
}

#[test]
fn ac2_gitignore_applies_with_no_git_folder() {
    let fx = Fixture::new("gi-nogit");
    fx.write(".gitignore", b"ignored.md\n");
    fx.write("ignored.md", b"x\n");
    fx.write("kept.md", b"x\n");
    assert_eq!(built_paths(&fx), vec![".gitignore", "kept.md"]);
}

#[test]
fn ac2_git_info_exclude_applies() {
    let fx = Fixture::new("exclude");
    fx.git_dir();
    fx.write(".git/info/exclude", b"secret.md\n");
    fx.write("secret.md", b"x\n");
    fx.write("kept.md", b"x\n");
    assert_eq!(built_paths(&fx), vec!["kept.md"]);
}

#[test]
fn ac2_global_git_ignore_applies() {
    let fx = Fixture::new("global");
    fx.git_dir();
    fx.global_ignore("*.global-ignored\n");
    fx.write("a.global-ignored", b"x\n");
    fx.write("kept.md", b"x\n");
    assert_eq!(built_paths(&fx), vec!["kept.md"]);
}

#[test]
fn ac2_git_folder_content_is_never_indexed() {
    let fx = Fixture::new("dotgit");
    fx.git_dir();
    fx.write(".git/config", b"[core]\n");
    fx.write(".git/HEAD", b"ref: refs/heads/main\n");
    fx.write("kept.md", b"x\n");
    assert_eq!(built_paths(&fx), vec!["kept.md"]);
}

#[test]
fn ac2_dotfiles_that_git_keeps_are_indexed() {
    let fx = Fixture::new("dotfiles");
    fx.git_dir();
    fx.write(".github/x.md", b"x\n");
    fx.write(".env.example", b"A=1\n");
    assert_eq!(built_paths(&fx), vec![".env.example", ".github/x.md"]);
}

#[test]
fn ac2_paths_use_slashes_from_the_root() {
    let fx = Fixture::new("slashes");
    fx.write("a/b/c.py", b"x\n");
    assert_eq!(built_paths(&fx), vec!["a/b/c.py"]);
}

#[test]
fn ac2_nul_byte_in_the_first_8k_skips_the_file() {
    let fx = Fixture::new("nul-early");
    let mut first = vec![b'a'; 8191];
    first.push(0);
    fx.write("bin-end.dat", &first);
    fx.write("bin-start.dat", b"\0abc");
    fx.write("kept.md", b"x\n");
    assert_eq!(built_paths(&fx), vec!["kept.md"]);
}

#[test]
fn ac2_nul_byte_after_8192_bytes_keeps_the_file() {
    let fx = Fixture::new("nul-late");
    let mut late = vec![b'a'; 8192];
    late.push(0);
    fx.write("late.dat", &late);
    assert_eq!(built_paths(&fx), vec!["late.dat"]);
}

#[test]
fn ac2_default_max_file_size_is_1_mib() {
    let fx = Fixture::new("max-default");
    fx.write("exact.txt", &vec![b'a'; MAX]);
    fx.write("over.txt", &vec![b'a'; MAX + 1]);
    assert_eq!(built_paths(&fx), vec!["exact.txt"]);
}

#[test]
fn ac2_max_file_size_option_sets_the_limit() {
    let fx = Fixture::new("max-opt");
    fx.write("ten.txt", b"0123456789");
    fx.write("eleven.txt", b"0123456789a");
    summary(&fx.build(&["--max-file-size", "10"]));
    assert_eq!(fx.paths(), vec!["ten.txt"]);
}

#[test]
fn ac2_symbolic_links_are_skipped() {
    let fx = Fixture::new("symlink");
    fx.write("real.md", b"x\n");
    #[cfg(unix)]
    std::os::unix::fs::symlink(fx.root.join("real.md"), fx.root.join("link.md")).unwrap();
    assert_eq!(built_paths(&fx), vec!["real.md"]);
}
