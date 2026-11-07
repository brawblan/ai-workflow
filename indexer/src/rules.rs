//! The symbol rules of C, C++, C#, and Rust. Each language has its own table of node kinds.

use tree_sitter::Node;

use crate::symbols::{Context, text};

/// The nesting of declarators that the name search follows: `*p`, `(*f)(int)`, `a[3]`.
const MAX_DECLARATOR_DEPTH: usize = 16;

/// The kind and the name of a C symbol node.
pub fn c_symbol(node: Node, source: &[u8]) -> Option<(&'static str, String)> {
    let kind = match node.kind() {
        "function_definition" => "function",
        "struct_specifier" => "struct",
        "union_specifier" => "union",
        "enum_specifier" => "enum",
        "type_definition" => "typedef",
        "preproc_def" | "preproc_function_def" => "macro",
        _ => return None,
    };
    let name = match kind {
        // A specifier with no body is a use of the type, not a declaration.
        "struct" | "union" | "enum" => {
            node.child_by_field_name("body")?;
            scoped_name(node.child_by_field_name("name")?, source)
        }
        "macro" => {
            node.child_by_field_name("value")?;
            text(node.child_by_field_name("name")?, source)
        }
        _ => declarator_name(node.child_by_field_name("declarator")?, source)?,
    };
    Some((kind, name))
}

/// The kind and the name of a C++ symbol node: the C symbols, and the rules below.
pub fn cpp_symbol(node: Node, source: &[u8], context: &Context) -> Option<(&'static str, String)> {
    let in_class = matches!(context.parent_kind, Some("class" | "struct" | "union"));
    match node.kind() {
        "namespace_definition" => {
            let name = node.child_by_field_name("name")?;
            Some(("namespace", scoped_name(name, source)))
        }
        "class_specifier" => {
            node.child_by_field_name("body")?;
            let name = node.child_by_field_name("name")?;
            Some(("class", scoped_name(name, source)))
        }
        "function_definition" => {
            let declarator = node.child_by_field_name("declarator")?;
            if let Some(kind) = exported_type_kind(node, declarator) {
                return Some((kind, text(declarator, source)));
            }
            let name = declarator_name(declarator, source)?;
            let kind = if in_class || name.contains('.') {
                "method"
            } else {
                "function"
            };
            Some((kind, name))
        }
        // A method that the class declares and a .cpp file defines.
        "field_declaration" if in_class => {
            let declarator = node.child_by_field_name("declarator")?;
            // A function pointer, `void (*cb)(int)`, is a field, not a method.
            let plain = declarator.kind() == "function_declarator"
                && declarator
                    .child_by_field_name("declarator")
                    .is_some_and(|inner| inner.kind() != "parenthesized_declarator");
            plain
                .then(|| declarator_name(declarator, source))?
                .map(|name| ("method", name))
        }
        _ => c_symbol(node, source),
    }
}

/// `class EXPORT Name {...}` has a macro between `class` and the name. The grammar then reads the
/// class as a function whose type is `class EXPORT` and whose name is `Name`.
fn exported_type_kind(node: Node, declarator: Node) -> Option<&'static str> {
    let specifier = node.child_by_field_name("type")?;
    if declarator.kind() != "identifier" || specifier.child_by_field_name("body").is_some() {
        return None;
    }
    match specifier.kind() {
        "class_specifier" => Some("class"),
        "struct_specifier" => Some("struct"),
        _ => None,
    }
}

/// The kind and the name of a C# symbol node.
pub fn csharp_symbol(node: Node, source: &[u8]) -> Option<(&'static str, String)> {
    let kind = match node.kind() {
        "namespace_declaration" | "file_scoped_namespace_declaration" => "namespace",
        "class_declaration" => "class",
        "struct_declaration" => "struct",
        "record_declaration" | "record_struct_declaration" => "record",
        "interface_declaration" => "interface",
        "enum_declaration" => "enum",
        "method_declaration" => "method",
        "property_declaration" => "property",
        _ => return None,
    };
    Some((kind, text(node.child_by_field_name("name")?, source)))
}

/// The kind and the name of a Rust symbol node. An item in an `impl` block gets the type in its
/// name, so `impl Parser { fn parse() }` gives `Parser.parse`. A trait is the parent of its items.
pub fn rust_symbol(node: Node, source: &[u8], context: &Context) -> Option<(&'static str, String)> {
    let block = context
        .parent_node
        .filter(|parent| parent.kind() == "declaration_list")
        .and_then(|parent| parent.parent());
    let member = block.is_some_and(|block| matches!(block.kind(), "impl_item" | "trait_item"));
    let kind = match node.kind() {
        "function_item" | "function_signature_item" if member => "method",
        "function_item" | "function_signature_item" => "function",
        "struct_item" => "struct",
        "enum_item" => "enum",
        "union_item" => "union",
        "trait_item" => "trait",
        // `mod a;` is a link. Only a module with a body is a symbol.
        "mod_item" => {
            node.child_by_field_name("body")?;
            "mod"
        }
        "const_item" => "constant",
        "static_item" => "static",
        "type_item" => "type",
        "macro_definition" => "macro",
        _ => return None,
    };
    let name = text(node.child_by_field_name("name")?, source);
    let owner = block
        .filter(|block| block.kind() == "impl_item")
        .and_then(|block| block.child_by_field_name("type"));
    Some(match owner {
        Some(owner) => (kind, format!("{}.{name}", impl_type(owner, source))),
        None => (kind, name),
    })
}

/// The name of the type of an `impl` block, with no generic parameters and no path:
/// `impl<T> a::Box<T>` gives `Box`.
fn impl_type(mut node: Node, source: &[u8]) -> String {
    for _ in 0..MAX_DECLARATOR_DEPTH {
        let inner = match node.kind() {
            "generic_type" | "reference_type" | "pointer_type" => node.child_by_field_name("type"),
            "scoped_type_identifier" => node.child_by_field_name("name"),
            _ => None,
        };
        match inner {
            Some(inner) => node = inner,
            None => break,
        }
    }
    text(node, source)
}

/// The name that a declarator declares. `Parser::parse` gives `Parser.parse`.
fn declarator_name(mut node: Node, source: &[u8]) -> Option<String> {
    for _ in 0..MAX_DECLARATOR_DEPTH {
        match node.kind() {
            "identifier" | "field_identifier" | "type_identifier" | "destructor_name"
            | "operator_name" => return Some(text(node, source)),
            "qualified_identifier" => return Some(scoped_name(node, source)),
            _ => {
                node = node
                    .child_by_field_name("declarator")
                    .or_else(|| node.named_child(0))?;
            }
        }
    }
    None
}

/// The text of a name with `.` for `::`, and no leading `::`.
fn scoped_name(node: Node, source: &[u8]) -> String {
    let name = if node.kind() == "template_type" {
        node.child_by_field_name("name").unwrap_or(node)
    } else {
        node
    };
    without_arguments(&text(name, source))
        .replace("::", ".")
        .trim_start_matches('.')
        .to_string()
}

/// The text with no `<...>` template arguments: `Box<T>::put` gives `Box::put`.
fn without_arguments(name: &str) -> String {
    let mut depth = 0usize;
    name.chars()
        .filter(|&c| {
            match c {
                '<' => depth += 1,
                '>' => depth = depth.saturating_sub(1),
                _ => return depth == 0,
            }
            false
        })
        .collect()
}
