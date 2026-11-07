//! The symbols of a file, from its tree-sitter syntax tree.

use tree_sitter::{Language, Node, Parser, Tree};

use crate::rules;

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

/// The parse of one file: the syntax tree, the source, and the symbols. The link reader uses the
/// tree and the source again.
pub struct Parsed<'a> {
    pub language: &'a str,
    pub tree: Tree,
    pub source: &'a [u8],
    pub symbols: Vec<Symbol>,
}

/// The parse of a file, with its symbols in line order. `None` for a language with no parser.
/// A syntax error does not stop the parse: the list has each symbol that tree-sitter finds.
pub fn symbols<'a>(language: &'a str, source: &'a [u8]) -> Option<Parsed<'a>> {
    let mut parser = Parser::new();
    parser.set_language(&grammar(language)?).ok()?;
    let tree = parser.parse(source, None)?;
    let symbols = if language == "markdown" {
        headings(tree.root_node(), source)
    } else {
        code_symbols(language, tree.root_node(), source)
    };
    Some(Parsed {
        language,
        tree,
        source,
        symbols,
    })
}

fn grammar(language: &str) -> Option<Language> {
    let grammar = match language {
        "python" => tree_sitter_python::LANGUAGE,
        "typescript" => tree_sitter_typescript::LANGUAGE_TYPESCRIPT,
        "tsx" => tree_sitter_typescript::LANGUAGE_TSX,
        "javascript" | "jsx" => tree_sitter_javascript::LANGUAGE,
        "markdown" => tree_sitter_md::LANGUAGE,
        "c" => tree_sitter_c::LANGUAGE,
        "cpp" => tree_sitter_cpp::LANGUAGE,
        "csharp" => tree_sitter_c_sharp::LANGUAGE,
        _ => return None,
    };
    Some(grammar.into())
}

/// The deepest nesting of code symbols that the index keeps. A deeper symbol is not stored, so a
/// generated file cannot make qualified names that grow with the square of the depth.
const MAX_SYMBOL_DEPTH: usize = 32;

/// One node on the walk stack: the node, its parent node, the index of the nearest symbol above
/// it, and true if an `export` statement contains it with only declarations between them.
type Item<'tree> = (Node<'tree>, Option<Node<'tree>>, Option<usize>, bool);

/// Walks the tree in source order with a stack, so a deep tree cannot overflow the thread stack.
fn code_symbols(language: &str, root: Node, source: &[u8]) -> Vec<Symbol> {
    let mut found: Vec<Symbol> = Vec::new();
    let mut depths: Vec<usize> = Vec::new();
    let mut stack: Vec<Item> = vec![(root, None, None, false)];
    while let Some((node, parent_node, parent, exported)) = stack.pop() {
        let mut next = parent;
        let depth = parent.map_or(0, |index| depths[index] + 1);
        let parent_kind = parent.map(|index| found[index].kind);
        let context = Context {
            language,
            parent_node,
            parent_kind,
            exported,
        };
        if let Some((kind, name)) =
            code_symbol(node, source, &context).filter(|_| depth < MAX_SYMBOL_DEPTH)
        {
            // A C++ method outside its class has the class in its name: `Parser.parse`.
            let (scope, name) = match name.rsplit_once('.') {
                Some((scope, last))
                    if language == "cpp" && matches!(kind, "function" | "method") =>
                {
                    (Some(scope), last.to_string())
                }
                _ => (None, name),
            };
            let local = scope.map_or_else(|| name.clone(), |scope| format!("{scope}.{name}"));
            let qualified_name = match parent {
                Some(index) => format!("{}.{local}", found[index].qualified_name),
                None => local,
            };
            // A decorated Python definition starts on its first decorator.
            let outer = parent_node.filter(|outer| outer.kind() == "decorated_definition");
            let (line, end_line) = lines(outer.unwrap_or(node));
            found.push(Symbol {
                name,
                qualified_name,
                kind,
                line,
                end_line,
                parent,
                level: None,
            });
            depths.push(depth);
            // The struct in `typedef struct {..} P;` is not a child of the typedef.
            next = if kind == "typedef" {
                parent
            } else {
                Some(found.len() - 1)
            };
        }
        let exports = node.kind() == "export_statement"
            || (exported && matches!(node.kind(), "ambient_declaration" | "lexical_declaration"));
        let mut cursor = node.walk();
        let children: Vec<Node> = node.named_children(&mut cursor).collect();
        stack.extend(
            children
                .into_iter()
                .rev()
                .map(|child| (child, Some(node), next, exports)),
        );
    }
    found
}

/// The facts about the place of a node that its symbol kind depends on.
pub struct Context<'tree> {
    language: &'tree str,
    pub parent_node: Option<Node<'tree>>,
    pub parent_kind: Option<&'static str>,
    exported: bool,
}

/// The kind and the name of a symbol node. Each language has its own rules.
fn code_symbol(node: Node, source: &[u8], context: &Context) -> Option<(&'static str, String)> {
    match context.language {
        "c" => rules::c_symbol(node, source),
        "cpp" => rules::cpp_symbol(node, source, context),
        "csharp" => rules::csharp_symbol(node, source),
        _ => script_symbol(node, source, context),
    }
}

/// The kind and the name of a Python, TypeScript, or JavaScript symbol node.
fn script_symbol(node: Node, source: &[u8], context: &Context) -> Option<(&'static str, String)> {
    let parent_node_kind = context.parent_node.map(|parent| parent.kind());
    let in_class = context.parent_kind == Some("class");
    let kind = match node.kind() {
        "function_definition" | "function_declaration" | "generator_function_declaration" => {
            if in_class {
                "method"
            } else {
                "function"
            }
        }
        "function_signature" if parent_node_kind == Some("ambient_declaration") => "function",
        "class_definition" | "class_declaration" | "abstract_class_declaration" => "class",
        "method_definition" if parent_node_kind == Some("class_body") => "method",
        "abstract_method_signature" => "method",
        "public_field_definition" | "field_definition" if has_function_value(node) => "method",
        "interface_declaration" => "interface",
        "type_alias_declaration" => "type",
        "enum_declaration" => "enum",
        "internal_module" => "namespace",
        "variable_declarator" => exported_const_kind(node, context)?,
        _ => return None,
    };
    let name = node
        .child_by_field_name("name")
        .or_else(|| node.child_by_field_name("property"))?;
    if node.kind() == "variable_declarator" && name.kind() != "identifier" {
        return None;
    }
    Some((kind, text(name, source)))
}

/// `function` for an exported `const` with a function value, `constant` for another exported
/// `const`, and `None` for each other declarator.
fn exported_const_kind(node: Node, context: &Context) -> Option<&'static str> {
    let declaration = context
        .parent_node
        .filter(|parent| parent.kind() == "lexical_declaration")?;
    let is_const = declaration
        .child_by_field_name("kind")
        .is_some_and(|keyword| keyword.kind() == "const");
    if !is_const || !context.exported {
        return None;
    }
    Some(if has_function_value(node) {
        "function"
    } else {
        "constant"
    })
}

fn has_function_value(node: Node) -> bool {
    node.child_by_field_name("value").is_some_and(|value| {
        matches!(
            value.kind(),
            "arrow_function" | "function_expression" | "function" | "generator_function"
        )
    })
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
    let mut name = text(*content, source)
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ");
    if node.kind() == "atx_heading" {
        name = without_closing_sequence(&name).to_string();
    }
    (!name.is_empty()).then_some((level, name))
}

/// The text of an ATX heading with no closing `#` sequence: `Title ##` gives `Title`, but `C#`
/// stays `C#`.
fn without_closing_sequence(name: &str) -> &str {
    let open = name.trim_end_matches('#');
    if open.is_empty() {
        open
    } else if open.ends_with(' ') {
        open.trim_end()
    } else {
        name
    }
}

/// The first and the last line of a node, from 1. A node that ends at the start of a line ends
/// on the line before it.
pub fn lines(node: Node) -> (i64, i64) {
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

pub fn text(node: Node, source: &[u8]) -> String {
    String::from_utf8_lossy(&source[node.byte_range()]).into_owned()
}
