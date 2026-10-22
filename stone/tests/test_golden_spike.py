"""Golden-file test for `stone render` with the spike profile alone (roadmap item 6e).

The test renders the profile into a temporary repo and compares each written file, byte for byte,
with the fixture in `golden/spike/`. To write the fixtures again after an intended change, run:

    STONE_UPDATE_GOLDEN=1 python -m unittest discover -s stone/tests -p "test_golden_*.py"

This file is self-contained on purpose: each profile has its own golden test file.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import render

PROFILE = "spike"
FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
GOLDEN = Path(__file__).resolve().parent / "golden" / PROFILE
UPDATE_ENV = "STONE_UPDATE_GOLDEN"
TODAY = dt.date(2026, 10, 18)
REVIEW_BY = "2027-04-18"  # TODAY plus 6 months (P5)
CONFIG = f"""framework_version: 0.8.0
harness: claude-code
model_profile: claude-5
profiles: [{PROFILE}]
branches: {{integration: dev, main: main}}
commands:
  install: pip install .
  test_unit: python -m unittest
  all_checks: make check
paths:
  tests: [tests/]
  checks: [.github/workflows/, .cornerstone/checks/]
  plans: docs/plans/
owners: {{default: octocat}}
"""
CONFIG_PATH = ".cornerstone/config.yaml"
MANIFEST = ".cornerstone/manifest.yaml"
HINT = f"If the change is intended, run with {UPDATE_ENV}=1 to write the fixtures again."

# Pins from framework/profiles/spike.md: roles [shaper, investigator], G3 skip, K16 in checks.
FILES = [".claude/agents/investigator.md", ".claude/agents/shaper.md", ".claude/settings.json",
         ".cornerstone/hooks/protect-paths.py", ".cornerstone/lib/path_match.py", MANIFEST,
         ".github/workflows/cornerstone-k16.yml"]
NOT_WRITTEN = [".github/workflows/cornerstone-checks.yml",
               ".cornerstone/checks/protected_paths.py"]
COMPONENTS = ["check.k16", "hook.path-match", "hook.protect-paths", "hook.settings",
              "role.investigator", "role.shaper"]


def tree_files(folder: Path, skip: frozenset[str] = frozenset()) -> dict[str, bytes]:
    """Return each file under `folder` (relative POSIX path) and its bytes."""
    if not folder.is_dir():
        return {}
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in sorted(folder.rglob("*"))
            if path.is_file() and path.relative_to(folder).as_posix() not in skip}


def golden_differences(golden: Path, files: dict[str, bytes]) -> list[str]:
    """Return one message for each fixture file that is missing, extra, or not equal."""
    fixtures = tree_files(golden)
    messages = [f"missing file {path}: the fixture has it, but render did not write it. " + HINT
                for path in sorted(set(fixtures) - set(files))]
    messages += [f"extra file {path}: render wrote it, but there is no fixture. " + HINT
                 for path in sorted(set(files) - set(fixtures))]
    messages += [f"changed file {path}: the render output is not equal to {golden / path}. "
                 + HINT for path in sorted(set(files) & set(fixtures))
                 if files[path] != fixtures[path]]
    return messages


def update_golden(golden: Path, files: dict[str, bytes]) -> None:
    """Make the fixture folder equal to `files`. Delete the stale fixture files."""
    if golden.exists():
        shutil.rmtree(golden)
    for path, content in files.items():
        (golden / path).parent.mkdir(parents=True, exist_ok=True)
        (golden / path).write_bytes(content)


class GoldenSpikeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / "repo"
        (self.root / ".cornerstone").mkdir(parents=True)
        (self.root / CONFIG_PATH).write_text(CONFIG, encoding="utf-8")
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            self.result = render.render(self.root, FRAMEWORK, today=TODAY)
        self.log = log.getvalue()
        self.files = tree_files(self.root, frozenset({CONFIG_PATH}))

    def manifest(self) -> dict:
        return yaml.safe_load(self.files[MANIFEST].decode("utf-8"))

    def test_golden_spike_files_match(self) -> None:
        if os.environ.get(UPDATE_ENV) == "1":
            update_golden(GOLDEN, self.files)
        differences = golden_differences(GOLDEN, self.files)
        self.assertEqual(differences, [], "\n".join(differences))

    def test_golden_spike_render_exits_0_with_no_skipped_profile(self) -> None:
        self.assertEqual(self.result.exit_code, 0, self.log)
        self.assertEqual(self.result.drift, [])
        self.assertNotIn("skipped profile", self.log)
        self.assertEqual(sorted(self.result.wrote), sorted(self.files))

    def test_golden_spike_writes_the_pinned_files(self) -> None:
        self.assertEqual(sorted(self.files), sorted(FILES))
        for path in NOT_WRITTEN:
            with self.subTest(path=path):
                self.assertNotIn(path, self.files)

    def test_golden_spike_manifest_has_the_pinned_components(self) -> None:
        components = self.manifest()["components"]
        self.assertEqual([c["id"] for c in components], COMPONENTS)
        for component in components:
            with self.subTest(component=component["id"]):
                self.assertEqual(str(component["added"]), TODAY.isoformat())
                self.assertEqual(str(component["review_by"]), REVIEW_BY)
                self.assertTrue(component["eval"])

    def test_golden_spike_fixtures_hold_the_manifest(self) -> None:
        if os.environ.get(UPDATE_ENV) == "1":
            self.skipTest("the fixtures are being rewritten")
        self.assertIn(MANIFEST, tree_files(GOLDEN))
        self.assertNotIn(CONFIG_PATH, tree_files(GOLDEN))

    def test_golden_spike_difference_names_the_file(self) -> None:
        golden = Path(self.folder.name) / "golden"
        update_golden(golden, self.files)
        self.assertEqual(golden_differences(golden, self.files), [])
        changed = sorted(self.files)[0]
        (golden / changed).write_bytes(b"changed\n")
        (golden / "only-in-fixture.txt").write_bytes(b"x\n")
        (golden / MANIFEST).unlink()
        messages = golden_differences(golden, self.files)
        self.assertEqual(len(messages), 3, messages)
        self.assertTrue(any("missing" in m and "only-in-fixture.txt" in m for m in messages))
        self.assertTrue(any("extra" in m and MANIFEST in m for m in messages))
        self.assertTrue(any("changed" in m and changed in m for m in messages))


if __name__ == "__main__":
    unittest.main()
