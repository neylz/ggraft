import unittest

from ggraft import glsl

from tests.fixtures import CONDITIONAL_INCLUDE, NESTED


class TestGlsl(unittest.TestCase):
    def test_declaration_line_skips_conditional_includes(self):
        index = glsl.declaration_line(NESTED)
        self.assertEqual(NESTED.splitlines()[index], "#include <minecraft:terrainglobals.glsl>")

    def test_declaration_line_falls_back_to_extension_then_version(self):
        self.assertEqual(glsl.declaration_line("#version 330\n#extension X : require\n"), 1)
        self.assertEqual(glsl.declaration_line("#version 330\nvoid main() {}\n"), 0)

    def test_header_line_is_the_version_line(self):
        self.assertEqual(glsl.header_line(NESTED), 0)

    def test_insert_after_places_text_on_its_own_line(self):
        self.assertEqual(glsl.insert_after("a\nb\nc", 0, "X"), "a\nX\nb\nc")

    def test_insert_after_preserves_crlf(self):
        self.assertEqual(glsl.insert_after("a\r\nb", 0, "X"), "a\r\nX\r\nb")

    def test_walk_reports_conditional_depth(self):
        depths = {line.strip(): d for _, line, d in glsl.walk(NESTED.splitlines())} # pyright: ignore[reportArgumentType]
        self.assertEqual(depths["#include <minecraft:chunksection.glsl>"], 1)
        self.assertEqual(depths["#include <minecraft:fog.glsl>"], 0)

    def test_declares_ignores_conditional_occurrences(self):
        self.assertFalse(glsl.declares(CONDITIONAL_INCLUDE, "#include <ns:x.glsl>"))
        self.assertTrue(glsl.declares(NESTED, "#include <minecraft:fog.glsl>"))

    def test_a_shader_with_no_directives_has_no_declaration_line(self):
        # -1 means "insert at the top": there is nothing to sit after
        self.assertEqual(glsl.declaration_line("void main() {}\n"), -1)
        self.assertEqual(glsl.header_line("void main() {}\n"), -1)
        self.assertEqual(glsl.insert_after("void main() {}", -1, "X"), "X\nvoid main() {}")

    def test_unbalanced_endif_does_not_drive_depth_negative(self):
        depths = [d for _, _, d in glsl.walk(["#endif", "#endif", "void main() {}"])]
        self.assertEqual(depths, [0, 0, 0])
