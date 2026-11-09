"""Fixtures of the context guard golden tests (issue #299, D115).

These tests render the single-ticket profile with a custom limit and with the guard off. A few
files (the hook and the settings) differ from the shared fixtures of `golden/_shared/`. So the
fixture folder of these tests holds each file that is not equal to the shared copy, and the compare
reads the shared copy for the others. The tests do not export `GOLDEN`, so `golden_helpers` does not
count them when it chooses the shared files.

The name does not start with "test", so discover does not load this module.
"""

from __future__ import annotations

from pathlib import Path

from golden_helpers import HINT, SHARED, tree_files, updating, write_tree


def own_files(files: dict[str, bytes]) -> dict[str, bytes]:
    """Return the rendered files that are not equal to the shared fixture of the same path."""
    shared = tree_files(SHARED)
    return {path: content for path, content in files.items() if shared.get(path) != content}


def differences(folder: Path, files: dict[str, bytes]) -> list[str]:
    """Return one message for each rendered file that is missing, extra, or not equal."""
    if updating():
        write_tree(folder, own_files(files))
    own, shared = tree_files(folder), tree_files(SHARED)
    messages = [f"missing file {path}: the fixture has it, but render did not write it. " + HINT
                for path in sorted(set(own) - set(files))]
    for path, content in sorted(files.items()):
        want = own.get(path, shared.get(path))
        if want is None:
            messages.append(f"extra file {path}: render wrote it, but there is no fixture. " + HINT)
        elif want != content:
            messages.append(f"changed file {path}: the render output is not equal to its fixture. " + HINT)
    return messages
