//! The links of a file: imports, includes, and relative Markdown links. Each language has its own reader.

use tree_sitter::Node;

use crate::symbols::{Parsed, lines, text};

pub struct Link {
    pub line: i64,
    pub kind: &'static str,
    /// The target as the file writes it. A Python `from M import a` gives `M.a`.
    pub target: String,
}

/// The links of a parsed file in source order.
pub fn links(parsed: &Parsed) -> Vec<Link> {
    let reader: fn(Node, &[u8], &mut Vec<Link>) = match parsed.language {
        "python" => python,
        "typescript" | "tsx" | "javascript" | "jsx" => script,
        "markdown" => markdown,
        "c" | "cpp" => include,
        "csharp" => using,
        _ => return Vec::new(),
    };
    let mut found = Vec::new();
    let mut stack = vec![parsed.tree.root_node()];
    while let Some(node) = stack.pop() {
        reader(node, parsed.source, &mut found);
        let mut cursor = node.walk();
        let children: Vec<Node> = node.named_children(&mut cursor).collect();
        stack.extend(children.into_iter().rev());
    }
    found
}

fn push(found: &mut Vec<Link>, node: Node, kind: &'static str, target: String) {
    if !target.is_empty() {
        let line = lines(node).0;
        found.push(Link { line, kind, target });
    }
}

/// `import a.b` gives `a.b`. `from m import a, b` gives `m.a` and `m.b`, and `from m import *`
/// gives `m`. The resolver uses `m` if `m.a` is not a module.
fn python(node: Node, source: &[u8], found: &mut Vec<Link>) {
    let mut cursor = node.walk();
    let names: Vec<String> = node
        .children_by_field_name("name", &mut cursor)
        .filter_map(|name| {
            let dotted = match name.kind() {
                "aliased_import" => name.child_by_field_name("name")?,
                _ => name,
            };
            Some(text(dotted, source))
        })
        .collect();
    match node.kind() {
        "import_statement" => {
            for name in names {
                push(found, node, "import", name);
            }
        }
        "import_from_statement" => {
            let Some(module) = node.child_by_field_name("module_name") else {
                return;
            };
            let module = text(module, source);
            let separator = if module.ends_with('.') { "" } else { "." };
            if names.is_empty() {
                push(found, node, "import", module);
                return;
            }
            for name in names {
                push(found, node, "import", format!("{module}{separator}{name}"));
            }
        }
        _ => {}
    }
}

/// `import` and `export ... from` with a source, and `require()` and `import()` with a string.
fn script(node: Node, source: &[u8], found: &mut Vec<Link>) {
    let (kind, string) = match node.kind() {
        "import_statement" => ("import", node.child_by_field_name("source")),
        "export_statement" => ("export", node.child_by_field_name("source")),
        "call_expression" => {
            let callee = node.child_by_field_name("function");
            let kind = match callee.map(|callee| (callee.kind(), text(callee, source))) {
                Some(("identifier", name)) if name == "require" => "require",
                Some(("import", _)) => "import",
                _ => return,
            };
            let argument = node
                .child_by_field_name("arguments")
                .and_then(|arguments| arguments.named_child(0));
            (kind, argument)
        }
        _ => return,
    };
    if let Some(string) = string.filter(|string| string.kind() == "string") {
        let quoted = text(string, source);
        let target = quoted.get(1..quoted.len().saturating_sub(1)).unwrap_or("");
        push(found, node, kind, target.to_string());
    }
}

/// `#include "a.h"` gives `a.h`. `#include <a.h>` gives `<a.h>`, so the resolver can tell them
/// apart: only a quoted include can be a file of the repo.
fn include(node: Node, source: &[u8], found: &mut Vec<Link>) {
    if node.kind() != "preproc_include" {
        return;
    }
    let Some(path) = node.child_by_field_name("path") else {
        return;
    };
    let written = text(path, source);
    let target = match path.kind() {
        "string_literal" => written.trim_matches('"'),
        "system_lib_string" => written.as_str(),
        _ => return,
    };
    push(found, node, "include", target.trim().to_string());
}

/// `using A.B;` gives `A.B`. `using static A.B;` gives `A.B`. `using X = A.B;` gives `A.B`.
fn using(node: Node, source: &[u8], found: &mut Vec<Link>) {
    if node.kind() != "using_directive" {
        return;
    }
    let mut cursor = node.walk();
    if let Some(name) = node.named_children(&mut cursor).last() {
        push(
            found,
            node,
            "using",
            text(name, source).split_whitespace().collect(),
        );
    }
}

/// The relative links of inline text and of link reference definitions, with no `#anchor`.
fn markdown(node: Node, source: &[u8], found: &mut Vec<Link>) {
    let first_line = lines(node).0;
    let destinations = match node.kind() {
        "inline" | "pipe_table_cell" => inline_destinations(&text(node, source)),
        "link_reference_definition" => {
            let mut cursor = node.walk();
            let children: Vec<Node> = node.named_children(&mut cursor).collect();
            children
                .into_iter()
                .filter(|child| child.kind() == "link_destination")
                .map(|child| (lines(child).0 - first_line, text(child, source)))
                .collect()
        }
        _ => return,
    };
    for (offset, destination) in destinations {
        let destination = destination.trim_start_matches('<').trim_end_matches('>');
        let path = destination.split(['#', '?']).next().unwrap_or("");
        let has_scheme = path
            .split('/')
            .next()
            .is_some_and(|part| part.contains(':'));
        if !path.is_empty() && !path.starts_with('/') && !has_scheme {
            let line = first_line + offset;
            let (kind, target) = ("link", path.to_string());
            found.push(Link { line, kind, target });
        }
    }
}

/// The destination of each `[text](destination)` link, with its line offset in the text. A code
/// span has no links.
fn inline_destinations(text: &str) -> Vec<(i64, String)> {
    let bytes = text.as_bytes();
    let mut found = Vec::new();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'`' {
            let run = bytes[index..]
                .iter()
                .take_while(|&&byte| byte == b'`')
                .count();
            let fence = &text[index..index + run];
            let close = text[index + run..].find(fence);
            index += run + close.map_or(0, |close| close + run);
            continue;
        }
        if bytes[index..].starts_with(b"](") {
            let rest = text[index + 2..].trim_start();
            let end = if rest.starts_with('<') {
                rest.find('>').map_or(rest.len(), |end| end + 1)
            } else {
                rest.find(|c: char| c == ')' || c.is_whitespace())
                    .unwrap_or(rest.len())
            };
            let offset = text[..index].matches('\n').count();
            found.push((i64::try_from(offset).unwrap_or(0), rest[..end].to_string()));
        }
        index += 1;
    }
    found
}
