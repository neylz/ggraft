"""Anchor resolution: what an injection point matches, and how it fails."""

import unittest

from ggraft.errors import AmbiguousInjection, PatchError, UnresolvedInjection
from ggraft.patching.anchor import Anchor, substitute

from tests.fixtures import NESTED

FUNCTION_BODY = """#version 330
void main() {
    gl_Position = A;
}
"""

DUPLICATED = "dup\ndup\n"


class TestAnchor(unittest.TestCase):
    def test_placeholder_captures_and_substitutes(self):
        match = Anchor("vec4({expr}, 1.0)").resolve("gl_Position = vec4(pos, 1.0);", "t")[0]
        self.assertEqual(match.group("expr"), "pos")

    def test_literal_anchor_does_not_treat_text_as_regex(self):
        self.assertEqual(len(Anchor("a * b(c)").resolve("x = a * b(c);", "t")), 1)

    def test_placeholder_stops_at_a_newline_by_default(self):
        with self.assertRaises(UnresolvedInjection):
            Anchor("main() {{body}}").resolve(FUNCTION_BODY, "t")

    def test_multiline_lets_a_placeholder_span_lines(self):
        match = Anchor("main() {{body}}", multiline=True).resolve(FUNCTION_BODY, "t")[0]
        self.assertEqual(match.group("body").strip(), "gl_Position = A;")

    def test_multiline_applies_to_regex_anchors_too(self):
        pattern = r"main\(\) \{(?P<body>.+)\}"
        with self.assertRaises(UnresolvedInjection):
            Anchor(pattern, regex=True).resolve(FUNCTION_BODY, "t")
        self.assertEqual(
            len(Anchor(pattern, regex=True, multiline=True).resolve(FUNCTION_BODY, "t")), 1
        )

    def test_literal_text_spans_lines_without_multiline(self):
        anchor = Anchor("main() {\n    gl_Position = {expr};")
        self.assertEqual(anchor.resolve(FUNCTION_BODY, "t")[0].group("expr"), "A")

    def test_unresolved_anchor_raises(self):
        with self.assertRaises(UnresolvedInjection):
            Anchor("nothing here").resolve(NESTED, "patch[0] -> core/terrain.vsh")

    def test_ambiguous_anchor_raises_and_names_the_lines(self):
        with self.assertRaises(AmbiguousInjection) as caught:
            Anchor("dup").resolve(DUPLICATED, "patch[0] -> x")
        self.assertIn("matched 2 times", str(caught.exception))

    def test_occurrence_disambiguates(self):
        matches = Anchor("dup", occurrence=2).resolve(DUPLICATED, "t")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].start(), 4)

    def test_occurrence_beyond_the_match_count_is_unresolved(self):
        with self.assertRaises(UnresolvedInjection):
            Anchor("dup", occurrence=9).resolve(DUPLICATED, "t")

    def test_every_returns_all_matches(self):
        self.assertEqual(len(Anchor("dup", every=True).resolve(DUPLICATED, "t")), 2)

    def test_substitute_leaves_glsl_braces_alone(self):
        self.assertEqual(substitute("void main() { {x} }", {"x": "ok"}), "void main() { ok }")
        self.assertEqual(substitute("{unknown}", {}), "{unknown}")

    def test_occurrence_must_be_a_positive_integer(self):
        for bad in (0, -1, "2", 1.5):
            with self.subTest(occurrence=bad):
                with self.assertRaises(PatchError) as caught:
                    Anchor.from_spec({"match": "x", "occurrence": bad}, "t")
                self.assertIn("positive integer", str(caught.exception))

    def test_an_empty_anchor_is_refused(self):
        with self.assertRaises(PatchError):
            Anchor.from_spec({"match": ""}, "t")

    def test_the_anchor_key_is_match(self):
        self.assertEqual(Anchor.from_spec({"match": "x"}, "t").pattern, "x")

    def test_a_placeholder_that_is_not_a_usable_name_is_reported(self):
        for pattern in ("vec4({1})", "{a} and {a}"):
            with self.subTest(pattern=pattern):
                with self.assertRaises(PatchError) as caught:
                    Anchor.from_spec({"match": pattern}, "t")
                self.assertIn("cannot be compiled", str(caught.exception))

    def test_an_invalid_regex_is_reported_not_raised_raw(self):
        with self.assertRaises(PatchError) as caught:
            Anchor.from_spec({"match": "f(", "regex": True}, "t")
        self.assertIn("cannot be compiled", str(caught.exception))

    def test_a_malformed_anchor_fails_at_load_not_mid_build(self):
        # the error names the patch and injection, which only from_spec knows
        with self.assertRaises(PatchError) as caught:
            Anchor.from_spec({"match": "vec4({1})"}, "iso[0]")
        self.assertIn("iso[0]", str(caught.exception))
