"""MkDocs hook: point each relative link to a file that is not on the site to GitHub.

The site content is a mirror of the repo folders (symlinks in website/content/). A link from a
mirrored page to a file outside the mirror, for example ../../README.md or ../.cornerstone/, would
break on the site. This hook rewrites such a link to the file on GitHub.
"""

import os
import posixpath
import re
from collections.abc import Callable
from pathlib import Path

REPO_URL = "https://github.com/brawblan/ai-workflow"
BRANCH = "main"
LINK = re.compile(r"(\]\()([^)\s]+)(\))")
EVALS_MARKER = "<!-- evals-index -->"
EVALS_PAGE = "evals/README.md"
RESULT_TITLE = re.compile(r"^# Eval results: (\S+)\s*$")
RESULT_HARNESS = re.compile(r"^Harness: `([^`]+)`\.\s*$")
RESULT_MODEL = re.compile(r"^Model: `([^`]+)`\. Date: (\d{4}-\d{2}-\d{2})\.")
RESULT_STAMP = re.compile(r"^(\d{8}-\d{6})-")
CONFIG_HARNESS = re.compile(r"^harness:\s*([^\s#]+)", re.MULTILINE)
EXTERNAL = re.compile(r"^([a-z][a-z0-9+.-]*:|#|/)", re.IGNORECASE)


def github_url(repo_path: str, anchor: str, is_dir: bool) -> str:
    """Return the GitHub URL of a repo path, with the anchor if there is one."""
    kind = "tree" if is_dir else "blob"
    url = f"{REPO_URL}/{kind}/{BRANCH}/{repo_path}" if repo_path else REPO_URL
    return f"{url}#{anchor}" if anchor else url


def rewrite_links(markdown: str, page_uri: str, page_repo_path: str, repo_root: str,
                  on_site: Callable[[str], bool]) -> str:
    """Rewrite each relative link that on_site rejects to a GitHub URL.

    page_uri is the page path in the site content. page_repo_path is the same page in the repo.
    on_site gets a site path and returns True if the site has that file or folder.
    """

    def replace(match: re.Match[str]) -> str:
        target = match.group(2)
        if EXTERNAL.match(target):
            return match.group(0)
        path, _, anchor = target.partition("#")
        site_path = posixpath.normpath(posixpath.join(posixpath.dirname(page_uri), path))
        if on_site(site_path):
            return match.group(0)
        repo_path = posixpath.normpath(posixpath.join(posixpath.dirname(page_repo_path), path))
        if repo_path.startswith(".."):
            return match.group(0)  # outside the repo: leave it for MkDocs to report
        repo_path = "" if repo_path == "." else repo_path
        is_dir = os.path.isdir(os.path.join(repo_root, repo_path))
        return f"{match.group(1)}{github_url(repo_path, anchor, is_dir)}{match.group(3)}"

    return LINK.sub(replace, markdown)


def default_harness(evals_dir: Path) -> str:
    """Return the harness of the repo config, or "" if the config has none.

    A result file from before the "Harness:" line came from the harness of the repo config.
    """
    config = evals_dir.parent / ".cornerstone" / "config.yaml"
    if not config.is_file():
        return ""
    found = CONFIG_HARNESS.search(config.read_text(encoding="utf-8"))
    return found.group(1) if found else ""


def read_result(path: Path, fallback_harness: str) -> tuple[str, dict[str, str]] | None:
    """Return the component and the fields of one result file, or None if it is not a result.

    `stone eval` writes the title, a blank line, an optional "Harness:" line, and the "Model:"
    line. The body is the rest of the file.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    title = RESULT_TITLE.match(lines[0]) if lines else None
    if not title:
        return None
    index = 2
    harness = RESULT_HARNESS.match(lines[index]) if len(lines) > index else None
    if harness:
        index += 1
    model = RESULT_MODEL.match(lines[index]) if len(lines) > index else None
    if not model:
        return None
    stamp = RESULT_STAMP.match(path.name)
    return title.group(1), {
        "harness": harness.group(1) if harness else fallback_harness,
        "model": model.group(1),
        "date": model.group(2),
        "stamp": stamp.group(1) if stamp else model.group(2),
        "name": path.name,
        "body": "\n".join(lines[index + 1:]).strip(),
    }


def evals_index(evals_dir: Path) -> str:
    """Return Markdown for the evals page: one section for each component, newest run first.

    The result files in evals/results/ are the data. Each starts with the "# Eval results: <id>"
    line and the "Model: `<model>`. Date: <date>." line that `stone eval` writes. A run on a
    harness other than the repo default also has a "Harness:" line. The page shows the latest run
    of each harness. A run of many models writes one file for each model with the same time stamp,
    so the page shows each of them. The links are relative to evals/README.md.
    """
    fallback = default_harness(evals_dir)
    runs: dict[str, list[dict[str, str]]] = {}
    for path in sorted((evals_dir / "results").glob("*.md")):
        found = read_result(path, fallback)
        if found:
            runs.setdefault(found[0], []).append(found[1])
    if not runs:
        return "No eval results yet."
    out: list[str] = []
    for component in sorted(runs):
        folder = component.replace(".", "-")
        out += [f"## {component}", ""]
        links = ["[Result files](results/)"]
        if (evals_dir / folder / "scenarios.yaml").is_file():
            links.insert(0, f"[Scenarios](./{folder}/scenarios.yaml)")
            links.insert(1, f"[Eval folder](./{folder}/)")
        out += [" · ".join(links), ""]
        ordered = sorted(runs[component], reverse=True,
                         key=lambda r: (r["stamp"], r["date"], r["model"], r["name"]))
        harnesses = sorted({r["harness"] for r in ordered}, key=lambda h: (h != fallback, h))
        latest: list[dict[str, str]] = []
        for harness in harnesses:
            mine = [r for r in ordered if r["harness"] == harness]
            latest += sorted((r for r in mine if r["stamp"] == mine[0]["stamp"]),
                             key=lambda r: r["model"])
        for run in latest:
            on = f" on `{run['harness']}`" if len(harnesses) > 1 and run["harness"] else ""
            out += [f"Latest run{on}: {run['date']}, model `{run['model']}`. "
                    f"[Result file](results/{run['name']}).", "", run["body"], ""]
        earlier = [r for r in ordered if r not in latest]
        if earlier:
            out += ["Earlier runs:", ""]
            for run in earlier:
                on = f" on `{run['harness']}`" if len(harnesses) > 1 and run["harness"] else ""
                out.append(f"- {run['date']}, `{run['model']}`{on}: "
                           f"[result file](results/{run['name']})")
            out.append("")
    return "\n".join(out)


def on_page_markdown(markdown, page, config, files):  # MkDocs hook signature
    repo_root = os.path.dirname(config["config_file_path"])
    real = os.path.realpath(page.file.abs_src_path)
    page_repo_path = os.path.relpath(real, repo_root).replace(os.sep, "/")
    docs_dir = config["docs_dir"]

    def built(site_path: str) -> bool:
        found = files.get_file_from_path(site_path)
        return found is not None and not found.inclusion.is_excluded()

    def on_site(site_path: str) -> bool:
        if built(site_path):
            return True
        folder = os.path.join(docs_dir, site_path)
        return os.path.isdir(folder) and any(
            built(posixpath.join(site_path, name)) for name in ("README.md", "index.md"))

    if page.file.src_uri == EVALS_PAGE and EVALS_MARKER in markdown:
        index = evals_index(Path(repo_root) / "evals")
        markdown = markdown.replace(EVALS_MARKER, index)
    return rewrite_links(markdown, page.file.src_uri, page_repo_path, repo_root, on_site)
