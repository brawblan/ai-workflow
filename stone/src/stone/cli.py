"""Command line for Cornerstone (`stone`)."""

from __future__ import annotations

import argparse
from pathlib import Path

from stone import __version__, framework_check
from stone.findings import report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stone", description="Cornerstone CLI.")
    parser.add_argument("--version", action="version", version=f"stone {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="Validate the framework and the repo config.")
    check.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")
    check.add_argument("--framework", type=Path, help="Framework folder. Default: <root>/framework.")
    check.add_argument("--format", choices=["text", "github"], default="text")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    findings = framework_check.run(args.root, args.framework)
    blocking = report(findings, args.format)
    print(f"stone check: {len(findings)} finding(s).")
    return 1 if blocking else 0
