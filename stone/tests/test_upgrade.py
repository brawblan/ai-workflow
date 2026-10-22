"""Issue #141: upgrades.yaml, stone upgrade, and the version warning of stone check."""

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

import stone
from stone import cli, framework_check, render, upgrade
from test_render import CONFIG, FRAMEWORK

RELEASES = """versions:
  - version: 2.0.0
    kind: major
    released: 2027-03-01
    summary: Rename a key.
    config:
      added: [{key: newkey, default: 1}]
      renamed: [{from: paths.old, to: paths.new}]
      removed: [{key: legacy, note: Gone.}]
    files: [{path: .cornerstone/checks/protected_paths.py, change: changed}]
    steps: ["Do a thing."]
  - version: 1.1.0
    kind: minor
    released: 2027-01-01
    summary: Add a key.
    config:
      added: [{key: delivery, default: ci}]
  - version: 1.0.0
    kind: major
    released: 2026-10-21
    summary: First.
"""


def write_framework(folder: Path, text: str) -> Path:
    framework = folder / "framework"
    shutil.copytree(FRAMEWORK, framework)
    (framework / "upgrades.yaml").write_text(text, encoding="utf-8")
    return framework


class RecordTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.framework = self.root / "framework"
        self.framework.mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def found(self, text: str) -> list[str]:
        (self.framework / "upgrades.yaml").write_text(text, encoding="utf-8")
        return upgrade.problems(self.framework)

    def test_the_real_record_is_valid(self) -> None:
        self.assertEqual(upgrade.problems(FRAMEWORK), [])

    def test_the_newest_released_version_is_the_version_of_stone(self) -> None:
        released = [v for v in upgrade.load(FRAMEWORK) if v.get("released")]
        self.assertEqual(str(released[0]["version"]), stone.__version__)
        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
        self.assertIn(f'version = "{stone.__version__}"', pyproject)

    def test_valid_record(self) -> None:
        self.assertEqual(self.found(RELEASES), [])

    def test_no_file_and_bad_shapes(self) -> None:
        self.assertTrue(any("no file" in m for m in upgrade.problems(self.framework)))
        self.assertTrue(any("must be a list" in m for m in self.found("versions: 1\n")))

    def test_bad_values(self) -> None:
        base = RELEASES.split("  - version: 1.1.0")[0]
        for old, new, message in (
                ("version: 2.0.0", "version: 2.0", "not a version"),
                ("kind: major\n    released: 2027", "kind: huge\n    released: 2027", "kind 'huge'"),
                ("summary: Rename a key.", "summary: ''", "needs a 'summary'"),
                ("released: 2027-03-01", "released: soon", "'released' to be a date"),
                ("renamed: [{from: paths.old, to: paths.new}]", "renamed: [{from: a}]",
                 "bad item in 'config.renamed'"),
                ("change: changed", "change: moved", "bad item in 'files'"),
                ('steps: ["Do a thing."]', "steps: [1]", "'steps' to be a list of text")):
            with self.subTest(message=message):
                text = (base + "  - version: 1.0.0\n    kind: major\n    released: 2026-10-21\n"
                        "    summary: First.\n").replace(old, new)
                self.assertTrue(any(message in m for m in self.found(text)), self.found(text))

    def test_order_kind_and_dates(self) -> None:
        wrong_order = RELEASES.replace("version: 2.0.0", "version: 0.9.0")
        self.assertTrue(any("must be newer" in m for m in self.found(wrong_order)))
        wrong_kind = RELEASES.replace("version: 1.1.0\n    kind: minor", "version: 1.1.0\n    kind: patch")
        self.assertTrue(any("is a minor release after 1.0.0, but its kind is 'patch'" in m
                            for m in self.found(wrong_kind)))
        patch = RELEASES.replace("version: 1.1.0\n    kind: minor", "version: 1.0.1\n    kind: patch")
        self.assertTrue(any("patch release, so it cannot change the config" in m
                            for m in self.found(patch)))
        minor = RELEASES.replace("version: 2.0.0\n    kind: major", "version: 1.2.0\n    kind: minor")
        self.assertTrue(any("minor release, so it cannot rename or remove" in m
                            for m in self.found(minor)))
        undated = RELEASES.replace("released: 2027-01-01", "released: null")
        self.assertTrue(any("not the newest" in m for m in self.found(undated)))
        self.assertEqual(self.found(RELEASES.replace("released: 2027-03-01", "released: null")), [])


class PlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()
        self.framework = write_framework(self.root, RELEASES)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def config(self, extra: str = "", version: str = "1.0.0") -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(
            CONFIG.replace("0.1.0", version) + extra, encoding="utf-8")

    def plan(self, target: str | None = None) -> tuple[str, list[str], int]:
        with contextlib.redirect_stderr(io.StringIO()):
            return upgrade.plan(self.root, self.framework, target)

    def test_plan_lists_each_release_and_the_actions(self) -> None:
        self.config("legacy: 1\ndelivery: ci\n")
        text, actions, code = self.plan()
        self.assertIn("stone upgrade: 1.0.0 -> 2.0.0", text)
        self.assertIn("This is a major upgrade over 2 release(s).", text)
        self.assertIn("config add delivery, default ci: present", text)
        self.assertIn("config add newkey, default 1: not set (optional)", text)
        self.assertIn("config remove legacy - Gone.", text)
        self.assertIn("file changed: .cornerstone/checks/protected_paths.py", text)
        self.assertIn("step: Do a thing.", text)
        self.assertIn("Render dry run:", text)
        self.assertEqual(actions, ["Remove the config key 'legacy'."])
        self.assertEqual(code, 1)

    def test_rename_needs_an_action_only_if_the_key_is_set(self) -> None:
        self.config()
        self.assertEqual(self.plan()[1:], ([], 0))
        path = self.root / ".cornerstone" / "config.yaml"
        path.write_text(path.read_text().replace("paths:\n", "paths:\n  old: x\n"))
        _, actions, code = self.plan()
        self.assertEqual((actions, code),
                         (["Rename the config key 'paths.old' to 'paths.new'."], 1))

    def test_target_and_up_to_date(self) -> None:
        self.config()
        text, actions, code = self.plan("1.1.0")
        self.assertIn("1.0.0 -> 1.1.0", text)
        self.assertNotIn("newkey", text)
        self.assertEqual(self.plan("1.0.0")[0].splitlines()[-1],
                         "Nothing to do. The config is at this version.")

    def test_errors(self) -> None:
        self.config(version="2.0.0")
        with self.assertRaisesRegex(upgrade.UpgradeError, "not in upgrades.yaml"):
            self.plan("3.0.0")
        self.config(version="3.0.0")
        with self.assertRaisesRegex(upgrade.UpgradeError, "downgrade is not supported"):
            self.plan("2.0.0")

    def test_apply_sets_the_version_and_renders(self) -> None:
        self.config(version="1.1.0")
        text = (self.root / ".cornerstone" / "config.yaml").read_text()
        (self.root / ".cornerstone" / "config.yaml").write_text(
            text.replace("framework_version: 1.1.0", "framework_version: 1.1.0   # tag"))
        with contextlib.redirect_stderr(io.StringIO()):
            written = upgrade.apply(self.root, self.framework, "2.0.0")
        config = (self.root / ".cornerstone" / "config.yaml").read_text()
        self.assertIn("framework_version: 2.0.0   # tag", config)
        self.assertTrue(written)
        self.assertTrue((self.root / ".claude" / "agents" / "implementer.md").exists())
        manifest = yaml.safe_load((self.root / render.MANIFEST).read_text())
        self.assertEqual(manifest["framework_version"], "2.0.0")

    def test_apply_stops_when_a_person_must_act(self) -> None:
        self.config("legacy: 1\n")
        with self.assertRaisesRegex(upgrade.UpgradeError, "1 action\\(s\\) need a person"):
            with contextlib.redirect_stderr(io.StringIO()):
                upgrade.apply(self.root, self.framework, None)
        self.assertIn("framework_version: 1.0.0",
                      (self.root / ".cornerstone" / "config.yaml").read_text())

    def test_a_drift_is_an_action(self) -> None:
        self.config()
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, self.framework)
        (self.root / ".claude" / "agents" / "tester.md").write_text("changed by a person\n")
        _, actions, code = self.plan()
        self.assertEqual(code, 1)
        self.assertTrue(any("Resolve the drift in .claude/agents/tester.md" in a for a in actions))

    def test_cli_exit_codes(self) -> None:
        self.config()
        base = ["upgrade", "--root", str(self.root), "--framework", str(self.framework)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(base + ["--to", "1.1.0"]), 0)
            self.assertEqual(cli.main(base + ["--to", "9.9.9"]), 2)
        self.assertIn("1.0.0 -> 1.1.0", out.getvalue())


class VersionWarningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def found(self, version: str | None) -> list:
        text = "harness: x\n" + (f"framework_version: {version}\n" if version else "")
        (self.root / ".cornerstone" / "config.yaml").write_text(text, encoding="utf-8")
        return framework_check.check_version(self.root)

    def test_same_version_no_finding(self) -> None:
        self.assertEqual(self.found(stone.__version__), [])

    def test_older_and_newer_warn_without_blocking(self) -> None:
        older = self.found("0.5.0")
        self.assertEqual((older[0].severity, "older than the installed stone" in older[0].message),
                         ("warning", True))
        self.assertIn("Run stone upgrade", older[0].message)
        newer = self.found("99.0.0")
        self.assertIn("newer than the installed stone", newer[0].message)
        self.assertIn("Install a newer stone", newer[0].message)

    def test_no_version_or_a_bad_one_gives_no_finding(self) -> None:
        self.assertEqual(self.found(None), [])
        self.assertEqual(self.found("latest"), [])


if __name__ == "__main__":
    unittest.main()
