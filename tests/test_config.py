import tempfile
import unittest
from pathlib import Path

from ggraft import config as config_module
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
