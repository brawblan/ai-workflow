"""Build `stone.pyz`: one zipapp file that runs `stone` with Python 3.11 or later.

The zipapp holds the `stone` package from `src/` and the `yaml` package of the Python that runs this
script. It leaves out each compiled module, so PyYAML uses its pure-Python code and the file works
on all platforms. Fixed file times and a sorted file order make two builds from the same commit and
the same PyYAML version give the same bytes.

Usage: python stone/build_zipapp.py --out stone.pyz
"""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import sys
import zipfile
from pathlib import Path

SHEBANG = b"#!/usr/bin/env python3\n"
MAIN = """import sys

if sys.version_info < (3, 11):
    sys.exit("stone needs Python 3.11 or later.")

from stone.cli import main

sys.exit(main())
"""
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o644 << 16
COMPILED_SUFFIXES = (".so", ".pyd", ".dylib", ".pyc", ".pyo")
SRC = Path(__file__).resolve().parent / "src" / "stone"


def package_files(package: Path, prefix: str) -> dict[str, Path]:
    """Map each archive name to its source file. Skip caches, compiled modules, and dotfiles."""
    files: dict[str, Path] = {}
    for path in package.rglob("*"):
        parts = path.relative_to(package).parts
        if (not path.is_file() or "__pycache__" in parts or path.suffix in COMPILED_SUFFIXES
                or any(part.startswith(".") for part in parts)):
            continue
        files[f"{prefix}/{path.relative_to(package).as_posix()}"] = path
    return files


def yaml_files() -> dict[str, Path]:
    """The pure-Python files of PyYAML, and its license file if the install has one."""
    try:
        import yaml
    except ImportError:
        raise SystemExit("build_zipapp: PyYAML is not installed. Run: pip install ./stone") from None
    files = package_files(Path(yaml.__file__).resolve().parent, "yaml")
    try:
        dist = importlib.metadata.distribution("PyYAML")
    except importlib.metadata.PackageNotFoundError:
        return files
    for entry in dist.files or []:
        if Path(entry.name).name.upper().startswith("LICENSE"):
            files["yaml/LICENSE"] = Path(dist.locate_file(entry))
            break
    return files


def entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = FILE_MODE
    info.create_system = 3  # Unix, also on Windows, so each OS gives the same bytes
    return info


def build(out: Path) -> None:
    """Write the zipapp to `out`. A second run with the same inputs writes the same bytes."""
    files = {**package_files(SRC, "stone"), **yaml_files()}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as handle:
        handle.write(SHEBANG)
        with zipfile.ZipFile(handle, "w") as archive:
            archive.writestr(entry("__main__.py"), MAIN, compresslevel=9)
            for name in sorted(files):
                archive.writestr(entry(name), files[name].read_bytes(), compresslevel=9)
    os.chmod(out, 0o755)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the stone zipapp.")
    parser.add_argument("--out", type=Path, default=Path("stone.pyz"), help="The output file.")
    args = parser.parse_args(argv)
    build(args.out)
    print(f"build_zipapp: wrote {args.out} ({args.out.stat().st_size} bytes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
