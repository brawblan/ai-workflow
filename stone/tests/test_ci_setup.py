"""Issue #162: the optional `ci.setup` section of the repo config."""

import contextlib
import datetime as dt
import io
import re
import tempfile
import unittest
from pathlib import Path

import yaml

from stone import ci_setup, framework_check, render
from test_render import CONFIG, FRAMEWORK

WORKFLOW = ".github/workflows/cornerstone-checks.yml"
SHA = "a" * 40
SHA2 = "b" * 40
MARKER = "if: steps.marker.outputs.cornerstone == 'true'"


class CiSetupRenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def workflow(self, extra: str = "") -> str:
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG + extra, encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK, today=dt.date(2026, 10, 17))
        return (self.root / WORKFLOW).read_text(encoding="utf-8")

    def steps(self, text: str) -> list[dict]:
        job = yaml.safe_load(text)["jobs"]
        return next(iter(job.values()))["steps"]

    def names_or_uses(self, steps: list[dict]) -> list[str]:
        return [step.get("name") or step.get("uses", "") for step in steps]

    def test_node_renders_a_pinned_setup_node_step_before_install(self) -> None:
        text = self.workflow('ci: {setup: {node: "22"}}\n')
        steps = self.steps(text)
        index = next(i for i, s in enumerate(steps) if s.get("uses", "").startswith(
            "actions/setup-node@"))
        step = steps[index]
        self.assertRegex(step["uses"], r"^actions/setup-node@[0-9a-f]{40}$")
        self.assertEqual(step["with"], {"node-version": "22", "cache": "npm"})
        self.assertIsInstance(step["with"]["node-version"], str)
        install = next(i for i, s in enumerate(steps) if s.get("name") == "Install")
        self.assertLess(index, install)

    def test_steps_render_in_order_after_node_and_before_install(self) -> None:
        extra = f"""ci:
  setup:
    node: "22"
    steps:
      - name: Cache tools
        uses: actions/cache@{SHA}
        with:
          path: ~/.tools
          key: tools-1
      - run: echo one
      - name: Build
        run: |
          echo a
          echo b
"""
        steps = self.steps(self.workflow(extra))
        install = next(i for i, s in enumerate(steps) if s.get("name") == "Install")
        node = next(i for i, s in enumerate(steps) if s.get("uses", "").startswith(
            "actions/setup-node@"))
        cache = next(i for i, s in enumerate(steps) if s.get("uses") == f"actions/cache@{SHA}")
        echo = next(i for i, s in enumerate(steps) if s.get("run") == "echo one")
        build = next(i for i, s in enumerate(steps) if s.get("name") == "Build")
        self.assertLess(node, cache)
        self.assertLess(cache, echo)
        self.assertLess(echo, build)
        self.assertLess(build, install)
        self.assertEqual(steps[cache]["name"], "Cache tools")
        self.assertEqual(steps[cache]["with"], {"path": "~/.tools", "key": "tools-1"})
        self.assertEqual(steps[build]["run"].strip(), "echo a\necho b")

    def test_steps_without_node_still_render_before_install(self) -> None:
        steps = self.steps(self.workflow("ci: {setup: {steps: [{run: make deps}]}}\n"))
        run = next(i for i, s in enumerate(steps) if s.get("run") == "make deps")
        install = next(i for i, s in enumerate(steps) if s.get("name") == "Install")
        self.assertLess(run, install)
        self.assertFalse(any(s.get("uses", "").startswith("actions/setup-node") for s in steps))

    def test_opt_in_gives_each_setup_step_the_marker_if(self) -> None:
        extra = f"""adoption: opt-in
ci:
  setup:
    node: "22"
    steps:
      - uses: actions/cache@{SHA}
        with: {{path: x}}
      - run: echo one
      - name: Multi
        run: |
          echo a
          echo b
"""
        text = self.workflow(extra)
        steps = self.steps(text)
        install = next(i for i, s in enumerate(steps) if s.get("name") == "Install")
        setup = [s for s in steps[:install] if s.get("uses", "").startswith(
            ("actions/setup-node@", "actions/cache@")) or s.get("run") == "echo one"
            or s.get("name") == "Multi"]
        self.assertEqual(len(setup), 4)
        for step in setup:
            self.assertEqual(step.get("if"), "steps.marker.outputs.cornerstone == 'true'", step)

    def test_default_adoption_adds_no_marker_if_to_setup_steps(self) -> None:
        steps = self.steps(self.workflow('ci: {setup: {node: "22", steps: [{run: echo x}]}}\n'))
        for step in steps:
            if step.get("run") == "echo x" or step.get("uses", "").startswith(
                    "actions/setup-node@"):
                self.assertNotIn("if", step)

    def test_without_ci_setup_the_workflow_is_unchanged(self) -> None:
        base = self.workflow()
        self.assertEqual(self.workflow("ci: {}\n"), base)
        self.assertEqual(self.workflow("ci: {setup: {}}\n"), base)
        self.assertNotIn("setup-node", base)
        self.assertNotIn("$ci_setup", base)
        self.assertNotIn("ci_setup", base)

    def test_without_ci_setup_leaves_no_blank_line_before_install(self) -> None:
        base = self.workflow()
        # The template keeps one blank line between steps. The removed block adds no second one.
        self.assertNotRegex(base, r"\n[ \t]*\n[ \t]*\n")
        self.assertRegex(base, r"run: \|\n(?:.*\n)*?.*stone\" check-evidence[^\n]*\n\n"
                               r"      - name: Install\n")

    def test_with_ci_setup_the_other_steps_stay_the_same(self) -> None:
        base = self.steps(self.workflow())
        full = self.steps(self.workflow('ci: {setup: {node: "22"}}\n'))
        self.assertEqual([s for s in full if not s.get("uses", "").startswith(
            "actions/setup-node@")], base)

    def test_opt_in_without_ci_setup_matches_opt_in_with_empty_ci(self) -> None:
        self.assertEqual(self.workflow("adoption: opt-in\n"),
                         self.workflow("adoption: opt-in\nci: {}\n"))

    def test_render_is_idempotent_with_ci_setup(self) -> None:
        extra = 'ci: {setup: {node: "22", steps: [{run: echo x}]}}\n'
        self.assertEqual(self.workflow(extra), self.workflow(extra))

    def test_render_raises_for_an_invalid_ci_setup(self) -> None:
        for extra, message in (("ci: x\n", "'ci' must be a map"),
                               ("ci: {setup: {node: 22}}\n", "'ci.setup.node' must be a text"),
                               ("ci: {setup: {steps: [{run: a, uses: b}]}}\n", "needs one of"),
                               ("ci: {setup: {steps: [{uses: 'a/b@v4'}]}}\n", "commit SHA")):
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(render.RenderError, message):
                    self.workflow(extra)

    def test_stone_check_reports_an_invalid_ci_setup(self) -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(
            CONFIG + "ci: {setup: {node: 22}}\n", encoding="utf-8")
        findings = framework_check.check_config(self.root, FRAMEWORK)
        self.assertTrue(any("ci.setup.node" in f.message for f in findings), findings)

    def test_stone_check_accepts_a_valid_ci_setup(self) -> None:
        self.workflow(f'ci: {{setup: {{node: "22", steps: [{{uses: "a/b@{SHA}"}}]}}}}\n')
        self.assertEqual(framework_check.check_config(self.root, FRAMEWORK), [])


class CiSetupProblemsTest(unittest.TestCase):
    def has(self, config: dict, text: str) -> bool:
        return any(re.search(text, problem) for problem in ci_setup.problems(config))

    def test_no_ci_has_no_problems(self) -> None:
        self.assertEqual(ci_setup.problems({}), [])
        self.assertEqual(ci_setup.problems({"ci": None}), [])
        self.assertEqual(ci_setup.problems({"ci": {}}), [])

    def test_valid_setup_has_no_problems(self) -> None:
        config = {"ci": {"setup": {"node": "22", "steps": [
            {"name": "a", "uses": f"o/r@{SHA}", "with": {"k": "v"}},
            {"run": "echo a\necho b"}]}}}
        self.assertEqual(ci_setup.problems(config), [])

    def test_ci_not_a_map(self) -> None:
        for value in ("x", ["setup"], 3):
            with self.subTest(value=value):
                self.assertTrue(self.has({"ci": value}, "'ci' must be a map"))

    def test_unknown_ci_key(self) -> None:
        self.assertTrue(self.has({"ci": {"cache": 1}}, "'ci.cache' is not a key"))

    def test_setup_not_a_map(self) -> None:
        self.assertTrue(self.has({"ci": {"setup": "x"}}, "'ci.setup' must be a map"))

    def test_unknown_setup_key(self) -> None:
        self.assertTrue(self.has({"ci": {"setup": {"python": "3"}}},
                                 "'ci.setup.python' is not a key"))

    def test_node_must_be_a_string(self) -> None:
        for node in (22, 22.1, ["22"], True, ""):
            with self.subTest(node=node):
                self.assertTrue(self.has({"ci": {"setup": {"node": node}}},
                                         "'ci.setup.node' must be a text"))

    def test_steps_must_be_a_list(self) -> None:
        for steps in ({"run": "x"}, "x", 3):
            with self.subTest(steps=steps):
                self.assertTrue(self.has({"ci": {"setup": {"steps": steps}}},
                                         "'ci.setup.steps' must be a list"))

    def test_step_must_be_a_map(self) -> None:
        self.assertTrue(self.has({"ci": {"setup": {"steps": ["echo x"]}}}, "must be a map"))

    def test_step_with_both_uses_and_run(self) -> None:
        step = {"uses": f"o/r@{SHA}", "run": "x"}
        self.assertTrue(self.has({"ci": {"setup": {"steps": [step]}}}, "needs one of"))

    def test_step_with_neither_uses_nor_run(self) -> None:
        self.assertTrue(self.has({"ci": {"setup": {"steps": [{"name": "x"}]}}}, "needs one of"))

    def test_unknown_step_key(self) -> None:
        step = {"run": "x", "env": {"A": "b"}}
        self.assertTrue(self.has({"ci": {"setup": {"steps": [step]}}}, "has the key 'env'"))

    def test_uses_needs_a_40_hex_sha(self) -> None:
        for uses in ("o/r@v4", "o/r", f"o/r@{SHA[:39]}", f"o/r@{SHA}0", "o/r@" + "g" * 40):
            with self.subTest(uses=uses):
                self.assertTrue(self.has({"ci": {"setup": {"steps": [{"uses": uses}]}}},
                                         "commit SHA"))

    def test_uses_with_a_sha_is_valid(self) -> None:
        self.assertEqual(ci_setup.problems(
            {"ci": {"setup": {"steps": [{"uses": f"o/r@{SHA2}"}]}}}), [])

    def test_with_needs_uses(self) -> None:
        step = {"run": "x", "with": {"k": "v"}}
        self.assertTrue(self.has({"ci": {"setup": {"steps": [step]}}}, "'with'"))

    def test_with_must_be_a_map(self) -> None:
        step = {"uses": f"o/r@{SHA}", "with": ["k"]}
        self.assertTrue(self.has({"ci": {"setup": {"steps": [step]}}}, "'with'"))

    def test_problem_names_the_step_number(self) -> None:
        steps = [{"run": "ok"}, {"name": "bad"}]
        problems = ci_setup.problems({"ci": {"setup": {"steps": steps}}})
        self.assertTrue(any("item 2" in problem for problem in problems), problems)


class CiSectionKeyCheckTest(unittest.TestCase):
    """The keys of the `ci` section are checked in one place: ci_setup.section_problems."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def write(self, extra: str) -> None:
        (self.root / ".cornerstone" / "config.yaml").write_text(CONFIG + extra, encoding="utf-8")

    def findings(self, extra: str) -> list[str]:
        self.write(extra)
        return [str(f) for f in framework_check.check_config(self.root, FRAMEWORK)]

    def render_message(self, extra: str) -> str:
        self.write(extra)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(render.RenderError) as caught:
                render.render(self.root, FRAMEWORK, today=dt.date(2026, 10, 17))
        return str(caught.exception)

    def test_one_wrong_key_gives_one_finding(self) -> None:
        found = self.findings("ci: {cache: 1}\n")
        self.assertEqual(len(found), 1, found)
        self.assertIn("'ci.cache' is not a key", found[0])

    def test_ci_that_is_not_a_map_gives_one_finding(self) -> None:
        found = self.findings("ci: [a]\n")
        self.assertEqual(len(found), 1, found)
        self.assertIn("'ci' must be a map", found[0])

    def test_each_valid_key_alone_gives_no_finding(self) -> None:
        for line in ("ci: {env: {A: x}}", "ci: {secrets: [A]}", 'ci: {setup: {node: "22"}}',
                     "ci: {branches: [dev]}"):
            with self.subTest(line=line):
                self.assertEqual(self.findings(line + "\n"), [])

    def test_two_wrong_keys_give_two_findings(self) -> None:
        found = self.findings("ci: {cache: 1, zz: 2}\n")
        self.assertEqual(len(found), 2, found)
        self.assertEqual(sum("'ci.cache' is not a key" in f for f in found), 1)
        self.assertEqual(sum("'ci.zz' is not a key" in f for f in found), 1)

    def test_section_problems_gives_nothing_without_a_section(self) -> None:
        for config in ({}, {"ci": None}, {"ci": {}}):
            with self.subTest(config=config):
                self.assertEqual(ci_setup.section_problems(config), [])

    def test_section_problems_gives_one_error_for_a_non_map(self) -> None:
        for value in (["a"], "x", 3):
            with self.subTest(value=value):
                found = ci_setup.section_problems({"ci": value})
                self.assertEqual(len(found), 1, found)
                self.assertIn("'ci' must be a map", found[0])

    def test_section_problems_gives_one_error_for_each_unknown_key(self) -> None:
        found = ci_setup.section_problems({"ci": {"env": {}, "cache": 1, "zz": 2}})
        self.assertEqual(len(found), 2, found)

    def test_keys_are_the_four_section_keys(self) -> None:
        self.assertEqual(ci_setup.KEYS, ("env", "secrets", "setup", "branches"))

    def test_render_and_check_config_give_the_same_message(self) -> None:
        for line, text in (("ci: {cache: 1}", "'ci.cache' is not a key"),
                           ("ci: [a]", "'ci' must be a map")):
            with self.subTest(line=line):
                message = self.render_message(line + "\n")
                found = self.findings(line + "\n")
                self.assertEqual(len(found), 1, found)
                self.assertIn(text, message)
                self.assertIn(text, found[0])
                expected = ci_setup.section_problems({"ci": yaml.safe_load(line)["ci"]})[0]
                self.assertIn(expected, message)
                self.assertIn(expected, found[0])


if __name__ == "__main__":
    unittest.main()
