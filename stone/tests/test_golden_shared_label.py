"""Golden-file test for `stone render` with two profiles that share one trigger label (D43, #55).

The profiles debugging and single-ticket both use label:agent-ready. The test renders them into a
temporary repo and compares each written file, byte for byte, with the fixture in
`golden/shared-label/`. To write the fixtures again after an intended change, run:

    STONE_UPDATE_GOLDEN=1 python -m unittest discover -s stone/tests -p "test_golden_*.py"

This file is self-contained on purpose: each profile set has its own golden test file.
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

PROFILES = ["debugging", "single-ticket"]
LABEL = "agent-ready"
FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
GOLDEN = Path(__file__).resolve().parent / "golden" / "shared-label"
UPDATE_ENV = "STONE_UPDATE_GOLDEN"
TODAY = dt.date(2026, 10, 18)
CONFIG = f"""framework_version: 0.8.0
harness: claude-code
model_profile: claude-5
profiles: [{", ".join(PROFILES)}]
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

WORKFLOWS = {profile: f".github/workflows/cornerstone-{profile}-label.yml" for profile in PROFILES}


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


class GoldenSharedLabelTest(unittest.TestCase):
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

    def workflow(self, profile: str) -> str:
        return self.files[WORKFLOWS[profile]].decode("utf-8")

    def test_golden_shared_label_files_match(self) -> None:
        if os.environ.get(UPDATE_ENV) == "1":
            update_golden(GOLDEN, self.files)
        differences = golden_differences(GOLDEN, self.files)
        self.assertEqual(differences, [], "\n".join(differences))

    def test_golden_shared_label_render_exits_0_with_no_skipped_profile(self) -> None:
        self.assertEqual(self.result.exit_code, 0, self.log)
        self.assertEqual(self.result.drift, [])
        self.assertNotIn("skipped profile", self.log)
        self.assertEqual(sorted(self.result.wrote), sorted(self.files))

    def test_golden_shared_label_writes_two_separate_workflows(self) -> None:
        labels = sorted(path for path in self.files
                        if path.startswith(".github/workflows/") and path.endswith("-label.yml"))
        self.assertEqual(labels, sorted(WORKFLOWS.values()))
        self.assertNotEqual(self.files[WORKFLOWS["debugging"]],
                            self.files[WORKFLOWS["single-ticket"]])

    def test_golden_shared_label_each_workflow_selects_its_own_profile(self) -> None:
        for profile, other in (("debugging", "single-ticket"), ("single-ticket", "debugging")):
            with self.subTest(profile=profile):
                text = self.workflow(profile)
                self.assertIn(f"github.event.label.name == '{LABEL}'", text)
                self.assertIn(f"'profile:{profile}'", text)
                self.assertNotIn(f"profile:{other}", text)

    def test_golden_shared_label_manifest_has_one_trigger_component_for_each_profile(self) -> None:
        ids = [c["id"] for c in self.manifest()["components"]
               if c["id"].startswith("trigger.label")]
        self.assertEqual(sorted(ids), sorted(f"trigger.label.{p}" for p in PROFILES))

    def test_golden_shared_label_difference_names_the_file(self) -> None:
        golden = Path(self.folder.name) / "golden"
        update_golden(golden, self.files)
        self.assertEqual(golden_differences(golden, self.files), [])
        changed = WORKFLOWS["debugging"]
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
