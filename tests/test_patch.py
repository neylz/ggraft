import tempfile
import unittest
from pathlib import Path

from ggraft.errors import PatchError
from ggraft.patching import patch as patch_module

REPLACE = '[[injection]]\nop = "replace"\nmatch = "x"\nwith = "y"\n'


class TestPatchFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def load(self, body, name="p.toml"):
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return patch_module.load(path)

    def test_targets_may_be_a_bare_string(self):
        self.assertEqual(self.load('targets = "core/a.vsh"\n' + REPLACE).targets, ["core/a.vsh"])

    def test_exclude_may_be_a_bare_string_and_wins_over_targets(self):
        patch = self.load('targets = "core/*.vsh"\nexclude = "core/b.vsh"\n' + REPLACE)
        self.assertEqual(patch.exclude, ["core/b.vsh"])
        self.assertTrue(patch.applies_to("core/a.vsh"))
        self.assertFalse(patch.applies_to("core/b.vsh"))

    def test_name_defaults_to_the_file_stem(self):
        self.assertEqual(self.load('targets = "x"\n' + REPLACE).name, "p")

    def test_name_must_be_a_string(self):
        with self.assertRaises(PatchError):
            self.load('name = 3\ntargets = "x"\n' + REPLACE)

    def test_targets_of_the_wrong_type_are_refused(self):
        with self.assertRaises(PatchError) as caught:
            self.load("targets = [1, 2]\n" + REPLACE)
        self.assertIn("must be a string or a list of strings", str(caught.exception))

    def test_a_patch_without_targets_is_refused(self):
        with self.assertRaises(PatchError) as caught:
            self.load(REPLACE)
        self.assertIn("no 'targets'", str(caught.exception))

    def test_a_patch_without_injections_is_refused(self):
        with self.assertRaises(PatchError) as caught:
            self.load('targets = "x"\n')
        self.assertIn("no [[injection]] blocks", str(caught.exception))

    def test_an_injection_that_is_not_a_table_is_refused(self):
        with self.assertRaises(PatchError) as caught:
            self.load('targets = "x"\ninjection = ["nope"]\n')
        self.assertIn("injection 0 is not a table", str(caught.exception))

    def test_an_injection_without_an_op_is_refused(self):
        with self.assertRaises(PatchError) as caught:
            self.load('targets = "x"\n[[injection]]\nmatch = "a"\n')
        self.assertIn("needs an 'op'", str(caught.exception))

    def test_a_bad_injection_is_reported_with_its_index(self):
        with self.assertRaises(PatchError) as caught:
            self.load('targets = "x"\n' + REPLACE + '[[injection]]\nop = "frobnicate"\n')
        self.assertIn("p[1]", str(caught.exception))

    def test_invalid_toml_names_the_file(self):
        with self.assertRaises(PatchError) as caught:
            self.load("targets = [\n")
        self.assertIn("invalid TOML", str(caught.exception))

    def test_unreadable_patch_is_reported_not_raised_raw(self):
        (self.root / "dir.toml").mkdir()
        with self.assertRaises(PatchError) as caught:
            patch_module.load(self.root / "dir.toml")
        self.assertIn("cannot read", str(caught.exception))


class TestPatchDirectory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_missing_directory_is_reported(self):
        with self.assertRaises(PatchError) as caught:
            patch_module.load_all(self.root / "nowhere")
        self.assertIn("patch directory not found", str(caught.exception))

    def test_a_directory_without_patches_is_reported(self):
        with self.assertRaises(PatchError) as caught:
            patch_module.load_all(self.root)
        self.assertIn("no patches (*.toml)", str(caught.exception))

    def test_patches_stack_in_filename_order_across_subdirectories(self):
        (self.root / "nested").mkdir()
        for name in ("20-b.toml", "10-a.toml", "nested/30-c.toml"):
            (self.root / name).write_text('targets = "x"\n' + REPLACE, encoding="utf-8")
        self.assertEqual([p.name for p in patch_module.load_all(self.root)],
                         ["10-a", "20-b", "30-c"])
