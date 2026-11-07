//! Tests of the `find` and `outline` queries (AC 8 to 12, and the query part of AC 16).

mod common;

use common::{Fixture, stderr, stdout, summary};

const PY: &str = "class Parser:
    def parse(self):
        def helper():
            pass

def parse(x):
    pass

class Outer:
    class Inner:
        def m(self):
            pass
";

const MD: &str = "# Title

### Deep

## Install

## Say \"hi\" \\ x
";

fn built(files: &[(&str, &str)]) -> Fixture {
    let fx = Fixture::new("queries");
    for (path, text) in files {
        fx.write(path, text.as_bytes());
    }
    summary(&fx.build(&[]));
    fx
}

/// Runs a command in the root. Returns the exit code and stdout.
fn run(fx: &Fixture, args: &[&str]) -> (i32, String) {
    let out = fx.run_in(&fx.root, args);
    (out.status.code().unwrap(), stdout(&out))
}

fn code_and_text() -> Fixture {
    built(&[("p.py", PY), ("a.md", MD)])
}

#[test]
fn ac8_find_matches_full_name_and_last_part() {
    let fx = code_and_text();
    assert_eq!(
        run(&fx, &["find", "parse"]),
        (
            0,
            "p.py:2 method Parser.parse\np.py:6 function parse\n".into()
        )
    );
    assert_eq!(
        run(&fx, &["find", "Parser.parse"]),
        (0, "p.py:2 method Parser.parse\n".into())
    );
    assert_eq!(
        run(&fx, &["find", "Outer"]),
        (0, "p.py:9 class Outer\n".into())
    );
    assert_eq!(
        run(&fx, &["find", "Inner"]),
        (0, "p.py:10 class Outer.Inner\n".into())
    );
}

#[test]
fn ac8_find_rejects_prefix_and_middle_part() {
    let fx = code_and_text();
    for name in ["Pars", "Inner.m", "Outer.Inner.", "Outer.Inner.m.x"] {
        assert_eq!(run(&fx, &["find", name]), (1, String::new()), "{name}");
    }
    assert_eq!(run(&fx, &["find", "Outer.Inner.m"]).0, 0);
}

#[test]
fn ac8_find_heading_and_kind_filter() {
    let fx = code_and_text();
    assert_eq!(
        run(&fx, &["find", "Install"]),
        (0, "a.md:5 heading Install\n".into())
    );
    assert_eq!(
        run(&fx, &["find", "parse", "--kind", "method"]),
        (0, "p.py:2 method Parser.parse\n".into())
    );
    assert_eq!(
        run(&fx, &["find", "parse", "--kind", "interface"]),
        (1, String::new())
    );
}

#[test]
fn ac8_find_in_typescript_and_javascript() {
    let fx = built(&[
        ("t.ts", "export class A { m() {} }\nexport interface I {}\n"),
        ("j.js", "export const K = 1;\nfunction m() {}\n"),
    ]);
    assert_eq!(
        run(&fx, &["find", "m"]),
        (0, "j.js:2 function m\nt.ts:1 method A.m\n".into())
    );
    assert_eq!(run(&fx, &["find", "I"]), (0, "t.ts:2 interface I\n".into()));
    assert_eq!(run(&fx, &["find", "K"]), (0, "j.js:1 constant K\n".into()));
}

#[test]
fn ac9_outline_indents_by_parent_and_level() {
    let fx = code_and_text();
    assert_eq!(
        run(&fx, &["outline", "p.py"]),
        (
            0,
            "1 class Parser\n  2 method parse\n    3 function helper\n6 function parse\n\
             9 class Outer\n  10 class Inner\n    11 method m\n"
                .into()
        )
    );
    assert_eq!(
        run(&fx, &["outline", "a.md"]),
        (
            0,
            "1 heading Title\n    3 heading Deep\n  5 heading Install\n  7 heading Say \"hi\" \\ x\n"
                .into()
        )
    );
}

#[test]
fn ac9_outline_relative_path_and_no_result_cases() {
    let fx = built(&[("sub/file.py", "def f():\n    pass\n"), ("n.txt", "text\n")]);
    let from_root = run(&fx, &["outline", "sub/file.py"]);
    assert_eq!(from_root, (0, "1 function f\n".into()));
    let out = fx.run_in(&fx.root.join("sub"), &["outline", "file.py"]);
    assert_eq!((out.status.code().unwrap(), stdout(&out)), from_root);
    assert_eq!(run(&fx, &["outline", "n.txt"]), (1, String::new()));
    assert_eq!(run(&fx, &["outline", "missing.py"]), (1, String::new()));
    let out = fx.run_in(&fx.root, &["outline", "../x"]);
    assert_eq!(out.status.code(), Some(2));
    assert_eq!(stdout(&out), "");
}

#[test]
fn ac10_query_updates_the_index_first() {
    let fx = built(&[("a.py", "def old():\n    pass\n")]);
    fx.write("b.py", b"def fresh():\n    pass\n");
    assert_eq!(
        run(&fx, &["find", "fresh", "--no-update"]),
        (1, String::new())
    );
    assert_eq!(
        run(&fx, &["find", "fresh"]),
        (0, "b.py:1 function fresh\n".into())
    );
}

#[test]
fn ac10_no_update_needs_a_current_index() {
    let fx = Fixture::new("queries");
    fx.write("a.py", b"def f():\n    pass\n");
    let out = fx.run_in(&fx.root, &["find", "f", "--no-update"]);
    assert_eq!(out.status.code(), Some(2));
    assert_eq!(stdout(&out), "");
    assert!(!stderr(&out).is_empty());
    summary(&fx.build(&[]));
    fx.conn()
        .execute(
            "UPDATE meta SET value = '1' WHERE key = 'schema_version'",
            [],
        )
        .unwrap();
    let out = fx.run_in(&fx.root, &["find", "f", "--no-update"]);
    assert_eq!(out.status.code(), Some(2));
    assert!(stderr(&out).contains("broken index"), "{}", stderr(&out));
}

fn many() -> Fixture {
    let fx = Fixture::new("queries");
    for n in 0..25 {
        fx.write(&format!("f{n:02}.py"), b"def dup():\n    pass\n");
    }
    summary(&fx.build(&[]));
    fx
}

#[test]
fn ac11_limit_cuts_text_output() {
    let fx = many();
    let (code, text) = run(&fx, &["find", "dup"]);
    let lines: Vec<&str> = text.lines().collect();
    assert_eq!((code, lines.len()), (0, 21));
    assert_eq!(lines[0], "f00.py:1 function dup");
    assert_eq!(lines[19], "f19.py:1 function dup");
    assert_eq!(lines[20], "(5 more results not printed. Use --limit.)");
    let (_, text) = run(&fx, &["find", "dup", "--limit", "3"]);
    assert_eq!(text.lines().count(), 4);
    assert!(text.ends_with("(22 more results not printed. Use --limit.)\n"));
    for limit in ["25", "30"] {
        let (_, text) = run(&fx, &["find", "dup", "--limit", limit]);
        assert_eq!(text.lines().count(), 25, "{limit}");
        assert!(!text.contains("more results"));
    }
    assert_eq!(
        run(&fx, &["find", "dup", "--limit", "0"]),
        (0, "(25 more results not printed. Use --limit.)\n".into())
    );
}

#[test]
fn ac11_limit_cuts_outline_output() {
    let fx = built(&[("p.py", PY)]);
    assert_eq!(
        run(&fx, &["outline", "p.py", "--limit", "2"]),
        (
            0,
            "1 class Parser\n  2 method parse\n(5 more results not printed. Use --limit.)\n".into()
        )
    );
}

#[test]
fn ac11_json_output() {
    let fx = built(&[("p.py", "def a():\n    pass\n")]);
    let row = "\"path\":\"p.py\",\"line\":1,\"end_line\":2,\"kind\":\"function\",\"name\":\"a\",\
               \"qualified_name\":\"a\",\"level\":null";
    assert_eq!(
        run(&fx, &["find", "a", "--format", "json"]),
        (0, format!("{{\"results\":[{{{row}}}],\"omitted\":0}}\n"))
    );
    assert_eq!(
        run(&fx, &["outline", "p.py", "--format", "json"]),
        (
            0,
            format!("{{\"results\":[{{{row},\"depth\":0}}],\"omitted\":0}}\n")
        )
    );
    assert_eq!(
        run(&fx, &["find", "a", "--format", "json", "--limit", "0"]),
        (0, "{\"results\":[],\"omitted\":1}\n".into())
    );
    assert_eq!(
        run(&fx, &["find", "zzz", "--format", "json"]),
        (1, "{\"results\":[],\"omitted\":0}\n".into())
    );
}

#[test]
fn ac11_json_escapes_and_heading_level() {
    let fx = built(&[("a.md", MD)]);
    let (code, text) = run(&fx, &["outline", "a.md", "--format", "json"]);
    assert_eq!(code, 0);
    assert!(
        text.contains("\"name\":\"Say \\\"hi\\\" \\\\ x\""),
        "{text}"
    );
    assert!(text.contains("\"level\":3,\"depth\":2}"), "{text}");
    assert_eq!(text.lines().count(), 1);
}

#[test]
fn ac12_usage_errors_exit_2_with_usage_on_stderr() {
    let fx = built(&[("p.py", PY)]);
    let cases: [&[&str]; 8] = [
        &["find"],
        &["find", "a", "b"],
        &["outline"],
        &["find", "a", "--limit", "abc"],
        &["outline", "p.py", "--kind", "method"],
        &["find", "a", "--bogus"],
        &["find", "a", "--format", "xml"],
        &["outline", "p.py", "--limit"],
    ];
    for args in cases {
        let out = fx.run_in(&fx.root, args);
        assert_eq!(out.status.code(), Some(2), "{args:?}");
        assert_eq!(stdout(&out), "", "{args:?}");
        assert!(stderr(&out).contains("usage"), "{args:?}: {}", stderr(&out));
    }
}
