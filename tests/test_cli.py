import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

import ggraft
from ggraft.cli import cli
from ggraft.cli.main import _is_broken_pipe, main

from tests.fixtures import CONFIG, Offline, REPLACE_PATCH


class TestCli(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    @staticmethod
    def _text(result):
        out = result.output or ""
        try:
            out += result.stderr or ""
        except ValueError:
            pass
        return out

    @staticmethod
    def _project(root: Path, targets: str = '"core/a.vsh"') -> None:
        (root / "base" / "core").mkdir(parents=True)
        (root / "patches").mkdir()
        (root / "ggraft.toml").write_text(CONFIG, encoding="utf-8")
        for name in ("a", "b"):
            (root / "base" / "core" / f"{name}.vsh").write_text(
                "#version 330\nvoid main() { gl_Position = %s; }\n" % name.upper(),
                encoding="utf-8",
            )
        (root / "patches" / "p.toml").write_text(
            REPLACE_PATCH.format(targets=targets), encoding="utf-8"
        )

    def test_help_lists_every_command(self):
        result = self.runner.invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0)
        for name in ("build", "init", "pull", "targets"):
            self.assertIn(name, result.output)

    def test_version_reports_the_package_version(self):
        result = self.runner.invoke(cli, ["--version"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(ggraft.__version__, result.output)

    def test_init_writes_a_config_then_refuses_to_clobber_it(self):
        with self.runner.isolated_filesystem():
            first = self.runner.invoke(cli, ["init", "26.3"])
            self.assertEqual(first.exit_code, 0)
            self.assertTrue(Path("ggraft.toml").is_file())
            self.assertIn('version = "26.3"', Path("ggraft.toml").read_text(encoding="utf-8"))

            second = self.runner.invoke(cli, ["init"])
            self.assertEqual(second.exit_code, 1)
            self.assertIn("already exists", self._text(second))

            forced = self.runner.invoke(cli, ["init", "--force"])
            self.assertEqual(forced.exit_code, 0)

    def test_build_writes_output_and_check_is_then_clean(self):
        with self.runner.isolated_filesystem() as tmp:
            self._project(Path(tmp))
            built = self.runner.invoke(cli, ["build"])
            self.assertEqual(built.exit_code, 0, self._text(built))
            self.assertIn("iso(A)", Path(tmp, "out", "core", "a.vsh").read_text(encoding="utf-8"))

            checked = self.runner.invoke(cli, ["build", "--check"])
            self.assertEqual(checked.exit_code, 0, self._text(checked))

    def test_check_exits_nonzero_when_output_would_change(self):
        with self.runner.isolated_filesystem() as tmp:
            self._project(Path(tmp))
            self.runner.invoke(cli, ["build"])
            Path(tmp, "out", "core", "a.vsh").write_text("drifted", encoding="utf-8")

            checked = self.runner.invoke(cli, ["build", "--check"])
            self.assertEqual(checked.exit_code, 1)
            # --check must not write
            self.assertEqual(Path(tmp, "out", "core", "a.vsh").read_text(encoding="utf-8"), "drifted")

    def test_ggraft_errors_become_exit_1_with_the_message(self):
        with self.runner.isolated_filesystem() as tmp:
            self._project(Path(tmp), targets='"core/missing.vsh"')
            result = self.runner.invoke(cli, ["build"])
            self.assertEqual(result.exit_code, 1)
            self.assertIn("matched nothing", self._text(result))

    def _pull(self, *args):
        with mock.patch("ggraft.cli.commands.pull.McMeta", Offline):
            return self.runner.invoke(cli, ["pull", *args])

    def test_pull_skips_a_base_it_already_holds_then_refetches_on_force(self):
        with self.runner.isolated_filesystem() as tmp:
            Path(tmp, "ggraft.toml").write_text(CONFIG, encoding="utf-8")

            first = self._pull("26.3")
            self.assertEqual(first.exit_code, 0, self._text(first))
            self.assertTrue(Path(tmp, "base", "core", "26_3.vsh").is_file())

            again = self._pull("26.3")
            self.assertIn("already present", again.output)

            stray = Path(tmp, "base", "core", "hand_written.vsh")
            stray.write_text("mine", encoding="utf-8")
            forced = self._pull("26.3", "--force")
            self.assertEqual(forced.exit_code, 0, self._text(forced))
            self.assertFalse(stray.exists())

    def test_pull_of_another_version_replaces_the_base(self):
        with self.runner.isolated_filesystem() as tmp:
            Path(tmp, "ggraft.toml").write_text(CONFIG, encoding="utf-8")
            self._pull("26.3")

            switched = self._pull("26.2")
            self.assertEqual(switched.exit_code, 0, self._text(switched))
            self.assertIn("replacing it", switched.output)
            # no leftovers from 26.3 for a build to pick up as targets
            self.assertFalse(Path(tmp, "base", "core", "26_3.vsh").exists())
            self.assertTrue(Path(tmp, "base", "core", "26_2.vsh").is_file())

    def test_pull_refetches_a_base_of_unrecorded_origin(self):
        with self.runner.isolated_filesystem() as tmp:
            Path(tmp, "ggraft.toml").write_text(CONFIG, encoding="utf-8")
            Path(tmp, "base", "core").mkdir(parents=True)
            Path(tmp, "base", "core", "unknown.vsh").write_text("?", encoding="utf-8")

            result = self._pull("26.3")
            self.assertIn("unrecorded base", result.output)
            self.assertFalse(Path(tmp, "base", "core", "unknown.vsh").exists())
            self.assertTrue(Path(tmp, "base", "core", "26_3.vsh").is_file())

    def test_a_malformed_anchor_is_reported_not_traced(self):
        with self.runner.isolated_filesystem() as tmp:
            self._project(Path(tmp))
            Path(tmp, "patches", "p.toml").write_text(
                'targets = ["core/a.vsh"]\n[[injection]]\n'
                'op = "replace"\nmatch = "vec4({1})"\nwith = "x"\n',
                encoding="utf-8",
            )
            result = self.runner.invoke(cli, ["build"])
            self.assertEqual(result.exit_code, 1)
            self.assertIn("cannot be compiled", self._text(result))
            self.assertNotIn("Traceback", self._text(result))

    def test_missing_config_is_reported_not_traced(self):
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, ["build"])
            self.assertEqual(result.exit_code, 1)
            self.assertIn("ggraft.toml", self._text(result))
            self.assertNotIn("Traceback", self._text(result))

    def test_targets_lists_the_patches_and_what_they_hit(self):
        with self.runner.isolated_filesystem() as tmp:
            self._project(Path(tmp), targets='"core/*.vsh"')
            result = self.runner.invoke(cli, ["targets"])
            self.assertEqual(result.exit_code, 0, self._text(result))
            self.assertIn("1 patch(es)", result.output)
            self.assertIn("core/a.vsh", result.output)
            self.assertIn("core/b.vsh", result.output)

    def test_build_t_writes_only_the_filtered_target(self):
        with self.runner.isolated_filesystem() as tmp:
            self._project(Path(tmp), targets='"core/*.vsh"')
            result = self.runner.invoke(cli, ["build", "-t", "core/a.vsh"])
            self.assertEqual(result.exit_code, 0, self._text(result))
            self.assertTrue(Path(tmp, "out", "core", "a.vsh").is_file())
            self.assertFalse(Path(tmp, "out", "core", "b.vsh").exists())

    def test_build_t_does_not_prune_what_it_could_not_see(self):
        with self.runner.isolated_filesystem() as tmp:
            self._project(Path(tmp), targets='"core/*.vsh"')
            self.runner.invoke(cli, ["build"])
            # a filtered build cannot tell what is stale, so b survives
            result = self.runner.invoke(cli, ["build", "-t", "core/a.vsh"])
            self.assertNotIn("pruned", result.output)
            self.assertTrue(Path(tmp, "out", "core", "b.vsh").is_file())

    def test_a_filter_matching_nothing_fails_the_build(self):
        with self.runner.isolated_filesystem() as tmp:
            self._project(Path(tmp))
            result = self.runner.invoke(cli, ["build", "-t", "core/nothing.*"])
            self.assertEqual(result.exit_code, 1)
            self.assertIn("no targets matched any patch", self._text(result))

    def test_build_reports_what_it_pruned(self):
        with self.runner.isolated_filesystem() as tmp:
            self._project(Path(tmp), targets='"core/*.vsh"')
            self.runner.invoke(cli, ["build"])
            Path(tmp, "patches", "p.toml").write_text(
                REPLACE_PATCH.format(targets='"core/a.vsh"'), encoding="utf-8")
            result = self.runner.invoke(cli, ["build"])
            self.assertIn("removed (no longer targeted)", result.output)
            self.assertIn("1 pruned", result.output)

    def test_pull_without_a_version_anywhere_says_where_to_set_it(self):
        with self.runner.isolated_filesystem() as tmp:
            Path(tmp, "ggraft.toml").write_text(CONFIG, encoding="utf-8")
            result = self._pull()
            self.assertEqual(result.exit_code, 1)
            self.assertIn("base.version", self._text(result))

    def test_a_closed_pipe_is_not_an_error(self):
        self.assertTrue(_is_broken_pipe(BrokenPipeError()))
        self.assertFalse(_is_broken_pipe(OSError("something else")))

    def test_a_closed_pipe_exits_zero_and_other_oserrors_still_raise(self):
        # `ggraft targets | head` must not trip `set -e`; stdout is swapped for
        # a throwaway file so the redirect cannot touch the test runner's own
        with tempfile.TemporaryFile() as sink:
            with mock.patch("ggraft.cli.main.sys.stdout", sink), \
                 mock.patch("ggraft.cli.main.cli", side_effect=BrokenPipeError()):
                with self.assertRaises(SystemExit) as caught:
                    main()
            self.assertEqual(caught.exception.code, 0)

        with mock.patch("ggraft.cli.main.cli", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                main()
