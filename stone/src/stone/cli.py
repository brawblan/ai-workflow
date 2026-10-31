"""Command line for Cornerstone (`stone`)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from stone import (__version__, dependency_check, evals, evidence_check, framework_check, gate, ready_check, render,
                   repo_rules, specialists, specs, upgrade, workflow_check, writing_check)
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

    local = commands.add_parser(
        "gate", help="G3 on this machine (delivery: local): run K6, K7, and commands.all_checks.")
    local.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")
    local.add_argument("--base", help="The base branch. Default: origin/<branches.integration "
                                      "or branches.main>.")
    local.add_argument("--body", type=Path,
                       help="A file with the PR body, for the K7 profile line and waiver, and "
                            "for K20.")
    local.add_argument("--labels", default="", help="The PR labels, with commas. For K20.")
    local.add_argument("--split-checks", action="store_true",
                       help="Run each command of commands.all_checks that '&&' joins, and give "
                            "each its own row. A failure does not stop the next command.")

    special = commands.add_parser(
        "specialists", help="Find the specialist reviews that a change needs, and their reports.")
    special.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")
    special.add_argument("--base", help="The base branch. Default: origin/<branches.integration "
                                        "or branches.main>.")
    special.add_argument("--ticket", required=True, help="The ticket ID. It names the reports.")
    special.add_argument("--labels", default="", help="The labels of the ticket, with commas.")
    special.add_argument("--personas", default="", help="The persona IDs of the ticket, with commas.")

    k20 = commands.add_parser(
        "check-specialists", help="K20: fail on a blocking specialist finding or a missing report.")
    k20.add_argument("body", help="The PR body file. Use '-' to read standard input.")
    k20.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")
    k20.add_argument("--base", help="The base branch. Default: origin/<branches.integration "
                                    "or branches.main>.")
    k20.add_argument("--labels", default="", help="The PR labels, with commas.")
    k20.add_argument("--mode", choices=["warn", "block"], default="warn",
                     help="warn: report only (the first 2 weeks). block: fail on errors.")
    k20.add_argument("--format", choices=["text", "github"], default="text")

    up = commands.add_parser(
        "upgrade", help="Plan the move to a new Cornerstone version. --apply makes the move.")
    up.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")
    up.add_argument("--framework", type=Path, help="Framework folder. Default: <root>/framework.")
    up.add_argument("--to", metavar="VERSION",
                    help="The target version. Default: the newest released version.")
    up.add_argument("--apply", action="store_true",
                    help="Set framework_version and render. Stops if a person must act first.")

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

    rules = commands.add_parser(
        "check-rules", help="R1 to R4, K9: test the action pins, the plugin version, the event text "
             "in 'run', the commit format, and the complexity caps (D78, D97, D98, D100).")
    rules.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")
    rules.add_argument("--base", help="The base branch. Gives R2 (the plugin version bump), R4 "
                                      "(the commit format), and K9 (the caps of changed "
                                      "functions). Without it, only R1 and R3 run.")
    rules.add_argument("--skills", default=repo_rules.SKILLS, help="The skills folder, for R2.")
    rules.add_argument("--plugin-file", default=repo_rules.PLUGIN_FILE,
                       help="The plugin file with the version, for R2.")
    rules.add_argument("--format", choices=["text", "github"], default="text")

    evidence = commands.add_parser("check-evidence",
                                   help="K14: fail if a required PR section is missing or empty.")
    evidence.add_argument("body", help="The PR body file. Use '-' to read standard input.")
    evidence.add_argument("--section", action="append", metavar="NAME",
                          help="A required section. Repeat for more. Default: "
                               + ", ".join(evidence_check.DEFAULT_SECTIONS) + ".")
    evidence.add_argument("--mode", choices=["warn", "block"], default="warn",
                          help="warn: report only (the first 2 weeks). block: fail on findings.")
    evidence.add_argument("--format", choices=["text", "github"], default="text")

    deps = commands.add_parser("check-dependencies",
                               help="K23: report a new package that the PR body does not name.")
    deps.add_argument("body", help="The PR body file. Use '-' to read standard input.")
    deps.add_argument("--base", required=True, help="The base ref, for example origin/dev.")
    deps.add_argument("--mode", choices=["warn", "block"], default="warn",
                      help="warn: report only (1.x). block: fail on findings.")
    deps.add_argument("--format", choices=["text", "github"], default="text")

    workflows = commands.add_parser("check-workflows",
                                    help="K24: report an unpinned tool in a CI workflow.")
    workflows.add_argument("body", help="The PR body file. Use '-' to read standard input.")
    scope = workflows.add_mutually_exclusive_group(required=True)
    scope.add_argument("--base", help="The base ref. Read the workflows that the PR changes.")
    scope.add_argument("--all", action="store_true", help="Read each tracked workflow.")
    workflows.add_argument("--mode", choices=["warn", "block"], default="warn",
                           help="warn: report only (1.x). block: fail on findings.")
    workflows.add_argument("--format", choices=["text", "github"], default="text")

    ready = commands.add_parser("check-ready",
                                help="K21: report a Definition of Ready field that is missing or "
                                     "empty.")
    ready.add_argument("ticket", help="The ticket file or issue body. Use '-' to read standard "
                                      "input.")
    ready.add_argument("--profile", choices=sorted(ready_check.PROFILE_FIELDS),
                       help="The profile of the ticket. Default: the 'Profile: <id>' line of the "
                            "ticket.")
    ready.add_argument("--mode", choices=["warn", "block"], default="warn",
                       help="warn: report only (D82). block: fail on findings.")
    ready.add_argument("--format", choices=["text", "github"], default="text")

    run = commands.add_parser("eval", help="Run the eval of one component, with it and without it.")
    run.add_argument("component", help="The component ID, for example role.tester.")
    run.add_argument("--root", type=Path, default=Path("."), help="Repo root. Default: '.'.")
    run.add_argument("--framework", type=Path, help="Framework folder. Default: <root>/framework.")
    run.add_argument("--scenario", action="append", metavar="ID",
                     help="Run only this scenario. Repeat for more. Default: all.")
    run.add_argument("--variant", default="both",
                     help="'with', 'without', or 'both' (default). A guidance eval takes the names "
                          "in the 'variants' of its scenarios.")
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
    if args.command == "gate":
        return _gate(args.root, args.base, args.body, _split(args.labels), args.split_checks)
    if args.command == "upgrade":
        return _upgrade(args)
    if args.command == "specialists":
        return _specialists(args)
    if args.command == "check-specialists":
        return _check_specialists(args)
    if args.command == "spec":
        return _spec(args.root, args.spec_command, getattr(args, "plan", ""))
    if args.command == "check-evidence":
        return _check_evidence(args.body, args.section, args.mode, args.format)
    if args.command == "check-dependencies":
        return _check_dependencies(args.body, args.base, args.mode, args.format)
    if args.command == "check-workflows":
        return _check_workflows(args.body, None if args.all else args.base, args.mode, args.format)
    if args.command == "check-ready":
        return _check_ready(args.ticket, args.profile, args.mode, args.format)
    if args.command == "check-rules":
        return _check_rules(args)
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


def _check_rules(args: argparse.Namespace) -> int:
    try:
        findings = repo_rules.run(args.root, args.base, args.skills, args.plugin_file)
    except subprocess.CalledProcessError as error:
        print(f"check-rules: git failed: {(error.stderr or '').strip()}")
        return 2
    blocking = report(findings, args.format)
    print(f"check-rules: {blocking} error(s).")
    return 1 if blocking else 0


def _gate(root: Path, base: str | None, body: Path | None, labels: list[str],
          split_checks: bool = False) -> int:
    try:
        steps, text = gate.run(root, base, body, labels=labels, split_checks=split_checks)
    except gate.GateError as error:
        print(f"stone gate: {error}")
        return 2
    print(text)
    failed = [step.name for step in steps if not (step.passed or step.skipped)]
    print(f"\nstone gate: {len(failed)} failed.", file=sys.stderr)
    return 1 if failed else 0


def _upgrade(args: argparse.Namespace) -> int:
    framework = args.framework or args.root / "framework"
    try:
        if args.apply:
            written = upgrade.apply(args.root, framework, args.to)
            print(f"stone upgrade: applied. {len(written)} file(s) written or in drift. Commit the "
                  "generated files alone, with the trailers 'Role: generator' and 'Actor: agent'.")
            return 0
        text, _, code = upgrade.plan(args.root, framework, args.to)
    except (upgrade.UpgradeError, render.RenderError) as error:
        print(f"stone upgrade: {error}")
        return 2
    print(text)
    return code


def _split(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _specialists(args: argparse.Namespace) -> int:
    try:
        config = gate.load_config(args.root)
        rows, text = specialists.run(args.root, config, args.base or gate.default_base(config),
                                     _split(args.labels), _split(args.personas), args.ticket)
    except (gate.GateError, specialists.SpecialistError) as error:
        print(f"stone specialists: {error}")
        return 2
    print(text)
    return 1 if any(row.status != "reviewed" for row in rows) else 0


def _check_specialists(args: argparse.Namespace) -> int:
    try:
        text = sys.stdin.read() if args.body == "-" else Path(args.body).read_text(encoding="utf-8")
        config = gate.load_config(args.root)
    except (OSError, UnicodeDecodeError, gate.GateError) as error:
        print(f"check-specialists: {error}")
        return 2
    findings = specialists.check(args.root, config, args.base or gate.default_base(config), text,
                                 _split(args.labels), "<stdin>" if args.body == "-" else args.body)
    blocking = report(findings, args.format, warn_only=args.mode == "warn")
    print(f"K20: {len(findings)} finding(s), mode {args.mode}.")
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


def _check_dependencies(body: str, base: str, mode: str, fmt: str) -> int:
    if body == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(body).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            reason = error.reason if isinstance(error, UnicodeDecodeError) else error.strerror
            print(f"check-dependencies: cannot read {body}: {reason}")
            return 2
    try:
        findings = dependency_check.check(Path("."), base, text)
    except RuntimeError as error:
        print(f"check-dependencies: {error}")
        return 2
    blocking = report(findings, fmt, warn_only=mode == "warn")
    print(f"K23: {len(findings)} finding(s), mode {mode}.")
    return 1 if blocking else 0


def _check_workflows(body: str, base: str | None, mode: str, fmt: str) -> int:
    if body == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(body).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            reason = error.reason if isinstance(error, UnicodeDecodeError) else error.strerror
            print(f"check-workflows: cannot read {body}: {reason}")
            return 2
    try:
        findings = workflow_check.check(Path("."), base, text)
    except RuntimeError as error:
        print(f"check-workflows: {error}")
        return 2
    blocking = report(findings, fmt, warn_only=mode == "warn")
    if workflow_check.has_waiver(text):
        print("K24: notice: the PR body has a Waiver (K24) section. A human reviews each finding.")
    print(f"K24: {len(findings)} finding(s), mode {mode}.")
    return 1 if blocking else 0


def _check_ready(ticket: str, profile: str | None, mode: str, fmt: str) -> int:
    if ticket == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(ticket).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            reason = error.reason if isinstance(error, UnicodeDecodeError) else error.strerror
            print(f"check-ready: cannot read {ticket}: {reason}")
            return 2
    profile = profile or ready_check.find_profile(text)
    if profile not in ready_check.PROFILE_FIELDS:
        print(f"check-ready: no known profile ({profile or 'none'}). Add a 'Profile: <id>' line "
              "to the ticket, or use --profile.")
        return 2
    findings = ready_check.check_text(text, "<stdin>" if ticket == "-" else ticket, profile)
    blocking = report(findings, fmt, warn_only=mode == "warn")
    print(f"K21: {len(findings)} finding(s), profile {profile}, mode {mode}.")
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
    failed = [run for run in runs if run.variant not in ("without", "none") and not run.passed()]
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
