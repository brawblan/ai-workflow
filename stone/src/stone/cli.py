"""Command line for Cornerstone (`stone`)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stone import __version__, evals, evidence_check, framework_check, render, specs, writing_check
from stone.findings import report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stone", description="Cornerstone CLI.")
    parser.add_argument("--version", action="version", version=f"stone {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="Validate the framework and the repo config.")
    check.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")
    check.add_argument("--framework", type=Path, help="Framework folder. Default: <root>/framework.")
    check.add_argument("--links", choices=framework_check.LINK_MODES, default="default",
                       help="Link check scope. default: the Cornerstone files and "
                            "checks.links.paths. all: each Markdown file.")
    check.add_argument("--format", choices=["text", "github"], default="text")

    build = commands.add_parser("render", help="Write the generated files and the manifest.")
    build.add_argument("--root", type=Path, default=Path("."), help="Target repo. Default: '.'.")
    build.add_argument("--framework", type=Path, help="Framework folder. Default: <root>/framework.")
    build.add_argument("--dry-run", action="store_true", help="Print the changes. Write nothing.")

    spec = commands.add_parser("spec", help="Work with the specs of the repo.")
    spec_commands = spec.add_subparsers(dest="spec_command", required=True)
    spec_apply = spec_commands.add_parser(
        "apply", help="Apply the spec delta of one plan to the specs.")
    spec_apply.add_argument("plan", help="The plan ID: the delta is <plans>/<plan>.spec.md.")
    spec_apply.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")
    spec_sync = spec_commands.add_parser(
        "sync", help="After a merge: renumber the applied deltas, and write the specs again.")
    spec_sync.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")

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

    evidence = commands.add_parser("check-evidence",
                                   help="K14: fail if a required PR section is missing or empty.")
    evidence.add_argument("body", help="The PR body file. Use '-' to read standard input.")
    evidence.add_argument("--section", action="append", metavar="NAME",
                          help="A required section. Repeat for more. Default: "
                               + ", ".join(evidence_check.DEFAULT_SECTIONS) + ".")
    evidence.add_argument("--mode", choices=["warn", "block"], default="warn",
                          help="warn: report only (the first 2 weeks). block: fail on findings.")
    evidence.add_argument("--format", choices=["text", "github"], default="text")

    run = commands.add_parser("eval", help="Run the eval of one component, with it and without it.")
    run.add_argument("component", help="The component ID, for example role.tester.")
    run.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")
    run.add_argument("--framework", type=Path, help="Framework folder. Default: <root>/framework.")
    run.add_argument("--scenario", action="append", metavar="ID",
                     help="Run only this scenario. Repeat for more. Default: all.")
    run.add_argument("--variant", choices=["with", "without", "both"], default="both")
    run.add_argument("--trials", type=int, default=1, help="Runs for each scenario and variant.")
    run.add_argument("--model", help="Default: the role model in the model profile.")
    run.add_argument("--budget", default="5", help="The cost limit for each run. Default: 5.")
    run.add_argument("--timeout", type=int, default=1800, help="Seconds for each run.")
    run.add_argument("--run-config", type=Path,
                     help="The harness command file. Default: the eval.yaml of the adapter.")
    run.add_argument("--keep", action="store_true", help="Keep the workspace of each run.")
    run.add_argument("--check-only", action="store_true",
                     help="Validate the scenarios and list the runs. Start no run.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check":
        findings = framework_check.run(args.root, args.framework, args.links)
        blocking = report(findings, args.format)
        print(f"stone check: {len(findings)} finding(s).")
        return 1 if blocking else 0
    if args.command == "render":
        return _render(args.root, args.framework, args.dry_run)
    if args.command == "spec":
        return _spec(args.root, args.spec_command, getattr(args, "plan", ""))
    if args.command == "check-evidence":
        return _check_evidence(args.body, args.section, args.mode, args.format)
    if args.command == "eval":
        return _eval(args)

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


def _spec(root: Path, command: str, plan: str) -> int:
    try:
        changed = specs.apply(root, plan) if command == "apply" else specs.sync(root)
    except specs.SpecError as error:
        print(f"stone spec {command}: {error}")
        return 1
    for path in changed:
        print(f"wrote {path}")
    print(f"stone spec {command}: {len(changed)} file(s) changed. Commit them alone, with the "
          "trailers 'Role: generator' and 'Actor: agent' or 'Actor: human'.")
    return 0


def _check_evidence(body: str, sections: list[str] | None, mode: str, fmt: str) -> int:
    if body == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(body).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            reason = error.reason if isinstance(error, UnicodeDecodeError) else error.strerror
            print(f"check-evidence: cannot read {body}: {reason}")
            return 2
    findings = evidence_check.check_text(text, "<stdin>" if body == "-" else body, sections)
    blocking = report(findings, fmt, warn_only=mode == "warn")
    print(f"K14: {len(findings)} finding(s), mode {mode}.")
    return 1 if blocking else 0


def _eval(args: argparse.Namespace) -> int:
    if args.trials < 1:
        print("stone eval: --trials must be 1 or more.")
        return 2
    try:
        runs, result = evals.run_eval(
            args.root, args.component, framework=args.framework, scenario_ids=args.scenario,
            variant=args.variant, trials=args.trials, model=args.model, budget=args.budget,
            timeout=args.timeout, run_config=args.run_config, keep=args.keep,
            check_only=args.check_only)
    except (evals.EvalError, render.RenderError) as error:
        print(f"stone eval: {error}")
        return 2
    if args.check_only:
        print("stone eval: the scenarios are valid.")
        return 0
    failed = [run for run in runs if run.variant == "with" and not run.passed()]
    print(f"stone eval: {len(runs)} run(s), {len(failed)} failed with the component. "
          f"Results: {result}")
    return 1 if failed else 0


def _render(root: Path, framework: Path | None, dry_run: bool) -> int:
    try:
        result = render.render(root, framework, dry_run)
    except render.RenderError as error:
        print(f"stone render: {error}")
        return 1
    print(f"stone render: {len(result.wrote)} written, {len(result.skipped)} skipped, "
          f"{len(result.drift)} drift.")
    if result.drift:
        print("Drift: a person changed generated content. Restore it, or move the change to "
              "the repo config, delete the file, and render again.")
    return result.exit_code
