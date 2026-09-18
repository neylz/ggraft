import unittest

from ggraft import glsl

from tests.fixtures import CONDITIONAL_INCLUDE, FUNCTIONS, NESTED


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


class TestFunctions(unittest.TestCase):
    def test_a_definition_is_found_with_its_body(self):
        found = glsl.find_functions(FUNCTIONS, "helper")
        self.assertEqual(len(found), 1)
        self.assertIn("return x * 2.0;", FUNCTIONS[found[0].body])
        self.assertEqual(FUNCTIONS[found[0].open_brace], "{")
        self.assertEqual(FUNCTIONS[found[0].close_brace], "}")

    def test_a_comment_a_prototype_and_a_call_are_not_definitions(self):
        found = glsl.find_functions(FUNCTIONS, "main")
        self.assertEqual(len(found), 1)
        self.assertIn("gl_Position", FUNCTIONS[found[0].body])

    def test_the_body_closes_on_the_matching_brace_not_the_first(self):
        helper = glsl.find_functions(FUNCTIONS, "helper")[0]
        body = FUNCTIONS[helper.body]
        self.assertIn("if (x < 0.0) {", body)   # the nested block is inside
        self.assertEqual(body.count("{"), body.count("}"))

    def test_overloads_come_back_in_source_order(self):
        source = "vec3 f(vec3 v) { return v; }\nfloat f(float x) { return x; }\n"
        found = glsl.find_functions(source, "f")
        self.assertEqual([source[f.start:f.start + 4] for f in found], ["f(ve", "f(fl"])

    def test_a_body_that_never_closes_reports_no_closing_brace(self):
        self.assertEqual(glsl.find_functions("void main() {\n  x();\n", "main")[0].close_brace, -1)

    def test_a_missing_function_is_simply_absent(self):
        self.assertEqual(glsl.find_functions(FUNCTIONS, "nowhere"), [])

    def test_returns_include_nested_ones_and_stop_at_the_body(self):
        helper = glsl.find_functions(FUNCTIONS, "helper")[0]
        found = glsl.return_statements(FUNCTIONS, helper)
        self.assertEqual(len(found), 2)
        self.assertTrue(all(helper.open_brace < at < helper.close_brace for at in found))

    def test_a_commented_return_is_not_a_return(self):
        source = "void f() {\n    // return early;\n    x();\n}\n"
        function = glsl.find_functions(source, "f")[0]
        self.assertEqual(glsl.return_statements(source, function), [])

    def test_mask_comments_blanks_the_text_but_keeps_length_and_lines(self):
        source = "a /* one\ntwo */ b // three\nc\n"
        masked = glsl.mask_comments(source)
        self.assertEqual(len(masked), len(source))
        self.assertEqual(masked.count("\n"), source.count("\n"))
        self.assertNotIn("one", masked)
        self.assertNotIn("three", masked)
        self.assertIn("a ", masked)
        self.assertIn("c", masked)

    def test_body_indent_falls_back_one_level_for_an_empty_body(self):
        source = "  void f() {\n  }\n"
        self.assertEqual(glsl.body_indent(source, glsl.find_functions(source, "f")[0]), "      ")


CALLS = """void main() {
    vec3 pos = helper(x) + offset;
    if (helper(pos.y) > 0.0) {
        helper(1.0);
    }
    for (int i = 0; helper(i); i++) { }
}
"""


class TestCalls(unittest.TestCase):
    def setUp(self):
        self.main = glsl.find_functions(CALLS, "main")[0]
        self.body_start = self.main.open_brace + 1

    def spans(self):
        return [glsl.statement_span(CALLS, at, self.body_start)
                for at in glsl.find_calls(CALLS, self.main, "helper")]

    def test_every_call_in_the_body_is_found(self):
        self.assertEqual(len(glsl.find_calls(CALLS, self.main, "helper")), 4)

    def test_a_name_that_merely_ends_with_the_call_is_not_a_call(self):
        source = "void f() {\n    myhelper(1.0);\n}\n"
        function = glsl.find_functions(source, "f")[0]
        self.assertEqual(glsl.find_calls(source, function, "helper"), [])

    def test_a_commented_call_is_not_a_call(self):
        source = "void f() {\n    // helper(1.0);\n}\n"
        function = glsl.find_functions(source, "f")[0]
        self.assertEqual(glsl.find_calls(source, function, "helper"), [])

    def test_a_simple_statement_spans_up_to_its_semicolon(self):
        start, end = self.spans()[0]
        self.assertEqual(CALLS[start:end], "vec3 pos = helper(x) + offset;")

    def test_a_call_in_an_if_header_has_no_statement_end(self):
        start, end = self.spans()[1]
        self.assertEqual(end, -1)
        self.assertTrue(CALLS[start:].startswith("if (helper"))

    def test_a_semicolon_inside_a_for_header_does_not_end_a_statement(self):
        # the give-away case: scanning backwards alone would stop at "int i = 0;"
        start, end = self.spans()[3]
        self.assertEqual(end, -1)
        self.assertTrue(CALLS[start:].startswith("for (int i = 0;"))

    def test_a_closing_paren_before_the_call_does_not_end_the_statement(self):
        source = "void main() {\n    vec3 p = clamp(a, b) + helper(x);\n}\n"
        function = glsl.find_functions(source, "main")[0]
        at = glsl.find_calls(source, function, "helper")[0]
        start, end = glsl.statement_span(source, at, function.open_brace + 1)
        self.assertEqual(source[start:end], "vec3 p = clamp(a, b) + helper(x);")

    def test_a_statement_that_never_ends_reports_no_end(self):
        fragment = "p = helper(x)"
        self.assertEqual(glsl.statement_span(fragment, 4, 0), (0, -1))
