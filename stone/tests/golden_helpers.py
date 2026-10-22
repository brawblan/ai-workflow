"""Shared helpers for the golden-file tests of `stone render` (D64, issue #148).

Each golden test renders one config into a temporary repo and compares each written file, byte for
byte, with its fixture. A fixture is in the profile folder of the test, or in `golden/_shared/`.
`_shared/` holds one copy of each file that two or more golden tests render with the same bytes.
The profile folder holds the other files, for example the manifest, the workflows, and the checks.

To write the fixtures again after an intended change, run all the golden tests in one process:

    STONE_UPDATE_GOLDEN=1 python -m unittest discover -s stone/tests -p "test_golden_*.py"

The update renders the config of each golden test to find the shared files. So each golden test
module gives its fixture folder as `GOLDEN` and its config text as `CONFIG`.

The name does not start with "test", so discover does not load this module.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib
import io
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from stone import render

TESTS = Path(__file__).resolve().parent
FRAMEWORK = TESTS.parents[1] / "framework"
SHARED = TESTS / "golden" / "_shared"
UPDATE_ENV = "STONE_UPDATE_GOLDEN"
HINT = f"If the change is intended, run with {UPDATE_ENV}=1 to write the fixtures again."
CONFIG_PATH = ".cornerstone/config.yaml"
TODAY = dt.date(2026, 10, 18)


def updating() -> bool:
    return os.environ.get(UPDATE_ENV) == "1"


def tree_files(folder: Path, skip: frozenset[str] = frozenset()) -> dict[str, bytes]:
    """Return each file under `folder` (relative POSIX path) and its bytes."""
    if not folder.is_dir():
        return {}
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob("*"))
            if path.is_file() and path.relative_to(folder).as_posix() not in skip}


def shared_folder(golden: Path) -> Path:
    """Return the shared folder for the profile folder `golden`.

    A folder under `stone/tests/golden/` uses `golden/_shared/`. A fixture in a temporary folder
    uses the `_shared/` folder next to it, so a test of this module does not touch the real one.
    """
    return SHARED if golden.is_relative_to(SHARED.parent) else golden.parent / "_shared"


def golden_differences(golden: Path, files: dict[str, bytes]) -> list[str]:
    """Return one message for each file that is missing, extra, duplicate, or not equal.

    Each rendered file must be in the profile folder `golden` or in the shared folder, not in both.
    Each file in the profile folder must be rendered. A shared file that this test does not render
    is not a difference, because other golden tests use it.
    """
    shared = shared_folder(golden)
    own, common = tree_files(golden), tree_files(shared)
    messages = [f"missing file {path}: the fixture has it, but render did not write it. " + HINT
                for path in sorted(set(own) - set(files))]
    for path in sorted(files):
        if path in own and path in common:
            messages.append(f"duplicate file {path}: it is in {golden} and in {shared}. " + HINT)
        elif path not in own and path not in common:
            messages.append(f"extra file {path}: render wrote it, but it is not in {golden} or in "
                            f"{shared}. " + HINT)
        elif files[path] != own.get(path, common.get(path)):
            folder = golden if path in own else shared
            messages.append(f"changed file {path}: the render output is not equal to "
                            f"{folder / path}. " + HINT)
    return messages


def shared_files(renders: Iterable[dict[str, bytes]]) -> dict[str, bytes]:
    """Return each file that two or more renders write, if each of them writes the same bytes."""
    found: dict[str, list[bytes]] = {}
    for files in renders:
        for path, content in files.items():
            found.setdefault(path, []).append(content)
    return {path: contents[0] for path, contents in sorted(found.items())
            if len(contents) > 1 and len(set(contents)) == 1}


def render_config(config: str) -> dict[str, bytes]:
    """Render `config` into a temporary repo on the fixed date, and return the written files."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder) / "repo"
        (root / ".cornerstone").mkdir(parents=True)
        (root / CONFIG_PATH).write_text(config, encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(root, FRAMEWORK, today=TODAY)
        return tree_files(root, frozenset({CONFIG_PATH}))


def golden_renders() -> dict[Path, dict[str, bytes]]:
    """Render the config of each golden test module. The key is the fixture folder of the test."""
    renders = {}
    for path in sorted(TESTS.glob("test_golden_*.py")):
        module = importlib.import_module(path.stem)
        if hasattr(module, "GOLDEN"):
            renders[module.GOLDEN] = render_config(module.CONFIG)
    return renders


def write_tree(folder: Path, files: dict[str, bytes]) -> None:
    """Make `folder` hold `files` and no other file. Write a file only if its bytes change."""
    old = tree_files(folder)
    for path in sorted(set(old) - set(files)):
        (folder / path).unlink(missing_ok=True)
    for path, content in files.items():
        if old.get(path) != content:
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_bytes(content)
    for sub in sorted(folder.rglob("*"), reverse=True) if folder.is_dir() else []:
        if sub.is_dir() and not any(sub.iterdir()):
            with contextlib.suppress(OSError):  # another test process can remove it first
                sub.rmdir()


def update_golden(golden: Path, files: dict[str, bytes]) -> None:
    """Write the fixtures of one golden test, and delete its stale fixtures (D64).

    The shared folder gets each file that two or more golden tests render with the same bytes. The
    profile folder gets the other files that this test renders.
    """
    common = shared_files(golden_renders().values())
    write_tree(shared_folder(golden), common)
    write_tree(golden, {path: content for path, content in files.items() if path not in common})
