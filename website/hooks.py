"""MkDocs hook: point each relative link to a file that is not on the site to GitHub.

The site content is a mirror of the repo folders (symlinks in website/content/). A link from a
mirrored page to a file outside the mirror, for example ../../README.md or ../.cornerstone/, would
break on the site. This hook rewrites such a link to the file on GitHub.
"""

import os
import posixpath
import re
from collections.abc import Callable

REPO_URL = "https://github.com/brawblan/ai-workflow"
BRANCH = "main"
LINK = re.compile(r"(\]\()([^)\s]+)(\))")
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


def on_page_markdown(markdown, page, config, files):  # MkDocs hook signature
    repo_root = os.path.dirname(config["config_file_path"])
    real = os.path.realpath(page.file.abs_src_path)
    page_repo_path = os.path.relpath(real, repo_root).replace(os.sep, "/")
    docs_dir = config["docs_dir"]

    def on_site(site_path: str) -> bool:
        if files.get_file_from_path(site_path) is not None:
            return True
        folder = os.path.join(docs_dir, site_path)
        return os.path.isdir(folder) and any(
            files.get_file_from_path(posixpath.join(site_path, name)) is not None
            for name in ("README.md", "index.md"))

    return rewrite_links(markdown, page.file.src_uri, page_repo_path, repo_root, on_site)
