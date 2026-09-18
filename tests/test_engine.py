import shutil
import tempfile
import unittest
from pathlib import Path

from ggraft import config as config_module
from ggraft.errors import TargetError
from ggraft.patching import engine, patch as patch_module

from tests.fixtures import CONFIG, REPLACE_PATCH

IDLE_PATCH = """targets = ["core/*.vsh"]
exclude = ["core/*.vsh"]
[[injection]]
op = "replace"
at = "x"
with = "y"
"""


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "base" / "core").mkdir(parents=True)
        (self.root / "patches").mkdir()
        (self.root / "ggraft.toml").write_text(CONFIG, encoding="utf-8")
        for name in ("a", "b"):
            body = "#version 330\nvoid main() { gl_Position = %s; }\n" % name.upper()
            (self.root / "base" / "core" / (name + ".vsh")).write_text(body, encoding="utf-8")

    def write_patch(self, name, body):
        (self.root / "patches" / (name + ".toml")).write_text(body, encoding="utf-8")

    def build(self):
        cfg = config_module.load(self.root / "ggraft.toml")
        patches = patch_module.load_all(cfg.patch_dir)
        return cfg, engine.run(cfg, engine.plan(cfg, patches))

    def test_prune_removes_a_target_dropped_from_a_patch(self):
        self.write_patch("p", REPLACE_PATCH.format(targets='"core/a.vsh", "core/b.vsh"'))
        cfg, _ = self.build()
        self.assertTrue((cfg.output_dir / "core" / "b.vsh").is_file())

        self.write_patch("p", REPLACE_PATCH.format(targets='"core/a.vsh"'))
        cfg, report = self.build()
        self.assertEqual(report.pruned, ["core/b.vsh"])
        self.assertFalse((cfg.output_dir / "core" / "b.vsh").exists())
        self.assertTrue((cfg.output_dir / "core" / "a.vsh").is_file())

    def test_prune_leaves_untracked_files_alone(self):
        self.write_patch("p", REPLACE_PATCH.format(targets='"core/a.vsh"'))
        cfg, _ = self.build()
        stranger = cfg.output_dir / "core" / "hand_written.vsh"
        stranger.write_text("mine", encoding="utf-8")
        self.build()
        self.assertTrue(stranger.is_file())

    def test_patch_that_applies_to_nothing_is_an_error(self):
        self.write_patch("idle", IDLE_PATCH)
        with self.assertRaises(TargetError) as caught:
            self.build()
        self.assertIn("applied to nothing", str(caught.exception))

    def test_target_matching_no_base_file_is_an_error(self):
        self.write_patch("p", REPLACE_PATCH.format(targets='"core/missing.vsh"'))
        with self.assertRaises(TargetError):
            self.build()

    def test_patched_output_is_stable_across_runs(self):
        self.write_patch("p", REPLACE_PATCH.format(targets='"core/a.vsh"'))
        _, first = self.build()
        _, second = self.build()
        self.assertTrue(first.results[0].changed)
        self.assertFalse(second.results[0].changed)

    def test_a_missing_base_says_to_pull_first(self):
        shutil.rmtree(self.root / "base")
        self.write_patch("p", REPLACE_PATCH.format(targets='"core/a.vsh"'))
        with self.assertRaises(TargetError) as caught:
            self.build()
        self.assertIn("run 'ggraft pull' first", str(caught.exception))

    def test_a_filtered_plan_skips_untargeted_files_and_the_idle_check(self):
        self.write_patch("p", REPLACE_PATCH.format(targets='"core/a.vsh"'))
        cfg = config_module.load(self.root / "ggraft.toml")
        patches = patch_module.load_all(cfg.patch_dir)
        self.assertEqual([i.target for i in engine.plan(cfg, patches, only=["core/b.*"])], [])

    def test_prune_removes_a_subdirectory_it_emptied(self):
        (self.root / "base" / "core" / "deep").mkdir()
        (self.root / "base" / "core" / "deep" / "d.vsh").write_text(
            "#version 330\nvoid main() { gl_Position = D; }\n", encoding="utf-8")

        self.write_patch("p", REPLACE_PATCH.format(targets='"core/a.vsh", "core/deep/d.vsh"'))
        cfg, _ = self.build()
        self.assertTrue((cfg.output_dir / "core" / "deep").is_dir())

        self.write_patch("p", REPLACE_PATCH.format(targets='"core/a.vsh"'))
        cfg, report = self.build()
        self.assertEqual(report.pruned, ["core/deep/d.vsh"])
        self.assertFalse((cfg.output_dir / "core" / "deep").exists())
        # only the directory it emptied, never the output root
        self.assertTrue((cfg.output_dir / "core").is_dir())

    def test_prune_at_the_output_root_leaves_the_output_directory(self):
        (self.root / "base" / "top.vsh").write_text(
            "#version 330\nvoid main() { gl_Position = T; }\n", encoding="utf-8")

        self.write_patch("p", REPLACE_PATCH.format(targets='"core/a.vsh", "top.vsh"'))
        cfg, _ = self.build()
        self.assertTrue((cfg.output_dir / "top.vsh").is_file())

        self.write_patch("p", REPLACE_PATCH.format(targets='"core/a.vsh"'))
        cfg, report = self.build()
        self.assertEqual(report.pruned, ["top.vsh"])
        self.assertFalse((cfg.output_dir / "top.vsh").exists())
        self.assertTrue(cfg.output_dir.is_dir())

    def test_a_corrupt_manifest_does_not_block_a_build(self):
        self.write_patch("p", REPLACE_PATCH.format(targets='"core/a.vsh"'))
        cfg, _ = self.build()
        cfg.manifest.write_text("{ not json", encoding="utf-8")
        _, report = self.build()
        self.assertEqual(report.pruned, [])
        self.assertTrue((cfg.output_dir / "core" / "a.vsh").is_file())


class TestHeader(unittest.TestCase):
    """output.header stamps provenance above the patched source."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "base" / "core").mkdir(parents=True)
        (self.root / "patches").mkdir()
        (self.root / "base" / "core" / "a.vsh").write_text(
            "#version 330\nvoid main() { gl_Position = A; }\n", encoding="utf-8")
        (self.root / "patches" / "p.toml").write_text(
            REPLACE_PATCH.format(targets='"core/a.vsh"'), encoding="utf-8")

    def build(self, version):
        config = CONFIG.replace("header = false", "header = true")
        if version:
            config = config.replace("[base]", f'[base]\nversion = "{version}"')
        (self.root / "ggraft.toml").write_text(config, encoding="utf-8")
        cfg = config_module.load(self.root / "ggraft.toml")
        patches = patch_module.load_all(cfg.patch_dir)
        engine.run(cfg, engine.plan(cfg, patches))
        return (cfg.output_dir / "core" / "a.vsh").read_text(encoding="utf-8")

    def test_header_names_the_version_and_the_patches(self):
        out = self.build("26.3")
        self.assertIn("// Generated by ggraft from Minecraft 26.3", out)
        self.assertIn("// Patches: p", out)
        self.assertIn("iso(A)", out)

    def test_version_directive_stays_the_first_statement(self):
        # #version must lead the file, so the header cannot go above it
        self.assertEqual(self.build("26.3").splitlines()[0], "#version 330")

    def test_an_unconfigured_version_is_stamped_as_unknown(self):
        self.assertIn("Minecraft unknown", self.build(None))
