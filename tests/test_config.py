import tempfile
import unittest
from pathlib import Path

from ggraft import config as config_module
from ggraft import glsl
from ggraft.errors import ConfigError

MINIMAL = '[output]\ndir = "out"\n'


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def write(self, body):
        path = self.root / "ggraft.toml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_the_directive_is_resolved_when_the_config_is_read(self):
        cfg = config_module.load(self.write('[base]\nversion = "26.2"\n' + MINIMAL))
        self.assertEqual(cfg.directive, glsl.MOJ_IMPORT)

    def test_everything_but_output_dir_has_a_default(self):
        cfg = config_module.load(self.write(MINIMAL))
        self.assertIsNone(cfg.version)
        self.assertEqual(cfg.source, "assets/minecraft/shaders")
        self.assertEqual(cfg.repo, "misode/mcmeta")
        self.assertEqual(cfg.base_dir, self.root / ".ggraft" / "base")
        self.assertEqual(cfg.patch_dir, self.root / "patches")
        self.assertTrue(cfg.header)

    def test_state_files_sit_beside_each_other_outside_the_base(self):
        cfg = config_module.load(self.write(MINIMAL))
        self.assertEqual(cfg.manifest, self.root / ".ggraft" / "manifest.json")
        self.assertEqual(cfg.base_state, self.root / ".ggraft" / "base.json")
        # a pull wipes base_dir and a build globs it for targets
        self.assertNotIn(cfg.base_dir, cfg.base_state.parents)

    def test_output_dir_is_required(self):
        with self.assertRaises(ConfigError) as caught:
            config_module.load(self.write('[base]\nversion = "26.3"\n'))
        self.assertIn("output.dir is required", str(caught.exception))

    def test_invalid_toml_names_the_file(self):
        with self.assertRaises(ConfigError) as caught:
            config_module.load(self.write("[base\n"))
        self.assertIn("invalid TOML", str(caught.exception))

    def test_sections_must_be_tables(self):
        with self.assertRaises(ConfigError) as caught:
            config_module.load(self.write('base = "nope"\n' + MINIMAL))
        self.assertIn("must be tables", str(caught.exception))

    def test_unreadable_config_is_reported_not_raised_raw(self):
        path = self.root / "ggraft.toml"
        path.mkdir()
        with self.assertRaises(ConfigError) as caught:
            config_module.load(path)
        self.assertIn("cannot read", str(caught.exception))

    def test_source_keeps_no_leading_or_trailing_slash(self):
        cfg = config_module.load(self.write('[base]\nsource = "/assets/x/"\n' + MINIMAL))
        self.assertEqual(cfg.source, "assets/x")

    def test_require_version_returns_what_is_configured(self):
        cfg = config_module.load(self.write('[base]\nversion = "26.3"\n' + MINIMAL))
        self.assertEqual(cfg.require_version(), "26.3")

    def test_require_version_says_where_to_set_it(self):
        cfg = config_module.load(self.write(MINIMAL))
        with self.assertRaises(ConfigError) as caught:
            cfg.require_version()
        self.assertIn("base.version", str(caught.exception))

    def test_find_walks_up_from_a_subdirectory(self):
        self.write(MINIMAL)
        deep = self.root / "a" / "b"
        deep.mkdir(parents=True)
        self.assertEqual(config_module.find(deep), self.root / "ggraft.toml")

    def test_find_without_a_config_names_the_directory(self):
        with self.assertRaises(ConfigError) as caught:
            config_module.find(self.root)
        self.assertIn(str(self.root), str(caught.exception))


class TestImportDirective(unittest.TestCase):
    """Mojang renamed #moj_import to #include in 26.3."""

    def resolve(self, version):
        return config_module.resolve_directive(version)

    def test_26_3_and_later_use_include(self):
        for version in ("26.3", "26.4", "27.1", "30.0"):
            with self.subTest(version=version):
                self.assertEqual(self.resolve(version), glsl.INCLUDE)

    def test_everything_earlier_uses_moj_import(self):
        for version in ("26.2", "26.1", "25.4", "1.21.11", "1.21.4", "1.19"):
            with self.subTest(version=version):
                self.assertEqual(self.resolve(version), glsl.MOJ_IMPORT)

    def test_a_pre_release_follows_its_release(self):
        self.assertEqual(self.resolve("1.21.4-pre1"), glsl.MOJ_IMPORT)
        self.assertEqual(self.resolve("26.3-rc1"), glsl.INCLUDE)

    def test_a_version_with_no_number_assumes_the_current_spelling(self):
        # snapshot versioning is not supported; neither is having no version
        self.assertEqual(self.resolve("25w14a"), glsl.INCLUDE)
        self.assertEqual(self.resolve(None), glsl.INCLUDE)
