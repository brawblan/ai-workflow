//! Tests of C, C++, and C# files: types, symbols, qualified names, links (AC 1 to 6 of issue 257).

mod common;

use common::{Fixture, summary};

fn built(files: &[(&str, &str)], extra: &[&str]) -> Fixture {
    let fx = Fixture::new("ccc");
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

/// Symbols of one file as `kind qualified_name` lines, in line order.
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

#[test]
fn ac1_extensions_map_to_languages() {
    let body = "int x;\n";
    let files: Vec<(String, &str)> = [
        "a.c", "a.cc", "a.cpp", "a.cxx", "a.hpp", "a.hh", "a.hxx", "a.cs", "a.h",
    ]
    .iter()
    .map(|p| (p.to_string(), body))
    .collect();
    let refs: Vec<(&str, &str)> = files.iter().map(|(p, t)| (p.as_str(), *t)).collect();
    let fx = built(&refs, &[]);
    assert_eq!(lang(&fx, "a.c").as_deref(), Some("c"));
    for p in ["a.cc", "a.cpp", "a.cxx", "a.hpp", "a.hh", "a.hxx", "a.h"] {
        assert_eq!(lang(&fx, p).as_deref(), Some("cpp"), "{p}");
    }
    assert_eq!(lang(&fx, "a.cs").as_deref(), Some("csharp"));
}

#[test]
fn ac2_lang_h_equals_c_and_rebuild_without_it() {
    let fx = built(
        &[("t.h", "struct Point {\n  int x;\n};\n")],
        &["--lang", "h=c"],
    );
    assert_eq!(lang(&fx, "t.h").as_deref(), Some("c"));
    assert_eq!(syms(&fx, "t.h"), vec!["struct Point"]);
    assert_eq!(
        run(&fx, &["find", "Point", "--no-update"]),
        "t.h:1 struct Point\n"
    );
    // A build without --lang reads the unchanged file again, as C++.
    summary(&fx.build(&[]));
    assert_eq!(lang(&fx, "t.h").as_deref(), Some("cpp"));
}

#[test]
fn ac3_c_symbols() {
    let src = "#ifndef GUARD_H\n#define GUARD_H\n#define MAX(a, b) ((a) > (b) ? (a) : (b))\n\
int add(int a, int b) { return a + b; }\nstruct Node { int v; };\nunion U { int i; float f; };\n\
enum Color { RED, GREEN };\ntypedef unsigned long ulong_t;\n#endif\n";
    let fx = built(&[("m.c", src)], &[]);
    let got = syms(&fx, "m.c");
    for want in [
        "macro MAX",
        "function add",
        "struct Node",
        "union U",
        "enum Color",
        "typedef ulong_t",
    ] {
        assert!(got.contains(&want.to_string()), "{want} missing in {got:?}");
    }
    assert!(!got.iter().any(|s| s.contains("GUARD_H")), "{got:?}");
}

#[test]
fn ac3_cpp_symbols_keep_declaration_kind() {
    let src = "namespace ns {\nclass Widget {\npublic:\n  void draw();\n};\n\
template <typename T> class Box { };\ntemplate <typename T> T twice(T v) { return v; }\n\
class EXPORT Exported { };\n}\n";
    let fx = built(&[("w.cpp", src)], &[]);
    assert_eq!(
        syms(&fx, "w.cpp"),
        vec![
            "namespace ns",
            "class ns.Widget",
            "method ns.Widget.draw",
            "class ns.Box",
            "function ns.twice",
            "class ns.Exported",
        ]
    );
}

#[test]
fn ac3_csharp_symbols() {
    let src = "using System;\nnamespace App {\npublic class C {\n  public int P { get; set; }\n  public void M() {}\n}\n\
public struct S { }\npublic record R(int A);\npublic interface I { }\npublic enum E { A }\n}\n";
    let fx = built(
        &[("a.cs", src), ("b.cs", "namespace A;\nclass K { }\n")],
        &[],
    );
    let got = syms(&fx, "a.cs");
    for want in [
        "namespace App",
        "class App.C",
        "property App.C.P",
        "method App.C.M",
        "struct App.S",
        "record App.R",
        "interface App.I",
        "enum App.E",
    ] {
        assert!(got.contains(&want.to_string()), "{want} missing in {got:?}");
    }
    let b = syms(&fx, "b.cs");
    assert!(b.contains(&"namespace A".to_string()), "{b:?}");
    assert!(
        b.iter()
            .any(|s| s.starts_with("class ") && s.ends_with("K")),
        "{b:?}"
    );
}

#[test]
fn ac4_method_outside_class_is_qualified() {
    let src = "class Parser {\npublic:\n  void parse();\n  void inside() {}\n};\nvoid Parser::parse() {}\n";
    let fx = built(&[("p.cpp", src)], &[]);
    let got = syms(&fx, "p.cpp");
    assert_eq!(
        got.iter().filter(|s| s.ends_with(" Parser.parse")).count(),
        2,
        "{got:?}"
    );
    assert_eq!(
        run(&fx, &["find", "Parser.parse", "--no-update"]),
        "p.cpp:3 method Parser.parse\np.cpp:6 method Parser.parse\n"
    );
}

#[test]
fn ac5_includes_and_using_links() {
    let fx = built(
        &[
            (
                "src/a.c",
                "#include \"b.h\"\n#include \"top.h\"\n#include \"deep/c.h\"\n#include <stdio.h>\n",
            ),
            ("src/b.h", "int b;\n"),
            ("top.h", "int top;\n"),
            ("lib/deep/c.h", "int c;\n"),
            ("u.cs", "using System;\nclass U { }\n"),
        ],
        &[],
    );
    let l = links(&fx, "src/a.c");
    assert_eq!(l.len(), 4, "{l:?}");
    assert!(l.iter().all(|(k, _, _)| k == "include"), "{l:?}");
    assert_eq!(l[0].2, "src/b.h");
    assert_eq!(l[1].2, "top.h");
    assert_eq!(l[2].2, "lib/deep/c.h");
    assert_eq!((l[3].1.as_str(), l[3].2.as_str()), ("<stdio.h>", ""));
    let u = links(&fx, "u.cs");
    assert_eq!(u.len(), 1, "{u:?}");
    assert_eq!((u[0].0.as_str(), u[0].1.as_str()), ("using", "System"));
}

#[test]
fn ac6_find_kind_and_outline_show_children() {
    let src = "namespace N {\nclass Foo {\npublic:\n  void m();\n};\n}\n";
    let fx = built(&[("a.cpp", src)], &[]);
    assert_eq!(
        run(&fx, &["find", "Foo", "--kind", "class", "--no-update"]),
        "a.cpp:2 class N.Foo\n"
    );
    assert_eq!(
        run(&fx, &["outline", "a.cpp", "--no-update"]),
        "1 namespace N\n  2 class Foo\n    4 method m\n"
    );
}
