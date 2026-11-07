//! Tests of the symbols: each language, qualified names, syntax errors, and updates
//! (AC 3, 4, 7 and the schema version).

mod common;

use common::{Fixture, summary};

/// One line per symbol: `path:line-end kind qualified_name [level] parent_or_-`.
fn dump(fx: &Fixture) -> String {
    let conn = fx.conn();
    let mut statement = conn
        .prepare(
            "SELECT s.path, s.line, s.end_line, s.kind, s.qualified_name, s.level, p.qualified_name
             FROM symbols s LEFT JOIN symbols p ON s.parent = p.id
             ORDER BY s.path, s.line, s.id",
        )
        .unwrap();
    let lines: Vec<String> = statement
        .query_map([], |r| {
            let level: Option<i64> = r.get(5)?;
            let parent: Option<String> = r.get(6)?;
            Ok(format!(
                "{}:{}-{} {} {} [{}] {}",
                r.get::<_, String>(0)?,
                r.get::<_, i64>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, String>(4)?,
                level.map_or("-".to_string(), |n| n.to_string()),
                parent.unwrap_or("-".to_string()),
            ))
        })
        .unwrap()
        .map(Result::unwrap)
        .collect();
    lines.join("\n")
}

fn built(files: &[(&str, &str)]) -> Fixture {
    let fx = Fixture::new("symbols");
    for (path, text) in files {
        fx.write(path, text.as_bytes());
    }
    assert_eq!(summary(&fx.build(&[])).0, files.len());
    fx
}

fn names(fx: &Fixture) -> Vec<String> {
    let conn = fx.conn();
    let mut st = conn
        .prepare("SELECT qualified_name FROM symbols ORDER BY line")
        .unwrap();
    st.query_map([], |r| r.get(0))
        .unwrap()
        .map(Result::unwrap)
        .collect()
}

const PY: &str = "import os

def top():
    def inner():
        pass
    return inner

class Parser:
    @staticmethod
    def parse(x):
        def helper():
            pass
        return helper

    async def run(self):
        pass
";

#[test]
fn ac3_ac4_python_symbols() {
    let fx = built(&[("p.py", PY)]);
    assert_eq!(
        dump(&fx),
        "p.py:3-6 function top [-] -
p.py:4-5 function top.inner [-] top
p.py:8-16 class Parser [-] -
p.py:10-13 method Parser.parse [-] Parser
p.py:11-12 function Parser.parse.helper [-] Parser.parse
p.py:15-16 method Parser.run [-] Parser"
    );
}

const TS: &str = "export function f() {}
function* gen() {}
export abstract class Shape {
  abstract area(): number;
  name() { return 1; }
}
export interface I { a: number }
export type T = string;
export enum E { A }
export const arrow = () => 1;
export const fe = function () {};
export const A = 1, B = 2;
const hidden = 1;
export let v = 1;
export const { a } = x;
export default class Def {}
";

#[test]
fn ac3_ac4_typescript_symbols() {
    let fx = built(&[
        ("t.ts", TS),
        ("x.tsx", "export const D = (): any => <b/>;\n"),
    ]);
    assert_eq!(
        dump(&fx),
        "t.ts:1-1 function f [-] -
t.ts:2-2 function gen [-] -
t.ts:3-6 class Shape [-] -
t.ts:4-4 method Shape.area [-] Shape
t.ts:5-5 method Shape.name [-] Shape
t.ts:7-7 interface I [-] -
t.ts:8-8 type T [-] -
t.ts:9-9 enum E [-] -
t.ts:10-10 function arrow [-] -
t.ts:11-11 function fe [-] -
t.ts:12-12 constant A [-] -
t.ts:12-12 constant B [-] -
t.ts:16-16 class Def [-] -
x.tsx:1-1 function D [-] -"
    );
}

#[test]
fn ac3_ac4_javascript_symbols() {
    let jsx = "export const C = () => <div>hi</div>;
export class K {
  m() { return 1; }
}
export function g() {}
export const N = 2;
";
    let fx = built(&[
        ("j.jsx", jsx),
        ("k.js", "export function h() {}\nlet z = 1;\n"),
    ]);
    assert_eq!(
        dump(&fx),
        "j.jsx:1-1 function C [-] -
j.jsx:2-4 class K [-] -
j.jsx:3-3 method K.m [-] K
j.jsx:5-5 function g [-] -
j.jsx:6-6 constant N [-] -
k.js:1-1 function h [-] -"
    );
}

#[test]
fn ac3_ac4_markdown_headings() {
    let md = "# A
text
```
# not
```
## B
### C
Setext
======
## D
Sub
---
#
###### Deep
end
";
    let fx = built(&[("m.md", md)]);
    assert_eq!(
        dump(&fx),
        "m.md:1-7 heading A [1] -
m.md:6-7 heading B [2] A
m.md:7-7 heading C [3] B
m.md:8-15 heading Setext [1] -
m.md:10-10 heading D [2] Setext
m.md:11-15 heading Sub [2] Setext
m.md:14-15 heading Deep [6] Sub"
    );
}

#[test]
fn ac7_python_syntax_error_keeps_the_other_symbols() {
    let src =
        "class A:\n    pass\ndef broken(:\n    x\nclass After:\n    pass\ndef tail():\n    pass\n";
    let fx = built(&[("b.py", src)]);
    let found = names(&fx);
    for want in ["A", "After", "tail"] {
        assert!(found.iter().any(|n| n == want), "{want} in {found:?}");
    }
}

#[test]
fn ac7_typescript_syntax_error_keeps_the_other_symbols() {
    let src = "export function ok() {}\nconst = ;\nlet 1x = ;\nexport function after() {}\n";
    let fx = built(&[("b.ts", src)]);
    let found = names(&fx);
    for want in ["ok", "after"] {
        assert!(found.iter().any(|n| n == want), "{want} in {found:?}");
    }
}

#[test]
fn changed_file_has_no_duplicate_symbols_and_removed_file_has_none() {
    let fx = built(&[
        ("a.py", "def one():\n    pass\n"),
        ("b.py", "def b():\n    pass\n"),
    ]);
    for (n, name) in [(1_750_000_000, "two"), (1_760_000_000, "three")] {
        fx.write("a.py", format!("def {name}():\n    pass\n").as_bytes());
        fx.set_mtime("a.py", n);
        assert_eq!(summary(&fx.build(&[])), (1, 1, 0));
    }
    assert_eq!(
        dump(&fx),
        "a.py:1-2 function three [-] -\nb.py:1-2 function b [-] -"
    );
    fx.remove("b.py");
    assert_eq!(summary(&fx.build(&[])), (0, 1, 1));
    assert_eq!(dump(&fx), "a.py:1-2 function three [-] -");
}

#[test]
fn touched_file_keeps_its_symbol_rows() {
    let fx = built(&[("a.py", "def one():\n    pass\n")]);
    let id = |fx: &Fixture| -> i64 {
        fx.conn()
            .query_row("SELECT id FROM symbols", [], |r| r.get(0))
            .unwrap()
    };
    let before = id(&fx);
    fx.set_mtime("a.py", 1_750_000_000);
    assert_eq!(summary(&fx.build(&[])), (0, 1, 0));
    assert_eq!(id(&fx), before);
}

#[test]
fn schema_version_1_index_is_made_again_as_version_2() {
    let fx = built(&[("a.py", "def one():\n    pass\n"), ("b.md", "# H\n")]);
    fx.conn()
        .execute(
            "UPDATE meta SET value = '1' WHERE key = 'schema_version'",
            [],
        )
        .unwrap();
    assert_eq!(summary(&fx.build(&[])), (2, 0, 0));
    let version: String = fx
        .conn()
        .query_row(
            "SELECT value FROM meta WHERE key = 'schema_version'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(version, "2");
    assert_eq!(
        dump(&fx),
        "a.py:1-2 function one [-] -\nb.md:1-1 heading H [1] -"
    );
}

#[test]
fn deep_tree_does_not_crash_the_build() {
    let src = format!("x = {}{}\n", "[".repeat(5000), "]".repeat(5000));
    let fx = Fixture::new("deep");
    fx.write("deep.js", src.as_bytes());
    fx.write(
        "deep2.js",
        format!("y = {}1{}\n", "(".repeat(5000), ")".repeat(5000)).as_bytes(),
    );
    assert_eq!(summary(&fx.build(&[])), (2, 0, 0));
}

#[test]
fn unknown_language_has_no_symbols() {
    let fx = built(&[("a.rb", "def f; end\n")]);
    assert_eq!(fx.paths(), vec!["a.rb"]);
    assert_eq!(dump(&fx), "");
}
