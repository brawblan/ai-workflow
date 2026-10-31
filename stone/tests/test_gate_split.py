"""Issue #224: stone gate --split-checks."""

import contextlib
import datetime as dt
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from stone import cli, gate, render
from test_render import CONFIG, FRAMEWORK


class SplitCommandsTest(unittest.TestCase):
    def test_splits_on_and(self) -> None:
        self.assertEqual(gate.split_commands("a && b && c d"), ["a", "b", "c d"])

    def test_splits_without_spaces(self) -> None:
        self.assertEqual(gate.split_commands("a&&b"), ["a", "b"])

    def test_one_command_is_unchanged(self) -> None:
        self.assertEqual(gate.split_commands("make check"), ["make check"])

    def test_and_inside_quotes_does_not_split(self) -> None:
        for command in ('echo "a && b"', "echo 'a && b'", "echo 'a' && echo \"b && c\""):
            with self.subTest(command=command):
                expected = ["echo 'a'", 'echo "b && c"'] if command.count("&&") == 2 else [command]
                self.assertEqual(gate.split_commands(command), expected)

    def test_other_operators_do_not_split(self) -> None:
        for command in ("a && b || c", "a && b; c", "a | b && c", "a && b &", "(a) && b",
                        "a && `b`", "a && b # note", "a &&\nb", "a && b\nc"):
            with self.subTest(command=command):
                self.assertEqual(gate.split_commands(command), [command])

    def test_unclosed_quote_does_not_split(self) -> None:
        for command in ("a && echo 'b", 'a && echo "b'):
            with self.subTest(command=command):
                self.assertEqual(gate.split_commands(command), [command])

    def test_empty_part_does_not_split(self) -> None:
        for command in ("a &&", "&& a", "a && && b"):
            with self.subTest(command=command):
                self.assertEqual(gate.split_commands(command), [command])

    def test_shell_state_command_does_not_split(self) -> None:
        for word in ("cd", "pushd", "popd", "export", "source", ".", "set", "unset", "alias"):
            for command in (f"{word} x && b", f"a && {word} x"):
                with self.subTest(command=command):
                    self.assertEqual(gate.split_commands(command), [command])

    def test_assignment_only_part_does_not_split(self) -> None:
        for command in ("A=1 && b", "a && B_2=x"):
            with self.subTest(command=command):
                self.assertEqual(gate.split_commands(command), [command])

    def test_assignment_before_a_command_splits(self) -> None:
        self.assertEqual(gate.split_commands("A=1 a && b"), ["A=1 a", "b"])


class PlanTest(unittest.TestCase):
    def config(self, all_checks: str) -> dict:
        return {"commands": {"all_checks": all_checks}, "commits": {"trailers": "none"}}

    def plan(self, all_checks: str, split: bool) -> tuple[list[str], str]:
        root = Path(tempfile.mkdtemp())
        (root / gate.CHECKS).mkdir(parents=True)
        (root / gate.CHECKS / "change_size.py").write_text("", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            steps = gate.plan(root, self.config(all_checks), "origin/dev", None, split_checks=split)
        return [step.name for step in steps if step.name.startswith("All checks")], err.getvalue()

    def test_split_gives_one_step_per_command(self) -> None:
        names, err = self.plan("lint && test", True)
        self.assertEqual(names, ["All checks: `lint`", "All checks: `test`"])
        self.assertEqual(err, "")

    def test_default_is_one_step(self) -> None:
        names, err = self.plan("lint && test", False)
        self.assertEqual(names, ["All checks"])
        self.assertEqual(err, "")

    def test_split_option_without_a_split_warns(self) -> None:
        for command in ("make check", "a || b", "cd x && b"):
            with self.subTest(command=command):
                names, err = self.plan(command, True)
                self.assertEqual(names, ["All checks"])
                self.assertIn("warning", err)


class GateRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / ".cornerstone").mkdir()
        self.set_checks("exit 0")
        with contextlib.redirect_stderr(io.StringIO()):
            render.render(self.root, FRAMEWORK)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "a@example.com")
        self.git("config", "user.name", "a")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base", "--trailer", "Role: generator")
        self.git("update-ref", "refs/remotes/origin/dev", "HEAD")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def set_checks(self, command: str) -> None:
        text = CONFIG.replace("make check", command.replace('"', '\\"'))
        text = text.replace("all_checks: " + command.replace('"', '\\"'),
                            'all_checks: "' + command.replace('"', '\\"') + '"')
        (self.root / ".cornerstone" / "config.yaml").write_text(
            text + "delivery: local\n", encoding="utf-8")

    def test_failing_first_command_does_not_stop_the_next(self) -> None:
        self.set_checks("echo one-ran && exit 1 && echo three-ran")
        steps, text = gate.run(self.root, split_checks=True)
        checks = [step for step in steps if step.name.startswith("All checks")]
        self.assertEqual([step.name for step in checks],
                         ["All checks: `echo one-ran`", "All checks: `exit 1`",
                          "All checks: `echo three-ran`"])
        self.assertEqual([step.passed for step in checks], [True, False, True])
        self.assertIn("| All checks: `exit 1` | FAIL |", text)
        self.assertIn("| All checks: `echo three-ran` | pass |", text)

    def test_default_stops_at_the_first_failure(self) -> None:
        self.set_checks("exit 1 && touch ran-after")
        steps, text = gate.run(self.root)
        self.assertEqual([step.name for step in steps][-1], "All checks")
        self.assertFalse(steps[-1].passed)
        self.assertFalse((self.root / "ran-after").exists())

    def run_cli(self, *extra: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["gate", "--root", str(self.root), *extra])
        return code, out.getvalue()

    def test_cli_option_exits_1_if_one_step_fails(self) -> None:
        self.set_checks("exit 1 && touch ran-after")
        code, out = self.run_cli("--split-checks")
        self.assertEqual(code, 1)
        self.assertIn("| All checks: `exit 1` | FAIL |", out)
        self.assertTrue((self.root / "ran-after").exists())

    def test_cli_option_exits_0_if_all_pass(self) -> None:
        self.set_checks("true && true")
        code, out = self.run_cli("--split-checks")
        self.assertEqual(code, 0, out)
        self.assertIn("| All checks: `true` | pass |", out)


if __name__ == "__main__":
    unittest.main()
