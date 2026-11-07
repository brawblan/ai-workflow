//! Tests of `show` and `search --context` (AC 1 to 6 of issue 272).

mod common;

use common::{Fixture, stdout, summary};

fn built(files: &[(&str, &str)]) -> Fixture {
    let fx = Fixture::new("showctx");
    for (path, text) in files {
        fx.write(path, text.as_bytes());
    }
    summary(&fx.build(&[]));
    fx
}

fn run(fx: &Fixture, args: &[&str]) -> (i32, String) {
    let out = fx.run_in(&fx.root, args);
    (out.status.code().unwrap(), stdout(&out))
}

const A_PY: &str = "def alpha():\n    one = 1\n    two = 2\n    return one + two\n\nx = 5\n";

#[test]
fn ac1_show_header_and_lines() {
    let fx = built(&[("a.py", A_PY), ("b.py", "def beta():\n    pass\n")]);
    let (code, out) = run(&fx, &["show", "alpha", "--no-update"]);
    assert_eq!(code, 0);
    assert_eq!(
        out,
        "a.py:1-4 function alpha\ndef alpha():\n    one = 1\n    two = 2\n    return one + two\n"
    );
    let (_, out) = run(&fx, &["show", "alpha", "--kind", "class", "--no-update"]);
    assert_eq!(out, "");
}

#[test]
fn ac2_max_lines_cuts() {
    let fx = built(&[("a.py", A_PY)]);
    let (_, out) = run(&fx, &["show", "alpha", "--max-lines", "2", "--no-update"]);
    assert_eq!(
        out,
        "a.py:1-4 function alpha\ndef alpha():\n    one = 1\n... 2 more lines (a.py:3-4)\n"
    );
    let (_, out) = run(&fx, &["show", "alpha", "--max-lines", "4", "--no-update"]);
    assert!(!out.contains("more lines"), "{out}");
}

#[test]
fn ac2_max_lines_default_is_80() {
    let mut body = String::from("def big():\n");
    for i in 1..=99 {
        body.push_str(&format!("    v{i} = {i}\n"));
    }
    let fx = built(&[("big.py", &body)]);
    let (_, out) = run(&fx, &["show", "big", "--no-update"]);
    assert!(out.starts_with("big.py:1-100 function big\n"), "{out}");
    assert!(
        out.ends_with("... 20 more lines (big.py:81-100)\n"),
        "{out}"
    );
    assert_eq!(out.lines().count(), 82);
}

#[test]
fn ac3_limit_default_5_and_exit_codes() {
    let files: Vec<(String, String)> = (1..=7)
        .map(|i| (format!("m{i}.py"), "def dup():\n    pass\n".to_string()))
        .collect();
    let refs: Vec<(&str, &str)> = files
        .iter()
        .map(|(p, t)| (p.as_str(), t.as_str()))
        .collect();
    let fx = built(&refs);
    let (code, out) = run(&fx, &["show", "dup", "--no-update"]);
    assert_eq!(code, 0);
    assert_eq!(out.matches("function dup").count(), 5, "{out}");
    assert!(
        out.contains("(2 more results not printed. Use --limit.)"),
        "{out}"
    );
    let (_, out) = run(&fx, &["show", "dup", "--limit", "1", "--no-update"]);
    assert_eq!(out.matches("function dup").count(), 1, "{out}");
    let (none, _) = run(&fx, &["show", "nosuchname", "--no-update"]);
    let (find_none, _) = run(&fx, &["find", "nosuchname", "--no-update"]);
    assert_eq!(none, find_none);
}

#[test]
fn ac4_stale_file_prints_no_lines() {
    let fx = built(&[("a.py", A_PY)]);
    fx.write(
        "a.py",
        b"def alpha():\n    changed = 1\n    two = 2\n    return 3\n",
    );
    let (code, out) = run(&fx, &["show", "alpha", "--no-update"]);
    assert_eq!(code, 0);
    assert_eq!(out, "stale: a.py\n");
}

/// A file of 100 lines. Lines in `hits` have the word `alpha`. One hit for each block of 50 lines.
fn hundred(hits: &[usize]) -> String {
    (1..=100)
        .map(|i| match hits.contains(&i) {
            true => format!("alpha {i}\n"),
            false => format!("filler {i}\n"),
        })
        .collect()
}

#[test]
fn ac5_search_context_lines_and_separate_ranges() {
    let fx = built(&[("t.txt", &hundred(&[10, 60]))]);
    let (code, out) = run(&fx, &["search", "alpha", "--context", "1", "--no-update"]);
    assert_eq!(code, 0);
    let want = "t.txt-9- filler 9\nt.txt:10: alpha 10\nt.txt-11- filler 11\n--\n\
                t.txt-59- filler 59\nt.txt:60: alpha 60\nt.txt-61- filler 61\n";
    assert_eq!(out, want);
    // Default 0 keeps the old output.
    let (_, out) = run(&fx, &["search", "alpha", "--no-update"]);
    assert_eq!(out, "t.txt:10: alpha 10\nt.txt:60: alpha 60\n");
}

#[test]
fn ac5_search_context_merges_touching_ranges() {
    // Hits at 50 and 52, context 1: ranges 49-51 and 51-53 overlap. Hits at 50 and 53 touch.
    for (second, last) in [(52, 53), (53, 54)] {
        let fx = built(&[("t.txt", &hundred(&[50, second]))]);
        let (_, out) = run(&fx, &["search", "alpha", "--context", "1", "--no-update"]);
        assert!(!out.contains("--\n"), "{out}");
        let want: Vec<String> = (49..=last)
            .map(|n| match n == 50 || n == second {
                true => format!("t.txt:{n}: alpha {n}"),
                false => format!("t.txt-{n}- filler {n}"),
            })
            .collect();
        assert_eq!(out, want.join("\n") + "\n");
    }
}

#[test]
fn ac6_json_includes_lines() {
    let fx = built(&[("a.py", A_PY), ("t.txt", "alpha 1\nfiller 2\n")]);
    let (_, out) = run(&fx, &["show", "alpha", "--format", "json", "--no-update"]);
    assert!(
        out.contains("\"lines\":[\"def alpha():\",\"    one = 1\","),
        "{out}"
    );
    let (_, out) = run(
        &fx,
        &[
            "search",
            "filler",
            "--context",
            "1",
            "--format",
            "json",
            "--no-update",
        ],
    );
    assert!(
        out.contains("{\"line\":1,\"text\":\"alpha 1\",\"hit\":false}"),
        "{out}"
    );
    assert!(
        out.contains("{\"line\":2,\"text\":\"filler 2\",\"hit\":true}"),
        "{out}"
    );
}

#[test]
fn tab_prints_as_four_spaces_in_show_and_search_context() {
    let fx = built(&[
        ("a.py", "def alpha():\n\tone = 1\n\treturn one\n"),
        ("t.txt", "alpha\n\tfiller\n"),
    ]);
    let (_, out) = run(&fx, &["show", "alpha", "--no-update"]);
    assert_eq!(
        out,
        "a.py:1-3 function alpha\ndef alpha():\n    one = 1\n    return one\n"
    );
    assert!(!out.contains('\t'), "{out}");
    let (_, out) = run(&fx, &["search", "filler", "--context", "1", "--no-update"]);
    assert!(!out.contains('\t'), "{out}");
    assert!(out.contains("t.txt:2:     filler"), "{out}");
}
