import unittest

from ggraft import glsl
from ggraft.errors import PatchError
from ggraft.patching import operations
from ggraft.patching.anchor import Anchor

from tests.fixtures import CONDITIONAL_INCLUDE, NESTED

TWO_LINES = "vec4 a = P * V;\nvec4 b = P * V;\n"

TWO_LINES_PATCHED = "vec4 a = iso(P, V);\nvec4 b = iso(P, V);\n"


class TestOperations(unittest.TestCase):
    def build(self, spec):
        cls = operations.get(spec["op"], "t")
        op = cls.from_spec(spec, "t")
        anchor = Anchor.from_spec(spec, "t") if cls.needs_anchor else None
        return op, anchor

    def test_replace_uses_captures(self):
        op, anchor = self.build({"op": "replace", "at": "f({arg})", "with": "g({arg}, 1)"})
        self.assertEqual(op.apply("y = f(pos);", anchor, "t"), "y = g(pos, 1);")

    def test_insert_before_and_after(self):
        op, anchor = self.build({"op": "insert", "at": "B", "text": "A", "where": "before"})
        self.assertEqual(op.apply("xBx", anchor, "t"), "xABx")
        op, anchor = self.build({"op": "insert", "at": "B", "text": "C"})
        self.assertEqual(op.apply("xBx", anchor, "t"), "xBCx")

    def test_wrap_keeps_the_matched_text(self):
        op, anchor = self.build({"op": "wrap", "at": "v", "prefix": "f(", "suffix": ")"})
        self.assertEqual(op.apply("x = v;", anchor, "t"), "x = f(v);")

    def test_declare_inserts_include_at_top_level(self):
        op, anchor = self.build({"op": "declare", "include": "ns:x.glsl"})
        lines = op.apply(NESTED, anchor, "t").splitlines()
        index = lines.index("#include <ns:x.glsl>")
        self.assertEqual(lines[index - 1], "#include <minecraft:terrainglobals.glsl>")
        self.assertEqual(lines[index + 1], "#ifndef MULTIDRAW_TERRAIN")

    def test_declare_is_idempotent(self):
        op, anchor = self.build({"op": "declare", "include": "ns:x.glsl"})
        once = op.apply(NESTED, anchor, "t")
        self.assertEqual(op.apply(once, anchor, "t"), once)

    def test_declare_still_adds_when_existing_include_is_conditional(self):
        op, anchor = self.build({"op": "declare", "include": "ns:x.glsl"})
        out = op.apply(CONDITIONAL_INCLUDE, anchor, "t")
        self.assertTrue(glsl.declares(out, "#include <ns:x.glsl>"))

    def test_every_replace_applies_to_all_matches(self):
        op, anchor = self.build({
            "op": "replace", "at": "vec4 {v} = P * V", "with": "vec4 {v} = iso(P, V)",
            "every": True,
        })
        self.assertEqual(op.apply(TWO_LINES, anchor, "t"), TWO_LINES_PATCHED)

    def test_unknown_operation_names_the_known_ones(self):
        with self.assertRaises(PatchError) as caught:
            operations.get("frobnicate", "t")
        self.assertIn("declare", str(caught.exception))

    def test_missing_anchor_is_rejected(self):
        with self.assertRaises(PatchError):
            Anchor.from_spec({"op": "replace", "with": "x"}, "t")

    def test_every_and_occurrence_are_mutually_exclusive(self):
        with self.assertRaises(PatchError):
            Anchor.from_spec({"at": "x", "every": True, "occurrence": 2}, "t")

    def test_declare_takes_raw_text_too(self):
        op, anchor = self.build({"op": "declare", "text": "uniform float iso_scale;"})
        out = op.apply(NESTED, anchor, "t")
        self.assertIn("uniform float iso_scale;", out)
        self.assertEqual(op.apply(out, anchor, "t"), out)

    def test_declare_refuses_both_include_and_text(self):
        with self.assertRaises(PatchError) as caught:
            self.build({"op": "declare", "include": "ns:x.glsl", "text": "x"})
        self.assertIn("not both", str(caught.exception))

    def test_declare_needs_one_of_them(self):
        with self.assertRaises(PatchError):
            self.build({"op": "declare"})

    def test_insert_refuses_a_where_that_is_neither_side(self):
        with self.assertRaises(PatchError) as caught:
            self.build({"op": "insert", "at": "B", "text": "A", "where": "above"})
        self.assertIn("'before' or 'after'", str(caught.exception))

    def test_wrap_needs_a_prefix_or_a_suffix(self):
        with self.assertRaises(PatchError) as caught:
            self.build({"op": "wrap", "at": "v"})
        self.assertIn("at least one", str(caught.exception))

    def test_wrap_refuses_a_non_string_affix(self):
        with self.assertRaises(PatchError):
            self.build({"op": "wrap", "at": "v", "prefix": 3})

    def test_replace_without_with_is_refused(self):
        with self.assertRaises(PatchError) as caught:
            self.build({"op": "replace", "at": "v"})
        self.assertIn("needs a 'with' string", str(caught.exception))

    def test_names_lists_every_registered_operation(self):
        self.assertEqual(operations.names(), ["declare", "insert", "replace", "wrap"])
