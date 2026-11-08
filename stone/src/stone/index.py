"""`stone index`: run the `stone-index` binary from PATH with the same arguments (#258)."""

from __future__ import annotations

import shutil
import subprocess
import sys

from stone import __version__

BINARY = "stone-index"
REPO_URL = "https://github.com/brawblan/ai-workflow"


def install_help() -> str:
    """The message when the binary is not on PATH: the install commands of indexer/README.md."""
    tag = f"v{__version__}"
    return (f"stone index: {BINARY} is not on PATH. Install it with one of these commands, "
            f"then run the command again.\n"
            f"  uv tool install <wheel URL from {REPO_URL}/releases/tag/{tag}>\n"
            f"  pipx install <wheel URL from {REPO_URL}/releases/tag/{tag}>\n"
            f"  cargo install --locked --git {REPO_URL} --tag {tag} {BINARY}\n"
            f"The Install section of indexer/README.md gives all the options.")


def run(args: list[str]) -> int:
    """Run stone-index with args and return its exit code. Return 2 if it is not on PATH."""
    path = shutil.which(BINARY)
    if path is None:
        print(install_help(), file=sys.stderr)
        return 2
    try:
        code = subprocess.run([path, *args], check=False).returncode
    except KeyboardInterrupt:
        return 130
    # A negative code is the number of the signal that stopped the binary (POSIX).
    return 128 - code if code < 0 else code
