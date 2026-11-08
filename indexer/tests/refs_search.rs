//! Tests of the `refs` and `search` queries (AC 1 to 7 of issue 256).

mod common;

use common::{Fixture, stderr, stdout, summary};

type Row = (i64, String, String, String);

fn built(files: &[(&str, &str)]) -> Fixture {
    let fx = Fixture::new("refs");
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

/// The links of one file as (line, kind, target, resolved), in line order.
fn links(fx: &Fixture, path: &str) -> Vec<Row> {
    let conn = fx.conn();
    let mut st = conn
        .prepare("SELECT line, kind, target, resolved FROM links WHERE path = ?1 ORDER BY line, id")
        .unwrap();
    st.query_map([path], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect()
}

fn row(line: i64, kind: &str, target: &str, resolved: &str) -> Row {
    (line, kind.into(), target.into(), resolved.into())
}

fn chunk_count(fx: &Fixture, path: &str) -> i64 {
    fx.conn()
        .query_row(
            "SELECT count(*) FROM chunk_rows WHERE path = ?1",
            [path],
            |r| r.get(0),
        )
        .unwrap()
}

fn numbered(n: usize) -> String {
    (1..=n).map(|i| format!("line number {i}\n")).collect()
}

#[test]
fn ac1_python_links() {
    let fx = built(&[(
        "p.py",
        "import a.b\nfrom m import a\nfrom . import x\nfrom .y import z\n",
    )]);
    let kinds: Vec<(i64, String, String)> = links(&fx, "p.py")
        .into_iter()
        .map(|(l, k, t, _)| (l, k, t))
        .collect();
    assert_eq!(
        kinds,
        vec![
            (1, "import".into(), "a.b".into()),
            (2, "import".into(), "m.a".into()),
            (3, "import".into(), ".x".into()),
            (4, "import".into(), ".y.z".into()),
        ]
    );
}

#[test]
fn ac1_script_links() {
    let src = "import a from 'a';\nexport { b } from './b';\nconst c = require('c');\nconst d = import('d');\nconst e = require(name);\n";
    for file in ["s.ts", "s.js"] {
        let fx = built(&[(file, src)]);
        assert_eq!(
            links(&fx, file),
            vec![
                row(1, "import", "a", ""),
                row(2, "export", "./b", ""),
                row(3, "require", "c", ""),
                row(4, "import", "d", ""),
            ],
            "{file}"
        );
    }
}

#[test]
fn ac1_markdown_links() {
    let md = "# T\n\nSee [a](docs/a.md#top) now.\n\nSee [site](https://example.com/x) and `[c](c.md)`.\n\n```\n[d](d.md)\n```\n";
    let fx = built(&[("r.md", md), ("docs/a.md", "x\n")]);
    assert_eq!(
        links(&fx, "r.md"),
        vec![row(3, "link", "docs/a.md", "docs/a.md")]
    );
}

#[test]
fn ac2_resolution() {
    let fx = built(&[
        ("pkg/a.py", "x = 1\n"),
        ("src/lib/util.py", "x = 1\n"),
        (
            "main.py",
            "import pkg.a\nimport lib.util\nimport requests\n",
        ),
        ("web/lib.ts", "export const a = 1;\n"),
        ("web/ui/index.ts", "export const b = 1;\n"),
        ("web/old.ts", "export const c = 1;\n"),
        (
            "web/main.ts",
            "import a from './lib';\nimport b from './ui';\nimport c from './old.js';\nimport r from 'react';\n",
        ),
        ("docs/a.md", "[up](../web/lib.ts)\n"),
    ]);
    assert_eq!(
        links(&fx, "main.py"),
        vec![
            row(1, "import", "pkg.a", "pkg/a.py"),
            row(2, "import", "lib.util", "src/lib/util.py"),
            row(3, "import", "requests", ""),
        ]
    );
    assert_eq!(
        links(&fx, "web/main.ts"),
        vec![
            row(1, "import", "./lib", "web/lib.ts"),
            row(2, "import", "./ui", "web/ui/index.ts"),
            row(3, "import", "./old.js", "web/old.ts"),
            row(4, "import", "react", ""),
        ]
    );
    assert_eq!(
        links(&fx, "docs/a.md"),
        vec![row(1, "link", "../web/lib.ts", "web/lib.ts")]
    );
    let (code, json) = run(
        &fx,
        &["refs", "web/main.ts", "--format", "json", "--no-update"],
    );
    assert_eq!(code, 0);
    assert!(
        json.contains("\"target\":\"react\",\"resolved\":\"\""),
        "{json}"
    );
}

#[test]
fn ac2_new_file_resolves_link_of_unchanged_file() {
    let fx = built(&[("main.py", "import later\n")]);
    assert_eq!(links(&fx, "main.py"), vec![row(1, "import", "later", "")]);
    fx.write("later.py", b"x = 1\n");
    summary(&fx.build(&[]));
    assert_eq!(
        links(&fx, "main.py"),
        vec![row(1, "import", "later", "later.py")]
    );
}

#[test]
fn ac3_refs_path_in_and_out() {
    let fx = built(&[
        ("a.py", "import b\nimport os\n"),
        ("b.py", "x = 1\n"),
        ("c.py", "\nimport b\n"),
    ]);
    assert_eq!(
        run(&fx, &["refs", "b.py"]),
        (0, "in\na.py:1 import b\nc.py:2 import b\nout\n".into())
    );
    assert_eq!(
        run(&fx, &["refs", "a.py"]),
        (0, "in\nout\na.py:1 import b\na.py:2 import os\n".into())
    );
}

#[test]
fn ac3_refs_module_name() {
    let fx = built(&[("pkg/b.py", "import os\n"), ("a.py", "import pkg.b\n")]);
    assert_eq!(
        run(&fx, &["refs", "pkg.b"]),
        (
            0,
            "in\na.py:1 import pkg.b\nout\npkg/b.py:1 import os\n".into()
        )
    );
}

#[test]
fn ac4_chunks_of_50_lines() {
    let fx = built(&[("big.py", &numbered(120)), ("notes.txt", "hello world\n")]);
    assert_eq!(chunk_count(&fx, "big.py"), 3);
    let starts: Vec<i64> = {
        let conn = fx.conn();
        let mut st = conn
            .prepare("SELECT line FROM chunk_rows WHERE path = 'big.py' ORDER BY line")
            .unwrap();
        st.query_map([], |r| r.get(0))
            .unwrap()
            .map(Result::unwrap)
            .collect()
    };
    assert_eq!(starts, vec![1, 51, 101]);
    assert_eq!(chunk_count(&fx, "notes.txt"), 1);
}

#[test]
fn ac4_changed_and_deleted_files_leave_no_stale_chunks() {
    let fx = built(&[("a.txt", "zebra here\n"), ("b.txt", "giraffe here\n")]);
    assert_eq!(run(&fx, &["search", "zebra"]).0, 0);
    fx.write("a.txt", b"lion here\n");
    fx.set_mtime("a.txt", 1_800_000_000);
    fx.remove("b.txt");
    assert_eq!(run(&fx, &["search", "zebra"]).0, 1);
    assert_eq!(run(&fx, &["search", "giraffe"]).0, 1);
    assert_eq!(
        run(&fx, &["search", "lion"]),
        (0, "a.txt:1: lion here\n".into())
    );
    assert_eq!(chunk_count(&fx, "a.txt"), 1);
    assert_eq!(chunk_count(&fx, "b.txt"), 0);
}

#[test]
fn ac5_search_prints_matching_line_in_bm25_order() {
    let fx = built(&[
        ("one.txt", "alpha\nbeta\nneedle in the middle\nomega\n"),
        ("two.txt", "needle needle needle\n"),
    ]);
    assert_eq!(
        run(&fx, &["search", "needle"]),
        (
            0,
            "two.txt:1: needle needle needle\none.txt:3: needle in the middle\n".into()
        )
    );
}

#[test]
fn ac5_search_matches_any_word() {
    let fx = built(&[("a.txt", "x\nfoo\n"), ("b.txt", "bar\n")]);
    assert_eq!(
        run(&fx, &["search", "foo bar", "--any"]),
        (0, "b.txt:1: bar\na.txt:2: foo\n".into())
    );
}

#[test]
fn ac6_search_path_glob() {
    let fx = built(&[("docs/a.md", "needle\n"), ("src/b.py", "needle\n")]);
    assert_eq!(
        run(&fx, &["search", "needle", "--path", "docs/*"]),
        (0, "docs/a.md:1: needle\n".into())
    );
    assert_eq!(
        run(&fx, &["search", "needle", "--path", "*.py"]),
        (0, "src/b.py:1: needle\n".into())
    );
    assert_eq!(run(&fx, &["search", "needle", "--path", "none/*"]).0, 1);
}

#[test]
fn ac7_no_update_without_index_exits_2() {
    let fx = Fixture::new("noindex");
    fx.write("a.txt", b"needle\n");
    for args in [
        ["search", "needle", "--no-update"],
        ["refs", "a.txt", "--no-update"],
    ] {
        let out = fx.run_in(&fx.root, &args);
        assert_eq!(out.status.code(), Some(2), "{}", stderr(&out));
    }
}

#[test]
fn ac7_update_step_builds_the_index() {
    let fx = Fixture::new("update");
    fx.write("a.txt", b"needle\n");
    assert_eq!(
        run(&fx, &["search", "needle"]),
        (0, "a.txt:1: needle\n".into())
    );
}

#[test]
fn ac7_no_results_exits_1() {
    let fx = built(&[("a.txt", "needle\n")]);
    assert_eq!(run(&fx, &["search", "absent"]), (1, String::new()));
    assert_eq!(run(&fx, &["refs", "nothing.py"]), (1, String::new()));
}

#[test]
fn ac7_limit_prints_omitted_line() {
    let fx = built(&[
        ("a.txt", "needle\n"),
        ("b.txt", "needle\n"),
        ("c.txt", "needle\n"),
    ]);
    assert_eq!(
        run(&fx, &["search", "needle", "--limit", "1"]),
        (
            0,
            "a.txt:1: needle\n(2 more results not printed. Use --limit.)\n".into()
        )
    );
    let fx = built(&[("a.py", "import b\nimport b\nimport b\n"), ("b.py", "")]);
    let (code, text) = run(&fx, &["refs", "b.py", "--limit", "1"]);
    assert_eq!(code, 0);
    assert_eq!(
        text,
        "in\na.py:1 import b\nout\n(2 more results not printed. Use --limit.)\n"
    );
}

#[test]
fn ac7_json_format() {
    let fx = built(&[("a.txt", "needle\n")]);
    assert_eq!(
        run(&fx, &["search", "needle", "--format", "json"]),
        (
            0,
            "{\"results\":[{\"path\":\"a.txt\",\"line\":1,\"text\":\"needle\"}],\"omitted\":0}\n"
                .into()
        )
    );
    assert_eq!(
        run(&fx, &["search", "zzz", "--format", "json"]),
        (1, "{\"results\":[],\"omitted\":0}\n".into())
    );
    let fx = built(&[("a.py", "import b\n"), ("b.py", "")]);
    assert_eq!(
        run(&fx, &["refs", "b.py", "--format", "json"]),
        (
            0,
            "{\"in\":[{\"path\":\"a.py\",\"line\":1,\"kind\":\"import\",\"target\":\"b\",\"resolved\":\"b.py\"}],\"out\":[],\"omitted\":0}\n"
                .into()
        )
    );
}

#[test]
fn review_markdown_link_in_table_cell_is_a_link() {
    let fx = built(&[
        ("t.md", "| a | b |\n|---|---|\n| x | [b](b.md) |\n"),
        ("b.md", "x\n"),
    ]);
    assert_eq!(links(&fx, "t.md"), vec![row(3, "link", "b.md", "b.md")]);
}

#[test]
fn review_search_prints_the_line_with_the_whole_word() {
    let fx = built(&[("a.py", "db = database()\nreturn merge_base(x)\n")]);
    assert_eq!(
        run(&fx, &["search", "base"]),
        (0, "a.py:2: return merge_base(x)\n".into())
    );
}

#[test]
fn review_search_skips_a_stale_hit() {
    let fx = built(&[("a.txt", "zebra here\n"), ("b.txt", "zebra there\n")]);
    fx.write("a.txt", b"lion here\n");
    let (code, text) = run(&fx, &["search", "zebra", "--no-update"]);
    assert_eq!(code, 0);
    assert!(text.starts_with("b.txt:1: zebra there\n"), "{text}");
    assert!(!text.contains("a.txt"), "{text}");
}

#[test]
fn review_import_of_standard_module_stays_external() {
    let fx = built(&[
        ("app/main.py", "import logging\n"),
        ("tools/logging.py", "x = 1\n"),
    ]);
    assert_eq!(
        links(&fx, "app/main.py"),
        vec![row(1, "import", "logging", "")]
    );
}

#[test]
fn review_sibling_and_top_package_imports_still_resolve() {
    let fx = built(&[
        ("app/main.py", "from . import util\n"),
        ("app/util.py", "x = 1\n"),
        ("src/pkg/__init__.py", ""),
        ("src/pkg/m.py", "x = 1\n"),
        ("use.py", "import pkg.m\n"),
    ]);
    assert_eq!(
        links(&fx, "app/main.py"),
        vec![row(1, "import", ".util", "app/util.py")]
    );
    assert_eq!(
        links(&fx, "use.py"),
        vec![row(1, "import", "pkg.m", "src/pkg/m.py")]
    );
}

#[test]
fn review_import_in_python_package_skips_sibling_file() {
    let fx = built(&[
        ("pkg/__init__.py", ""),
        ("pkg/html.py", "import html\n"),
        ("pkg/util.py", "import json\n"),
        ("pkg/json.py", "x = 1\n"),
        ("tools/run.py", "import helper\n"),
        ("tools/helper.py", "x = 1\n"),
    ]);
    assert_eq!(
        links(&fx, "pkg/html.py"),
        vec![row(1, "import", "html", "")]
    );
    assert_eq!(
        links(&fx, "pkg/util.py"),
        vec![row(1, "import", "json", "")]
    );
    assert_eq!(
        links(&fx, "tools/run.py"),
        vec![row(1, "import", "helper", "tools/helper.py")]
    );
}
