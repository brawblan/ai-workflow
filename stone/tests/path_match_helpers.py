"""Shared names for the tests of the protected paths (D62, issue #119).

test_path_globs.py and test_eval_hook_protect_paths.py import this module by name, as other test
modules import from test_render. The name does not start with "test", so discover does not load it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FRAMEWORK = REPO / "framework"
# The rendered files, relative to the repo root.
HOOK = ".cornerstone/hooks/protect-paths.py"
K6 = ".cornerstone/checks/protected_paths.py"
PATH_MATCH = ".cornerstone/lib/path_match.py"

# The match rule before D62 (the main branch): the path, or a path under the folder. A test can put
# this text in the rendered match module, or call it as `prefix_only_covers`. It is the one copy.
PREFIX_ONLY_COVERS = ('def covers(patterns, path):\n'
                      '    return any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/")'
                      ' for p in patterns)\n')
_namespace: dict = {}
exec(PREFIX_ONLY_COVERS, _namespace)
prefix_only_covers: Callable[[list[str], str], bool] = _namespace["covers"]
