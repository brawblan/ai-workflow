//! Tests of Rust files: type, symbols, qualified names, links, resolution, CLI output (issue 273).

mod common;

use common::{Fixture, summary};

fn built(files: &[(&str, &str)], extra: &[&str]) -> Fixture {
    let fx = Fixture::new("rust");
    for (path, text) in files {
        fx.write(path, text.as_bytes());
    }
    summary(&fx.build(extra));
    fx
}

fn run(fx: &Fixture, args: &[&str]) -> String {
    let out = fx.run_in(&fx.root, args);
    assert_eq!(out.status.code(), Some(0), "{}", common::stderr(&out));
    common::stdout(&out)
}

fn syms(fx: &Fixture, path: &str) -> Vec<String> {
    let conn = fx.conn();
    let mut st = conn
        .prepare("SELECT kind, qualified_name FROM symbols WHERE path = ?1 ORDER BY line, id")
        .unwrap();
    st.query_map([path], |r| {
        Ok(format!(
            "{} {}",
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?
        ))
    })
    .unwrap()
    .map(Result::unwrap)
    .collect()
}

fn lang(fx: &Fixture, path: &str) -> Option<String> {
    fx.conn()
        .query_row("SELECT language FROM files WHERE path = ?1", [path], |r| {
            r.get(0)
        })
        .unwrap()
}

fn links(fx: &Fixture, path: &str) -> Vec<(String, String, String)> {
    let conn = fx.conn();
    let mut st = conn
        .prepare("SELECT kind, target, resolved FROM links WHERE path = ?1 ORDER BY line, id")
        .unwrap();
    st.query_map([path], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect()
}

fn l(kind: &str, target: &str, resolved: &str) -> (String, String, String) {
    (kind.into(), target.into(), resolved.into())
}

#[test]
fn ac1_rs_extension_maps_to_rust() {
    let fx = built(&[("a.rs", "fn main() {}\n")], &[]);
    assert_eq!(lang(&fx, "a.rs").as_deref(), Some("rust"));
}

#[test]
fn ac1_file_indexed_before_without_parser_is_parsed_again() {
    let fx = built(&[("a.rs", "fn main() {}\n")], &["--lang", "rs=markdown"]);
    assert_eq!(lang(&fx, "a.rs").as_deref(), Some("markdown"));
    assert!(syms(&fx, "a.rs").is_empty());
    summary(&fx.build(&[]));
    assert_eq!(lang(&fx, "a.rs").as_deref(), Some("rust"));
    assert_eq!(syms(&fx, "a.rs"), vec!["function main"]);
}

#[test]
fn ac2_symbol_kinds() {
    let src = "fn f() {}\nstruct S;\nenum E { A }\nunion U { a: u32 }\ntrait T { fn t(&self); }\n\
impl S { fn m(&self) {} }\nmod inner {\n    pub fn g() {}\n}\nmod outside;\nconst C: u32 = 1;\n\
static ST: u32 = 2;\ntype Alias = u32;\nmacro_rules! mac { () => {}; }\n";
    let fx = built(&[("a.rs", src)], &[]);
    let got = syms(&fx, "a.rs");
    for want in [
        "function f",
        "struct S",
        "enum E",
        "union U",
        "trait T",
        "method T.t",
        "method S.m",
        "mod inner",
        "function inner.g",
        "constant C",
        "static ST",
        "type Alias",
        "macro mac",
    ] {
        assert!(got.contains(&want.to_string()), "{want} missing in {got:?}");
    }
    assert!(
        !got.iter().any(|s| s.contains("outside")),
        "`mod outside;` must not be a symbol: {got:?}"
    );
}

#[test]
fn ac3_qualified_names() {
    let src = "struct Type;\ntrait Trait { fn tm(&self); }\nimpl Type { fn a(&self) {} }\n\
impl Trait for Type { fn tm(&self) {} }\nimpl<T> a::Box<T> { fn put(&self) {} }\n\
mod m {\n    struct Inner;\n    impl Inner { fn deep(&self) {} }\n}\n";
    let fx = built(&[("a.rs", src)], &[]);
    let got = syms(&fx, "a.rs");
    for want in [
        "method Type.a",
        "method Type.tm",
        "method Box.put",
        "method Trait.tm",
        "method m.Inner.deep",
    ] {
        assert!(got.contains(&want.to_string()), "{want} missing in {got:?}");
    }
}

#[test]
fn ac4_mod_and_use_links() {
    let src = "mod name;\nuse std::io;\nuse a::{self, b as c, d::*};\n";
    let fx = built(&[("a.rs", src)], &[]);
    assert_eq!(
        links(&fx, "a.rs"),
        vec![
            l("mod", "name", ""),
            l("use", "std::io", ""),
            l("use", "a", ""),
            l("use", "a::b", ""),
            l("use", "a::d", ""),
        ]
    );
}

#[test]
fn ac5_resolution() {
    let fx = built(
        &[
            (
                "src/lib.rs",
                "mod net;\nmod foo;\nuse std::io;\npub struct Thing;\n",
            ),
            ("src/net/mod.rs", "mod tcp;\n"),
            ("src/net/tcp.rs", "pub struct Conn;\n"),
            ("src/foo.rs", "mod x;\n"),
            ("src/foo/x.rs", "fn x() {}\n"),
            (
                "src/other.rs",
                "use crate::net::tcp::Conn;\nuse crate::Thing;\n",
            ),
        ],
        &[],
    );
    assert_eq!(
        links(&fx, "src/lib.rs"),
        vec![
            l("mod", "net", "src/net/mod.rs"),
            l("mod", "foo", "src/foo.rs"),
            l("use", "std::io", ""),
        ]
    );
    assert_eq!(
        links(&fx, "src/net/mod.rs"),
        vec![l("mod", "tcp", "src/net/tcp.rs")]
    );
    assert_eq!(
        links(&fx, "src/foo.rs"),
        vec![l("mod", "x", "src/foo/x.rs")]
    );
    assert_eq!(
        links(&fx, "src/other.rs"),
        vec![
            l("use", "crate::net::tcp::Conn", "src/net/tcp.rs"),
            l("use", "crate::Thing", "src/lib.rs"),
        ]
    );
}

#[test]
fn ac5_mod_resolves_to_plain_file_when_no_mod_rs() {
    let fx = built(
        &[("src/lib.rs", "mod net;\n"), ("src/net.rs", "fn n() {}\n")],
        &[],
    );
    assert_eq!(
        links(&fx, "src/lib.rs"),
        vec![l("mod", "net", "src/net.rs")]
    );
}

#[test]
fn ac6_find_outline_refs_text() {
    let fx = built(
        &[
            (
                "src/lib.rs",
                "pub struct Conn;\nimpl Conn {\n    pub fn open(&self) {}\n}\nmod net;\n",
            ),
            ("src/net.rs", "use crate::Conn;\n"),
        ],
        &[],
    );
    assert_eq!(
        run(&fx, &["find", "Conn", "--no-update"]),
        "src/lib.rs:1 struct Conn\n"
    );
    assert_eq!(
        run(&fx, &["find", "Conn.open", "--no-update"]),
        "src/lib.rs:3 method Conn.open\n"
    );
    assert_eq!(
        run(&fx, &["outline", "src/lib.rs", "--no-update"]),
        "1 struct Conn\n3 method open\n"
    );
    assert_eq!(
        run(&fx, &["refs", "src/lib.rs", "--no-update"]),
        "in\nsrc/net.rs:1 use crate::Conn\nout\nsrc/lib.rs:5 mod net\n"
    );
}

#[test]
fn use_list_comments_are_skipped() {
    let src = "use a::{b, /* x */ // note\n    c};\n";
    let fx = built(&[("a.rs", src)], &[]);
    let targets: Vec<String> = links(&fx, "a.rs").into_iter().map(|t| t.1).collect();
    assert_eq!(targets, vec!["a::b", "a::c"]);
}

#[test]
fn search_finds_a_line_in_a_rust_file() {
    let fx = built(&[("src/lib.rs", "pub fn zebra() {}\n")], &[]);
    assert_eq!(
        run(&fx, &["search", "zebra"]),
        "src/lib.rs:1: pub fn zebra() {}\n"
    );
}
