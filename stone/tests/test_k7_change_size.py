"""Tests for check K7 (change size) from `stone render` (roadmap item 6b, D27)."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import render

FRAMEWORK = Path(__file__).resolve().parents[2] / "framework"
TODAY = dt.date(2026, 10, 18)
K7 = ".cornerstone/checks/change_size.py"
CONFIG = """framework_version: 0.8.0
harness: claude-code
model_profile: claude-5
profiles: [{profiles}]
branches: {{integration: dev, main: main}}
commands: {{install: pip install ., test_unit: python -m unittest, all_checks: make check}}
paths: {{tests: [tests/], checks: [.github/workflows/, .cornerstone/checks/], plans: docs/plans/}}
owners: {{default: octocat}}
{extra}"""
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def render_into(root: Path, profiles: list[str], extra: str = "") -> render.Result:
    """Write a config for the profiles into root and render it."""
    (root / ".cornerstone").mkdir(parents=True, exist_ok=True)
    (root / ".cornerstone/config.yaml").write_text(
        CONFIG.format(profiles=", ".join(profiles), extra=extra), encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()):
        return render.render(root, FRAMEWORK, today=TODAY)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "-c", "init.defaultBranch=main", *args],
                   cwd=repo, env=GIT_ENV, check=True, capture_output=True)


def make_repo(repo: Path, added: int, deleted: int = 0) -> Path:
    """Make a repo: a base commit on main, then a feature commit with a known diff."""
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "old.txt").write_text("".join(f"o{i}\n" for i in range(100)), encoding="utf-8")
    (repo / "keep.txt").write_text("".join(f"k{i}\n" for i in range(50)), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "old.txt").write_text("".join(f"o{i}\n" for i in range(deleted, 100)), "utf-8")
    (repo / "new.txt").write_text("".join(f"n{i}\n" for i in range(added)), encoding="utf-8")
    (repo / "blob.bin").write_bytes(bytes(range(256)) * 200)  # binary: counts 0
    git(repo, "mv", "keep.txt", "moved.txt")  # a pure rename counts 0 with -M
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "feature")
    # main moves on after the branch point. Lines on main only must not count.
    git(repo, "checkout", "-q", "main")
    (repo / "main-only.txt").write_text("m\n" * 900, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "main moves")
    git(repo, "checkout", "-q", "feature")
    return repo


def limits_in(script: str) -> dict[str, int]:
    return json.loads(re.search(r"^LIMITS = (.*)$", script, re.M).group(1))


class RenderK7Test(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_ac1_k7_profile_writes_the_check_and_a_manifest_entry(self) -> None:
        result = render_into(self.root, ["single-ticket"])
        self.assertIn(K7, result.wrote)
        manifest = yaml.safe_load((self.root / render.MANIFEST).read_text(encoding="utf-8"))
        entry = next(c for c in manifest["components"] if c["id"] == "check.k7")
        self.assertEqual((entry["eval"], entry["review_by"]), ("evals/check-k7/", "2027-04-18"))

    def test_ac1_profiles_without_k7_do_not_get_the_check(self) -> None:
        for name in ("bug-triage", "code-audit", "spike"):
            with self.subTest(profile=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.assertNotIn(K7, render_into(root, [name]).wrote)
                self.assertFalse((root / K7).exists())
                self.assertNotIn("check.k7", (root / render.MANIFEST).read_text("utf-8"))

    def test_ac2_limits_have_one_entry_per_k7_profile(self) -> None:
        render_into(self.root, ["single-ticket", "dependency-upgrade", "debugging", "spike"])
        self.assertEqual(limits_in((self.root / K7).read_text("utf-8")),
                         {"debugging": 200, "dependency-upgrade": 300, "single-ticket": 600})

    def test_ac2_repo_limit_only_tightens(self) -> None:
        for repo_limit, want in ((250, {"debugging": 200, "dependency-upgrade": 250}),
                                 (1000, {"debugging": 200, "dependency-upgrade": 300})):
            with self.subTest(limit=repo_limit), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                render_into(root, ["dependency-upgrade", "debugging"],
                            f"limits: {{pr_changed_lines: {repo_limit}}}\n")
                self.assertEqual(limits_in((root / K7).read_text("utf-8")), want)

    def test_ac2_bad_repo_limit_stops_render_before_any_write(self) -> None:
        for value in ("0", "-5", "'600'", "1.5", "true"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                with self.assertRaises(render.RenderError):
                    render_into(root, ["single-ticket"], f"limits: {{pr_changed_lines: {value}}}\n")
                self.assertEqual([p.name for p in root.rglob("*") if p.is_file()], ["config.yaml"])

    def test_ac3_workflow_has_k7_after_k6_with_env_only_and_warn_mode(self) -> None:
        render_into(self.root, ["single-ticket"])
        workflow = (self.root / ".github/workflows/cornerstone-checks.yml").read_text("utf-8")
        steps = yaml.safe_load(workflow)["jobs"]["checks"]["steps"]
        names = [s.get("name", "") for s in steps]
        k7 = steps[names.index("K7 change size")]
        self.assertEqual(names.index("K7 change size"), names.index("K6 protected paths") + 1)
        self.assertNotIn("${{", k7["run"])
        self.assertIn("github.event.pull_request.body", k7["env"]["PR_BODY"])
        self.assertIn("github.base_ref", k7["env"]["BASE_REF"])
        for flag in ("--mode warn", "--format github", "--body -"):
            self.assertIn(flag, k7["run"])


class ScriptTest(unittest.TestCase):
    """Run the rendered script. Limits: debugging 200, dependency-upgrade 300, single-ticket 600."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        base = Path(cls.folder.name)
        render_into(base / "render", ["single-ticket", "dependency-upgrade", "debugging"])
        cls.script = base / "render" / K7
        cls.exact = make_repo(base / "exact", added=160, deleted=40)  # 200 lines
        cls.over = make_repo(base / "over", added=250)

    def run_k7(self, repo: Path, body: str | None, *args: str, base: str = "main"):
        argv = [sys.executable, str(self.script), base, *args]
        if body is not None:
            argv += ["--body", "-"]
        return subprocess.run(argv, cwd=repo, input=body or "", env=GIT_ENV,
                              capture_output=True, text=True)

    def test_ac4_counts_added_plus_deleted_from_the_merge_base(self) -> None:
        run = self.run_k7(self.exact, "Profile: debugging\n")
        self.assertEqual(run.returncode, 0, run.stdout)
        self.assertIn("200 changed lines", run.stdout)

    def test_ac4_profile_line_selects_the_limit_in_each_form(self) -> None:
        for body in ("Profile: dependency-upgrade", "**Profile:** `dependency-upgrade`",
                     "PROFILE: Dependency-Upgrade", "## Ticket\n\nprofile: dependency-upgrade"):
            with self.subTest(body=body):
                self.assertEqual(self.run_k7(self.over, body).returncode, 0)

    def test_ac4_no_known_profile_uses_the_smallest_limit_with_a_notice(self) -> None:
        for body in (None, "", "No profile here.", "Profile: no-such-profile"):
            with self.subTest(body=body):
                run = self.run_k7(self.over, body)
                self.assertEqual(run.returncode, 1, run.stdout)
                self.assertIn("notice", run.stdout)
                self.assertIn("limit for debugging is 200", run.stdout)

    def test_ac4_over_the_limit_blocks_by_default_and_warns_in_warn_mode(self) -> None:
        block = self.run_k7(self.over, "Profile: debugging")
        self.assertEqual(block.returncode, 1)
        for text in ("error", "Split the PR", "Waiver (P10)"):
            self.assertIn(text, block.stdout)
        warn = self.run_k7(self.over, "Profile: debugging", "--mode", "warn")
        self.assertEqual((warn.returncode, "warning" in warn.stdout), (0, True))

    def test_ac4_waiver_with_text_passes_with_a_notice(self) -> None:
        for waiver in ("## Waiver (P10)\nGenerated lock file. Owner: octocat. Ends 2026-11-01.",
                       "**Waiver (P10)**\nGenerated lock file."):
            with self.subTest(waiver=waiver):
                run = self.run_k7(self.over, f"Profile: debugging\n\n{waiver}\n\n## Risks\nNone\n")
                self.assertEqual(run.returncode, 0, run.stdout)
                self.assertIn("notice", run.stdout)

    def test_ac4_empty_none_or_fenced_waiver_does_not_count(self) -> None:
        for waiver in ("## Waiver (P10)\n\n## Risks\nLow.", "## Waiver (P10)\nNone",
                       "```\n## Waiver (P10)\nBig diff.\n```"):
            with self.subTest(waiver=waiver):
                run = self.run_k7(self.over, f"Profile: debugging\n\n{waiver}\n")
                self.assertEqual(run.returncode, 1, run.stdout)

    def test_ac4_at_or_under_the_limit_passes(self) -> None:
        self.assertEqual(self.run_k7(self.over, "Profile: single-ticket").returncode, 0)
        self.assertEqual(self.run_k7(self.exact, None).returncode, 0)

    def test_ac4_github_format_prints_annotations(self) -> None:
        cases = (("Profile: debugging", "block", "::error title=K7::"),
                 ("Profile: debugging", "warn", "::warning title=K7::"),
                 ("Profile: single-ticket", "block", "::notice title=K7::"))
        for body, mode, want in cases:
            with self.subTest(mode=mode, body=body):
                run = self.run_k7(self.over, body, "--mode", mode, "--format", "github")
                self.assertTrue(any(line.startswith(want) for line in run.stdout.splitlines()),
                                run.stdout)

    def test_ac4_unknown_base_exits_2(self) -> None:
        self.assertEqual(self.run_k7(self.over, "", base="origin/no-such-branch").returncode, 2)


if __name__ == "__main__":
    unittest.main()
