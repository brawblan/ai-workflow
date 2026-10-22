"""Run the stone unit tests with one subprocess per test class, N classes at a time.

Usage: python stone/tests/run_parallel.py [-j N] [-v | -q] [--list]

It runs the same tests as `python -m unittest discover -s stone/tests`. The parent loads each
`test*.py` module with the unittest loader and groups its tests by TestCase class. Each class runs
as `python -m unittest -q <module>.<Class>` with cwd = the tests folder, so the imports work as with
discover. The classes with the most tests start first to balance the load.

If a module does not import, the runner keeps it as one unit, `<module>`. That unit fails with the
import error, as discover reports it. Stdlib only.
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import subprocess
import sys
import time
import unittest
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

RAN = re.compile(r"^Ran (\d+) tests?", re.MULTILINE)


@dataclass(frozen=True)
class Unit:
    """One subprocess: a `<module>.<Class>` name, or a `<module>` name if the module did not load."""

    name: str
    tests: int


@dataclass
class UnitResult:
    name: str
    seconds: float
    returncode: int
    output: str
    planned: int = 0

    @property
    def tests_run(self) -> int:
        """The count from the "Ran N tests" line.

        If the subprocess stopped before that line (for example, a module that raises a
        non-ImportError at import), use the planned count. Discover counts that module as 1 test.
        """
        match = RAN.search(self.output)
        return int(match.group(1)) if match else self.planned


def iter_tests(suite: unittest.TestSuite | unittest.TestCase) -> Iterator[unittest.TestCase]:
    """Yield each test case in `suite`, flattening the nested suites."""
    if isinstance(suite, unittest.TestSuite):
        for item in suite:
            yield from iter_tests(item)
    else:
        yield suite


def module_units(module_name: str) -> list[Unit]:
    """Load one module and return one unit per TestCase class that has tests.

    If the module does not import, or a test class is not an attribute of the module (for example
    a `load_tests` failure), return the whole module as one unit. Its subprocess then shows the
    error, and the error counts as one test, as with discover.
    """
    loader = unittest.defaultTestLoader
    errors_before = len(loader.errors)
    try:
        suite = loader.loadTestsFromName(module_name)
    except Exception:  # noqa: BLE001 - discover reports any import error as a failed test
        return [Unit(module_name, 1)]
    finally:
        del loader.errors[errors_before:]  # the subprocess reports the error, not this process
    module = sys.modules.get(module_name)
    if module is None:  # loadTestsFromName turns an ImportError into a failed test
        return [Unit(module_name, max(suite.countTestCases(), 1))]
    counts: dict[type, int] = {}
    for test in iter_tests(suite):
        counts[type(test)] = counts.get(type(test), 0) + 1
    if any(getattr(module, cls.__name__, None) is not cls for cls in counts):
        return [Unit(module_name, sum(counts.values()))]
    return [Unit(f"{module_name}.{cls.__name__}", count) for cls, count in counts.items()]


def find_units(folder: Path) -> list[Unit]:
    """Return the test classes of the `test*.py` modules in `folder`, the most tests first.

    The parent imports each module to read its classes. It restores `sys.path` and `sys.modules`
    after, so a second call on a different folder loads fresh modules.
    """
    saved_path = list(sys.path)
    saved_modules = dict(sys.modules)
    sys.path.insert(0, str(folder))
    importlib.invalidate_caches()
    try:
        units: list[Unit] = []
        for path in sorted(folder.glob("test*.py")):
            units.extend(module_units(path.stem))
    finally:
        sys.path[:] = saved_path
        for name in set(sys.modules) - set(saved_modules):
            del sys.modules[name]
        sys.modules.update(saved_modules)
    return sorted(units, key=lambda unit: (-unit.tests, unit.name))


def run_unit(folder: Path, unit: Unit, verbose: bool) -> UnitResult:
    command = [sys.executable, "-m", "unittest", "-v" if verbose else "-q", unit.name]
    start = time.monotonic()
    proc = subprocess.run(command, cwd=folder, env=os.environ.copy(), capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    return UnitResult(unit.name, time.monotonic() - start, proc.returncode, output, unit.tests)


def main(folder: Path, jobs: int | None = None, verbose: bool = False, quiet: bool = False) -> int:
    """Run each test class in `folder` in its own subprocess. Return 1 if any unit fails.

    With `quiet`, print only the failed units and the summary (D63).
    """
    start = time.monotonic()
    units = find_units(folder)
    results: list[UnitResult] = []
    with ThreadPoolExecutor(max_workers=jobs or os.cpu_count() or 1) as pool:
        futures = [pool.submit(run_unit, folder, unit, verbose) for unit in units]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status = "ok" if result.returncode == 0 else "FAIL"
            if not quiet or result.returncode != 0:
                print(f"{result.name:<60} {result.seconds:7.2f}s  {status}", flush=True)
            if result.returncode != 0 or verbose:
                print(result.output, flush=True)
    failed = sorted(result.name for result in results if result.returncode != 0)
    total = sum(result.tests_run for result in results)
    wall = time.monotonic() - start
    print(f"\nRan {total} tests in {len(results)} units, wall time {wall:.2f}s")
    if failed:
        print(f"FAILED units: {', '.join(failed)}")
        return 1
    print("OK")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-j", "--jobs", type=int, default=None, help="units at a time (default: CPU count)")
    parser.add_argument("-v", "--verbose", action="store_true", help="print the output of each unit")
    parser.add_argument("-q", "--quiet", action="store_true", help="print only the failed units and the summary")
    parser.add_argument("--list", action="store_true", help="print the units and their test counts, do not run")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    tests_folder = Path(__file__).resolve().parent
    if args.list:
        planned = find_units(tests_folder)
        for planned_unit in planned:
            print(f"{planned_unit.tests:5d}  {planned_unit.name}")
        print(f"\n{sum(unit.tests for unit in planned)} tests in {len(planned)} units")
        sys.exit(0)
    sys.exit(main(tests_folder, args.jobs, args.verbose, args.quiet))
