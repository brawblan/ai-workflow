//! The symbols of a file, from its tree-sitter syntax tree.

use tree_sitter::{Language, Node, Parser};

pub struct Symbol {
    pub name: String,
    pub qualified_name: String,
    pub kind: &'static str,
    pub line: i64,
    pub end_line: i64,
    /// The index of the parent symbol in the same list. A parent comes before its children.
    pub parent: Option<usize>,
    /// The level of a Markdown heading, 1 to 6.
    pub level: Option<i64>,
}

/// The symbols of a file in line order. The list is empty for a language with no parser.
/// A syntax error does not stop the parse: the list has each symbol that tree-sitter finds.
pub fn symbols(language: &str, source: &[u8]) -> Vec<Symbol> {
    let Some(grammar) = grammar(language) else {
        return Vec::new();
    };
    let mut parser = Parser::new();
    if parser.set_language(&grammar).is_err() {
        return Vec::new();
    }
    let Some(tree) = parser.parse(source, None) else {
        return Vec::new();
    };
    if language == "markdown" {
        headings(tree.root_node(), source)
    } else {
        code_symbols(tree.root_node(), source)
    }
}

fn grammar(language: &str) -> Option<Language> {
    let grammar = match language {
        "python" => tree_sitter_python::LANGUAGE,
        "typescript" => tree_sitter_typescript::LANGUAGE_TYPESCRIPT,
        "tsx" => tree_sitter_typescript::LANGUAGE_TSX,
        "javascript" | "jsx" => tree_sitter_javascript::LANGUAGE,
        "markdown" => tree_sitter_md::LANGUAGE,
        _ => return None,
    };
    Some(grammar.into())
}

/// Walks the tree in source order with a stack, so a deep tree cannot overflow the thread stack.
fn code_symbols(root: Node, source: &[u8]) -> Vec<Symbol> {
    let mut found: Vec<Symbol> = Vec::new();
    let mut stack = vec![(root, None)];
    while let Some((node, parent)) = stack.pop() {
        let mut next = parent;
        let parent_kind = parent.map(|index: usize| found[index].kind);
        if let Some((kind, name)) = code_symbol(node, source, parent_kind) {
            let qualified_name = match parent {
                Some(index) => format!("{}.{name}", found[index].qualified_name),
                None => name.clone(),
            };
            let (line, end_line) = lines(node);
            found.push(Symbol {
                name,
                qualified_name,
                kind,
                line,
                end_line,
                parent,
                level: None,
            });
            next = Some(found.len() - 1);
        }
        let mut cursor = node.walk();
        let children: Vec<Node> = node.named_children(&mut cursor).collect();
        stack.extend(children.into_iter().rev().map(|child| (child, next)));
    }
    found
}

/// The kind and the name of a Python, TypeScript, or JavaScript symbol node.
fn code_symbol(
    node: Node,
    source: &[u8],
    parent_kind: Option<&str>,
) -> Option<(&'static str, String)> {
    let kind = match node.kind() {
        "function_definition" | "function_declaration" | "generator_function_declaration" => {
            if parent_kind == Some("class") {
                "method"
            } else {
                "function"
            }
        }
        "class_definition" | "class_declaration" | "abstract_class_declaration" => "class",
        "method_definition" | "abstract_method_signature" => "method",
        "interface_declaration" => "interface",
        "type_alias_declaration" => "type",
        "enum_declaration" => "enum",
        "variable_declarator" => exported_const_kind(node)?,
        _ => return None,
    };
    let name = node.child_by_field_name("name")?;
    if node.kind() == "variable_declarator" && name.kind() != "identifier" {
        return None;
    }
    Some((kind, text(name, source)))
}

/// `function` for an exported `const` with a function value, `constant` for another exported
/// `const`, and `None` for each other declarator.
fn exported_const_kind(node: Node) -> Option<&'static str> {
    let declaration = node
        .parent()
        .filter(|parent| parent.kind() == "lexical_declaration")?;
    let is_const = declaration
        .child_by_field_name("kind")
        .is_some_and(|keyword| keyword.kind() == "const");
    let exported = declaration
        .parent()
        .is_some_and(|parent| parent.kind() == "export_statement");
    if !is_const || !exported {
        return None;
    }
    let value = node.child_by_field_name("value").map(|value| value.kind());
    match value {
        Some("arrow_function" | "function_expression" | "function") => Some("function"),
        _ => Some("constant"),
    }
}

/// The Markdown headings. A heading ends on the line before the next heading of the same or a
/// higher level. Its parent is the nearest heading before it with a lower level.
fn headings(root: Node, source: &[u8]) -> Vec<Symbol> {
    let mut found: Vec<Symbol> = Vec::new();
    let mut open: Vec<usize> = Vec::new();
    let last_line = lines(root).1;
    let mut stack = vec![root];
    while let Some(node) = stack.pop() {
        if let Some((level, name)) = heading(node, source) {
            while let Some(&index) = open
                .last()
                .filter(|&&index| found[index].level >= Some(level))
            {
                found[index].end_line = lines(node).0 - 1;
                open.pop();
            }
            found.push(Symbol {
                qualified_name: name.clone(),
                name,
                kind: "heading",
                line: lines(node).0,
                end_line: last_line,
                parent: open.last().copied(),
                level: Some(level),
            });
            open.push(found.len() - 1);
            continue;
        }
        let mut cursor = node.walk();
        let children: Vec<Node> = node.named_children(&mut cursor).collect();
        stack.extend(children.into_iter().rev());
    }
    found
}

/// The level and the text of a heading node. An empty heading has no symbol.
fn heading(node: Node, source: &[u8]) -> Option<(i64, String)> {
    let mut cursor = node.walk();
    let children: Vec<Node> = node.named_children(&mut cursor).collect();
    let (level, content) = match node.kind() {
        "atx_heading" => {
            let marker = children.first()?.kind();
            let digit = marker.strip_prefix("atx_h")?.strip_suffix("_marker")?;
            (digit.parse().ok()?, children.get(1)?)
        }
        "setext_heading" => {
            let underline = children.last()?.kind();
            (
                if underline == "setext_h1_underline" {
                    1
                } else {
                    2
                },
                children.first()?,
            )
        }
        _ => return None,
    };
    let name = text(*content, source).trim().to_string();
    (!name.is_empty()).then_some((level, name))
}

/// The first and the last line of a node, from 1. A node that ends at the start of a line ends
/// on the line before it.
fn lines(node: Node) -> (i64, i64) {
    let start = node.start_position().row;
    let end = node.end_position();
    let end_row = if end.column == 0 && end.row > start {
        end.row - 1
    } else {
        end.row
    };
    let to_line = |row: usize| i64::try_from(row + 1).unwrap_or(i64::MAX);
    (to_line(start), to_line(end_row))
}

fn text(node: Node, source: &[u8]) -> String {
    String::from_utf8_lossy(&source[node.byte_range()]).into_owned()
}
