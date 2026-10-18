"""Command line for Cornerstone (`stone`)."""

from __future__ import annotations

import argparse
from pathlib import Path

from stone import __version__, framework_check, render, writing_check
from stone.findings import report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stone", description="Cornerstone CLI.")
    parser.add_argument("--version", action="version", version=f"stone {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="Validate the framework and the repo config.")
    check.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")
    check.add_argument("--framework", type=Path, help="Framework folder. Default: <root>/framework.")
    check.add_argument("--format", choices=["text", "github"], default="text")

    build = commands.add_parser("render", help="Write the generated files and the manifest.")
    build.add_argument("--root", type=Path, default=Path("."), help="Target repo. Default: '.'.")
    build.add_argument("--framework", type=Path, help="Framework folder. Default: <root>/framework.")
    build.add_argument("--dry-run", action="store_true", help="Print the changes. Write nothing.")

    writing = commands.add_parser("check-writing",
                                  help="K17: test human-facing text against the writing standard.")
    writing.add_argument("paths", nargs="*", help="Files or folders to test in full.")
    writing.add_argument("--diff", metavar="BASE",
                         help="Also test the changed lines of Markdown files since BASE.")
    writing.add_argument("--root", type=Path, default=Path("."))
    writing.add_argument("--rules", type=Path, help="The STE rule file (ste.md).")
    writing.add_argument("--dictionary", type=Path, help="The project dictionary.")
    writing.add_argument("--exclude", action="append", default=[],
                         help="Glob of a path to skip. Repeat for more.")
    writing.add_argument("--mode", choices=["warn", "block"], default="warn",
                         help="warn: report only (the first 2 weeks). block: fail on errors.")
    writing.add_argument("--format", choices=["text", "github"], default="text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check":
        findings = framework_check.run(args.root, args.framework)
        blocking = report(findings, args.format)
        print(f"stone check: {len(findings)} finding(s).")
        return 1 if blocking else 0
    if args.command == "render":
        return _render(args.root, args.framework, args.dry_run)

    rules_path = args.rules or args.root / writing_check.DEFAULT_RULES
    dictionary = args.dictionary or args.root / writing_check.DEFAULT_DICTIONARY
    rules = writing_check.load_rules(rules_path, dictionary)
    if not args.paths and not args.diff:
        print("check-writing: give paths, --diff BASE, or both.")
        return 2
    findings = writing_check.run(args.root, args.paths, args.diff, rules,
                                 writing_check.DEFAULT_EXCLUDE + args.exclude)
    blocking = report(findings, args.format, warn_only=args.mode == "warn")
    errors = sum(1 for f in findings if f.severity == "error")
    print(f"K17: {errors} error(s), {len(findings) - errors} warning(s), mode {args.mode}.")
    return 1 if blocking else 0


def _render(root: Path, framework: Path | None, dry_run: bool) -> int:
    try:
        result = render.render(root, framework, dry_run)
    except render.RenderError as error:
        print(f"stone render: {error}")
        return 1
    print(f"stone render: {len(result.wrote)} written, {len(result.skipped)} skipped, "
          f"{len(result.drift)} drift.")
    if result.drift:
        print("Drift: a generated file changed by hand. Move the edit to the repo config, "
              "or delete the file and render again.")
    return result.exit_code
