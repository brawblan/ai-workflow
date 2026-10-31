"""Issue #123: specialist reviews: the config, the match, the reports, and render."""

import contextlib
import datetime as dt
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import cli, framework_check, render, specialists
from test_render import CONFIG, FRAMEWORK

TODAY = dt.date(2026, 10, 17)
TEMPLATE = FRAMEWORK / "adapters" / "claude-code" / "templates" / "lib" / "path_match.py"
HARNESS = FRAMEWORK / "adapters" / "claude-code"
BAD_GLOB = {"id": "a", "run": "x", "when": {"paths": ["src/[a"]}}


def put_module(root: Path) -> Path:
    """Copy the path match template to the place where render writes it."""
    target = root / specialists.MATCH_MODULE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMPLATE, target)
    return target
A11Y = """specialists:
  - id: accessibility
    run: claude --agent accessibility-lead
    when:
      paths: ["**/components/**", "src/*.css.js"]
      personas_with: [screen reader]
      labels: [a11y]
    blocks: true
  - id: security
    run: /security-review
    owner: sec-lead
    eval: evals/security/
"""
PERSONAS = """## Sam
- id: sam
- who: A user
- jobs:
  - sam.J1: When I read, I want to hear it, so that I can work
- limits:
  - device: phone
  - access: uses a screen reader
- evidence: assumed
"""


class ConfigTest(unittest.TestCase):
    def found(self, section: object) -> list[str]:
        return specialists.problems({"specialists": section})

    def test_valid_section(self) -> None:
        self.assertEqual(self.found(yaml.safe_load(A11Y.split("specialists:")[1])), [])

    def test_bad_values(self) -> None:
        for item, message in (
                ({"run": "x"}, "needs an 'id'"),
                ({"id": "A b", "run": "x"}, "needs an 'id'"),
                ({"id": "a"}, "needs 'run'"),
                ({"id": "a", "run": "x", "stage": "late"}, "stage 'late'"),
                ({"id": "a", "run": "x", "blocks": "yes"}, "'blocks' to be true or false"),
                ({"id": "a", "run": "x", "when": {"files": ["x"]}}, "'when.files'"),
                ({"id": "a", "run": "x", "when": {"paths": "x"}}, "list of text values"),
                ({"id": "a", "run": "x", "when": {"labels": []}}, "list of text values"),
                ({"id": "a", "run": "x", "color": 1}, "key 'color'"),
                ({"id": "a", "run": "x", "owner": " "}, "empty 'owner'")):
            with self.subTest(item=item):
                self.assertTrue(any(message in m for m in self.found([item])), self.found([item]))

    def test_duplicate_id_and_wrong_shapes(self) -> None:
        item = {"id": "a", "run": "x"}
        self.assertTrue(any("used twice" in m for m in self.found([item, item])))
        self.assertTrue(any("must be a list" in m for m in self.found({"id": "a"})))
        self.assertTrue(any("must be a map" in m for m in self.found(["a"])))


class MatchTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        put_module(self.root)
        self.covers = specialists.path_matcher(self.root)

    def test_glob(self) -> None:
        match = lambda pattern, path: self.covers([pattern], path)  # noqa
        self.assertTrue(match("**/components/**", "src/ui/components/Button.tsx"))
        self.assertTrue(match("**/components/**", "components/a.tsx"))
        self.assertTrue(match("src/*.css.js", "src/a.css.js"))
        self.assertFalse(match("src/*.css.js", "src/x/a.css.js"))
        self.assertTrue(match("docs/", "docs/a/b.md"))
        self.assertFalse(match("docs/", "docs2/a.md"))
        self.assertTrue(match("a?.py", "ab.py"))
        self.assertFalse(match("*.py", "a/b.py"))

    def test_d65_rules(self) -> None:
        match = lambda pattern, path: self.covers([pattern], path)  # noqa
        self.assertTrue(match("docs", "docs/a.md"))
        self.assertTrue(match("src/*", "src/x/a.py"))
        self.assertTrue(match("src/[ab].py", "src/a.py"))
        self.assertFalse(match("./src/*.py", "src/a.py"))

    def test_d65_rules_through_reasons(self) -> None:
        for pattern, path in (("docs", "docs/a.md"), ("src/*", "src/x/a.py"),
                              ("src/[ab].py", "src/a.py")):
            spec = {"id": "a", "run": "x", "when": {"paths": [pattern]}}
            self.assertTrue(specialists.reasons(spec, [path], [], {}, self.covers), pattern)
        spec = {"id": "a", "run": "x", "when": {"paths": ["./src/*.py"]}}
        self.assertEqual(specialists.reasons(spec, ["src/a.py"], [], {}, self.covers), [])

    def test_reasons(self) -> None:
        spec = yaml.safe_load(A11Y)["specialists"][0]
        covers = self.covers
        self.assertEqual(specialists.reasons(spec, ["README.md"], [], {}, covers), [])
        self.assertIn("paths: src/a.css.js matches src/*.css.js",
                      specialists.reasons(spec, ["src/a.css.js"], [], {}, covers))
        self.assertEqual(specialists.reasons(spec, [], ["A11Y"], {}, covers), ["labels: A11Y"])
        self.assertEqual(
            specialists.reasons(spec, [], [], {"sam": ["Uses a Screen Reader"]}, covers),
            ["personas_with: 'screen reader' in the limits of sam"])

    def test_no_trigger_always_matches(self) -> None:
        self.assertEqual(specialists.reasons({"id": "x", "run": "y"}, [], [], {}, None), ["always"])

    def test_labels_only_needs_no_covers(self) -> None:
        spec = {"id": "a", "run": "x", "when": {"labels": ["a11y"]}}
        self.assertEqual(specialists.reasons(spec, ["a.py"], ["a11y"], {}, None), ["labels: a11y"])

    def test_bad_glob_raises(self) -> None:
        with self.assertRaises(specialists.SpecialistError) as caught:
            specialists.reasons(BAD_GLOB, ["src/a.py"], [], {}, self.covers)
        self.assertIn("'when.paths'", str(caught.exception))
        self.assertIn("'a'", str(caught.exception))

    def test_missing_or_broken_module(self) -> None:
        for text in (None, "def (", "x = 1\n"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                if text is not None:
                    (root / specialists.MATCH_MODULE).parent.mkdir(parents=True)
                    (root / specialists.MATCH_MODULE).write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(specialists.SpecialistError, "Run stone render"):
                    specialists.path_matcher(root)


class RunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()
        (self.root / "constitution").mkdir()
        put_module(self.root)
        (self.root / "constitution" / "personas.md").write_text(PERSONAS, encoding="utf-8")
        self.config = yaml.safe_load(CONFIG + A11Y)
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG + A11Y, encoding="utf-8")
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "a@example.com"),
                     ("config", "user.name", "a")):
            self.git(*args)
        (self.root / "a.txt").write_text("a\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("update-ref", "refs/remotes/origin/dev", "HEAD")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def change(self, path: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")

    def run_for(self, **kwargs: object) -> tuple[list[specialists.Row], str]:
        args = {"labels": [], "persona_ids": [], "ticket": "T1", **kwargs}
        return specialists.run(self.root, self.config, "origin/dev", **args)  # type: ignore

    def report(self, name: str, text: str) -> None:
        path = self.root / "docs" / "reports" / f"T1.{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_only_the_security_specialist_without_a_trigger_matches(self) -> None:
        self.change("README.md")
        rows, text = self.run_for()
        self.assertEqual([r.spec["id"] for r in rows], ["security"])
        self.assertEqual(rows[0].status, "missing")
        self.assertIn("Missing: start `/security-review`", text)
        self.assertIn("docs/reports/T1.security.md", text)

    def test_path_label_and_persona_triggers(self) -> None:
        self.change("src/components/B.tsx")
        self.assertEqual([r.spec["id"] for r in self.run_for()[0]], ["accessibility", "security"])
        rows, _ = self.run_for(persona_ids=["sam"])
        self.assertIn("personas_with", " ".join(rows[0].why))

    def test_label_only(self) -> None:
        self.change("README.md")
        rows, _ = self.run_for(labels=["a11y"])
        self.assertEqual([r.spec["id"] for r in rows], ["accessibility", "security"])

    def test_reviewed_and_blocking(self) -> None:
        self.change("src/components/B.tsx")
        self.report("accessibility", "- Severity: medium\n")
        self.report("security", "Severity: high\n")  # security does not block
        rows, _ = self.run_for()
        self.assertEqual([r.status for r in rows], ["reviewed", "reviewed"])
        self.report("accessibility", "1. **Severity:** high\n")
        rows, text = self.run_for()
        self.assertEqual(rows[0].status, "blocking")
        self.assertIn("G4 cannot pass", text)

    def test_nothing_matches(self) -> None:
        self.config["specialists"] = self.config["specialists"][:1]
        self.change("README.md")
        rows, text = self.run_for()
        self.assertEqual(rows, [])
        self.assertIn("No specialist review matched", text)

    def test_unknown_persona_and_base(self) -> None:
        with self.assertRaisesRegex(specialists.SpecialistError, "persona 'ghost'"):
            self.run_for(persona_ids=["ghost"])
        with self.assertRaisesRegex(specialists.SpecialistError, "cannot diff"):
            specialists.run(self.root, self.config, "origin/none", [], [], "T1")

    def test_missing_module_fails_when_a_path_trigger_exists(self) -> None:
        self.change("README.md")
        (self.root / specialists.MATCH_MODULE).unlink()
        with self.assertRaisesRegex(specialists.SpecialistError, "Run stone render"):
            self.run_for()

    def test_missing_module_is_fine_without_path_triggers(self) -> None:
        self.config["specialists"][0]["when"] = {"labels": ["a11y"]}
        self.change("README.md")
        (self.root / specialists.MATCH_MODULE).unlink()
        rows, _ = self.run_for(labels=["a11y"])
        self.assertEqual([r.spec["id"] for r in rows], ["accessibility", "security"])

    def test_cli_missing_module_exits_2(self) -> None:
        self.change("README.md")
        (self.root / specialists.MATCH_MODULE).unlink()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["specialists", "--root", str(self.root), "--base", "origin/dev",
                             "--ticket", "T1"])
        self.assertEqual(code, 2)
        self.assertIn("Run stone render", out.getvalue() + err.getvalue())

    def test_cli_exit_codes(self) -> None:
        self.change("README.md")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["specialists", "--root", str(self.root), "--base", "origin/dev",
                             "--ticket", "T1"])
        self.assertEqual(code, 1)
        self.report("security", "Severity: low\n")
        with contextlib.redirect_stdout(out):
            code = cli.main(["specialists", "--root", str(self.root), "--base", "origin/dev",
                             "--ticket", "T1"])
        self.assertEqual(code, 0)
        with contextlib.redirect_stdout(out):
            code = cli.main(["specialists", "--root", str(self.root), "--ticket", "T1",
                             "--personas", "ghost", "--base", "origin/dev"])
        self.assertEqual(code, 2)


class RenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def render(self, extra: str) -> str:
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG + extra, encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            render.render(self.root, FRAMEWORK, today=TODAY)
        return err.getvalue()

    def manifest(self) -> dict:
        return {e["id"]: e for e in yaml.safe_load(
            (self.root / render.MANIFEST).read_text())["components"]}

    def test_no_specialists_changes_nothing(self) -> None:
        self.render("")
        self.assertFalse((self.root / specialists.DOC).exists())
        self.assertNotIn("specialist", (self.root / ".claude/agents/reviewer.md").read_text())
        self.assertFalse([i for i in self.manifest() if i.startswith("specialist")])

    def test_document_reviewer_and_manifest(self) -> None:
        err = self.render(A11Y)
        doc = (self.root / specialists.DOC).read_text(encoding="utf-8")
        trigger = ("paths: `**/components/**`, `src/*.css.js`; personas_with: `screen reader`; "
                   "labels: `a11y`")
        self.assertIn(f"| 1     | accessibility | `claude --agent accessibility-lead` | {trigger} "
                      "| yes    |", doc)
        self.assertIn(f"| 2     | security      | `/security-review`                  | "
                      f"{'always':<{len(trigger)}} | no     |", doc)
        self.assertIn(f"| ----- | ------------- | ----------------------------------- | "
                      f"{'-' * len(trigger)} | ------ |", doc)
        self.assertEqual(doc.splitlines()[1], "")  # a blank line follows the comment
        widths = {len(line) for line in doc.splitlines() if line.startswith("|")}
        self.assertEqual(len(widths), 1)  # every table line has the same width
        self.assertIn("`docs/reports/<ticket-id>.<id>.md`", doc)
        self.assertIn("Also read the specialist findings that `.cornerstone/specialists.md` lists.",
                      (self.root / ".claude/agents/reviewer.md").read_text())
        manifest = self.manifest()
        a11y, security = manifest["specialist.accessibility"], manifest["specialist.security"]
        self.assertEqual((a11y["source"], a11y["owner"], a11y["review_by"]),
                         ("repo", "octocat", "2027-04-17"))
        self.assertEqual((security["owner"], security["eval"]), ("sec-lead", "evals/security/"))
        self.assertIn("specialist.accessibility has no eval plan", err)
        self.assertNotIn("specialist.security has no eval plan", err)
        self.assertEqual(manifest["doc.specialists"]["source"], "framework")

    def test_second_render_keeps_dates_and_removes_a_dropped_specialist(self) -> None:
        self.render(A11Y)
        first = self.manifest()["specialist.accessibility"]
        (self.root / "extra.txt").write_text("x")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK, today=dt.date(2027, 1, 5))
        self.assertEqual(self.manifest()["specialist.accessibility"]["added"], first["added"])
        self.render(A11Y.split("  - id: security")[0])
        self.assertNotIn("specialist.security", self.manifest())

    def test_hand_written_repo_entries_are_kept(self) -> None:
        self.render(A11Y)
        path = self.root / render.MANIFEST
        data = yaml.safe_load(path.read_text())
        data["components"].append({"id": "rule.mine", "kind": "rule", "source": "repo",
                                   "owner": "x", "eval": "e", "review_by": "2027-01-01"})
        path.write_text(yaml.safe_dump(data))
        self.render(A11Y)
        self.assertIn("rule.mine", self.manifest())

    def test_check_passes_and_fails(self) -> None:
        self.render(A11Y)
        self.assertEqual([f.message for f in framework_check.check_components(self.root, FRAMEWORK)], [])
        with self.assertRaisesRegex(render.RenderError, "needs 'run'"):
            self.render("specialists:\n  - id: a\n")

    def test_bad_when_paths_glob_fails_check_and_render(self) -> None:
        config = {"specialists": [BAD_GLOB]}
        found = framework_check.path_pattern_problems(config, HARNESS)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("'when.paths' of the specialist 'a': "), found)
        good = {"specialists": [{"id": "a", "run": "x", "when": {"paths": ["src/*.py", "docs/"]}}]}
        self.assertEqual(framework_check.path_pattern_problems(good, HARNESS), [])
        with self.assertRaisesRegex(render.RenderError, "'when.paths' of the specialist 'a'"):
            self.render("specialists:\n  - id: a\n    run: x\n"
                        "    when:\n      paths: [\"src/[a\"]\n")


if __name__ == "__main__":
    unittest.main()
