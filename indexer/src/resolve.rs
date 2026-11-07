//! Resolves the target of a link to a file of the repo.

use std::collections::{HashMap, HashSet};

use crate::lang;

/// The extensions that a TypeScript or JavaScript import can leave out, in the order of the try.
const SCRIPT_EXTENSIONS: &[&str] = &[
    ".ts", ".tsx", ".d.ts", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs",
];

/// The files of the repo, and the Python modules that each file can be.
pub struct Resolver<'a> {
    files: HashSet<&'a str>,
    /// The dotted names of each Python file: each name with two or more parts, the name from the
    /// repo root, and the name from a top package (a folder with `__init__.py` in a folder with
    /// none). Thus `tools/logging.py` is not `logging`, and the standard `logging` stays
    /// external. A package is its `__init__.py`.
    modules: HashMap<String, Vec<&'a str>>,
}

impl<'a> Resolver<'a> {
    pub fn new(paths: impl IntoIterator<Item = &'a str>) -> Self {
        let files: HashSet<&str> = paths.into_iter().collect();
        let mut modules: HashMap<String, Vec<&str>> = HashMap::new();
        let packages: HashSet<&str> = files
            .iter()
            .filter_map(|path| {
                let stem = path
                    .strip_suffix("__init__.py")
                    .or_else(|| path.strip_suffix("__init__.pyi"));
                stem.map(|stem| stem.trim_end_matches('/'))
            })
            .collect();
        for &path in &files {
            let Some(stem) = path
                .strip_suffix(".py")
                .or_else(|| path.strip_suffix(".pyi"))
            else {
                continue;
            };
            let parts: Vec<&str> = stem.split('/').collect();
            let parts = match parts.split_last() {
                Some((&"__init__", package)) => package,
                _ => &parts[..],
            };
            let is_root = |start: usize| {
                let package = parts[..=start].join("/");
                start == 0
                    || parts.len() - start > 1
                    || (packages.contains(package.as_str())
                        && !packages.contains(parts[..start].join("/").as_str()))
            };
            for start in (0..parts.len()).filter(|&start| is_root(start)) {
                modules
                    .entry(parts[start..].join("."))
                    .or_default()
                    .push(path);
            }
        }
        Self { files, modules }
    }

    /// The repo path of the target of a link in the file `from`, or `None`.
    pub fn resolve(&self, from: &str, target: &str) -> Option<String> {
        match lang::language(from)? {
            "python" if target.starts_with('.') => self.python_relative(from, target),
            "python" => self.python_module(from, target),
            "markdown" => self.file(&join(from, target)?),
            _ if target.starts_with("./") || target.starts_with("../") => {
                self.script(&join(from, target)?)
            }
            _ => None,
        }
    }

    /// The file of a dotted module name. If the name is not a module, its parent can be:
    /// `from m import a` imports `a` from `m`.
    pub fn python_module(&self, from: &str, name: &str) -> Option<String> {
        let parent = name.rsplit_once('.').map(|(parent, _)| parent);
        self.module(from, name)
            .or_else(|| self.module(from, parent?))
    }

    /// The file of a dotted module name next to `from`, else the best file from a root: the one
    /// nearest to `from`.
    pub fn module(&self, from: &str, name: &str) -> Option<String> {
        let sibling = join(from, &name.replace('.', "/"))?;
        let siblings = [format!("{sibling}.py"), format!("{sibling}/__init__.py")];
        if let Some(path) = siblings.iter().find_map(|path| self.file(path)) {
            return Some(path);
        }
        let paths = self.modules.get(name)?;
        // The nearest path wins. The first path in text order wins a tie.
        let near = |a: &&&str, b: &&&str| {
            let order = common_prefix(from, a).cmp(&common_prefix(from, b));
            order.then_with(|| b.cmp(a))
        };
        paths.iter().max_by(near).map(|path| (*path).to_string())
    }

    fn python_relative(&self, from: &str, target: &str) -> Option<String> {
        let name = target.trim_start_matches('.');
        let up = "../".repeat(target.len() - name.len() - 1);
        let parts: Vec<&str> = name.split('.').filter(|part| !part.is_empty()).collect();
        let try_parts = |parts: &[&str]| {
            let base = join(from, &format!("./{up}{}", parts.join("/")))?;
            let base = base.trim_end_matches('/');
            [format!("{base}.py"), format!("{base}/__init__.py")]
                .into_iter()
                .find_map(|path| self.file(&path))
        };
        try_parts(&parts).or_else(|| try_parts(parts.split_last()?.1))
    }

    fn script(&self, base: &str) -> Option<String> {
        let mut paths = vec![base.to_string()];
        if let Some(stem) = [".js", ".jsx", ".mjs", ".cjs"]
            .iter()
            .find_map(|extension| base.strip_suffix(extension))
        {
            paths.extend(
                [".ts", ".tsx", ".mts", ".cts"].map(|extension| format!("{stem}{extension}")),
            );
        }
        for extension in SCRIPT_EXTENSIONS {
            paths.push(format!("{base}{extension}"));
            paths.push(format!("{base}/index{extension}"));
        }
        paths.into_iter().find_map(|path| self.file(&path))
    }

    fn file(&self, path: &str) -> Option<String> {
        self.files.contains(path).then(|| path.to_string())
    }
}

/// The repo path of `target` from the folder of the file `from`, or `None` above the root.
fn join(from: &str, target: &str) -> Option<String> {
    let mut parts: Vec<&str> = from.split('/').collect();
    parts.pop();
    for part in target.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                parts.pop()?;
            }
            other => parts.push(other),
        }
    }
    Some(parts.join("/"))
}

fn common_prefix(a: &str, b: &str) -> usize {
    a.bytes().zip(b.bytes()).take_while(|(x, y)| x == y).count()
}
