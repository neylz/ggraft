import unittest

from ggraft import glsl
from ggraft.errors import AmbiguousInjection, PatchError, UnresolvedInjection
from ggraft.patching import operations
from ggraft.patching.anchor import Anchor

from tests.fixtures import CONDITIONAL_INCLUDE, FUNCTIONS, NESTED

TWO_LINES = "vec4 a = P * V;\nvec4 b = P * V;\n"

TWO_LINES_PATCHED = "vec4 a = iso(P, V);\nvec4 b = iso(P, V);\n"


def build_operation(spec):
    cls = operations.get(spec["op"], "t")
    op = cls.from_spec(spec, "t")
    anchor = Anchor.from_spec(spec, "t") if cls.needs_anchor else None
    return op, anchor


class TestOperations(unittest.TestCase):
    def build(self, spec):
        return build_operation(spec)

    def test_replace_uses_captures(self):
        op, anchor = self.build({"op": "replace", "match": "f({arg})", "with": "g({arg}, 1)"})
        self.assertEqual(op.apply("y = f(pos);", anchor, "t"), "y = g(pos, 1);")

    def test_insert_before_and_after(self):
        op, anchor = self.build({"op": "insert", "match": "B", "text": "A", "where": "before"})
        self.assertEqual(op.apply("xBx", anchor, "t"), "xABx")
        op, anchor = self.build({"op": "insert", "match": "B", "text": "C"})
        self.assertEqual(op.apply("xBx", anchor, "t"), "xBCx")

    def test_wrap_keeps_the_matched_text(self):
        op, anchor = self.build({"op": "wrap", "match": "v", "prefix": "f(", "suffix": ")"})
        self.assertEqual(op.apply("x = v;", anchor, "t"), "x = f(v);")

    def test_declare_spells_the_include_with_the_current_directive(self):
        self.addCleanup(glsl.use, glsl.current())
        op, anchor = self.build({"op": "declare", "include": "ns:x.glsl"})
        # resolved on apply, so a patch loaded before the config still follows it
        glsl.use(glsl.MOJ_IMPORT)
        self.assertIn("#moj_import <ns:x.glsl>", op.apply(NESTED, anchor, "t"))
        glsl.use(glsl.INCLUDE)
        self.assertIn("#include <ns:x.glsl>", op.apply(NESTED, anchor, "t"))

    def test_declare_is_idempotent_against_either_spelling(self):
        self.addCleanup(glsl.use, glsl.current())
        glsl.use(glsl.MOJ_IMPORT)
        op, anchor = self.build({"op": "declare", "include": "minecraft:fog.glsl"})
        source = "#version 330\n#moj_import <minecraft:fog.glsl>\nvoid main() {}\n"
        self.assertEqual(op.apply(source, anchor, "t"), source)

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
            "op": "replace", "match": "vec4 {v} = P * V", "with": "vec4 {v} = iso(P, V)",
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
            Anchor.from_spec({"match": "x", "every": True, "occurrence": 2}, "t")

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
            self.build({"op": "insert", "match": "B", "text": "A", "where": "above"})
        self.assertIn("'before' or 'after'", str(caught.exception))

    def test_wrap_needs_a_prefix_or_a_suffix(self):
        with self.assertRaises(PatchError) as caught:
            self.build({"op": "wrap", "match": "v"})
        self.assertIn("at least one", str(caught.exception))

    def test_wrap_refuses_a_non_string_affix(self):
        with self.assertRaises(PatchError):
            self.build({"op": "wrap", "match": "v", "prefix": 3})

    def test_replace_without_with_is_refused(self):
        with self.assertRaises(PatchError) as caught:
            self.build({"op": "replace", "match": "v"})
        self.assertIn("needs a 'with' string", str(caught.exception))

    def test_names_lists_every_registered_operation(self):
        self.assertEqual(operations.names(),
                         ["declare", "function", "insert", "replace", "wrap"])


ONE_LINE = "#version 330\nvoid main() { gl_Position = A; }\n"

RETURNS = """#version 330
float clampish(float x) {
    if (x < 0.0) {
        return 0.0;
    }
    return x;
}
"""


class TestFunctionInjection(unittest.TestCase):
    """Mixin-style injection into a named function."""

    def apply(self, source, **spec):
        op, anchor = build_operation({"op": "function", **spec})
        return op.apply(source, anchor, "t")

    def test_it_needs_no_anchor(self):
        self.assertFalse(operations.get("function", "t").needs_anchor)

    def test_head_goes_first_in_the_body(self):
        out = self.apply(FUNCTIONS, function="main", at="HEAD", text="iso_setup();")
        body = out[out.rindex("void main() {") :].splitlines()
        self.assertEqual(body[1], "    iso_setup();")
        self.assertEqual(body[2], "    gl_Position = vec4(helper(1.0));")

    def test_head_is_the_default_point(self):
        self.assertEqual(
            self.apply(FUNCTIONS, function="main", text="iso_setup();"),
            self.apply(FUNCTIONS, function="main", at="HEAD", text="iso_setup();"),
        )

    def test_tail_goes_last_in_the_body(self):
        out = self.apply(FUNCTIONS, function="main", at="TAIL", text="iso_finish();")
        body = out[out.rindex("void main() {") :].splitlines()
        self.assertEqual(body[1], "    gl_Position = vec4(helper(1.0));")
        self.assertEqual(body[2], "    iso_finish();")
        self.assertEqual(body[3], "}")

    def test_return_goes_before_every_return_at_its_own_depth(self):
        out = self.apply(RETURNS, function="clampish", at="RETURN", text="trace();")
        self.assertEqual(out.count("trace();"), 2)
        self.assertIn("        trace();\n        return 0.0;", out)   # nested, deeper indent
        self.assertIn("    trace();\n    return x;", out)

    def test_multi_line_text_is_indented_line_by_line(self):
        out = self.apply(FUNCTIONS, function="main", at="HEAD",
                         text="float s = 2.0;\nfloat t = s * 3.0;")
        self.assertIn("    float s = 2.0;\n    float t = s * 3.0;\n", out)

    def test_a_one_line_body_stays_on_one_line(self):
        head = self.apply(ONE_LINE, function="main", at="HEAD", text="iso_setup();")
        self.assertIn("void main() { iso_setup(); gl_Position = A; }", head)
        tail = self.apply(ONE_LINE, function="main", at="TAIL", text="iso_finish();")
        self.assertIn("void main() { gl_Position = A; iso_finish(); }", tail)

    def test_an_empty_body_still_gets_one_level_of_indentation(self):
        out = self.apply("#version 330\nvoid main() {\n}\n", function="main", text="iso_setup();")
        self.assertIn("void main() {\n    iso_setup();\n}", out)

    def test_an_unknown_function_is_unresolved(self):
        with self.assertRaises(UnresolvedInjection) as caught:
            self.apply(FUNCTIONS, function="nowhere", text="x();")
        self.assertIn("no function named 'nowhere'", str(caught.exception))

    def test_return_without_a_return_statement_points_at_tail(self):
        with self.assertRaises(UnresolvedInjection) as caught:
            self.apply(FUNCTIONS, function="main", at="RETURN", text="x();")
        self.assertIn('use at = "TAIL"', str(caught.exception))

    def test_an_overloaded_name_is_ambiguous_and_names_the_lines(self):
        source = "vec3 f(vec3 v) { return v; }\nfloat f(float x) { return x; }\n"
        with self.assertRaises(AmbiguousInjection) as caught:
            self.apply(source, function="f", text="x();")
        self.assertIn("defined 2 times (lines [1, 2])", str(caught.exception))

    def test_occurrence_picks_one_overload(self):
        source = "vec3 f(vec3 v) { return v; }\nfloat f(float x) { return x; }\n"
        out = self.apply(source, function="f", occurrence=2, text="trace();")
        self.assertEqual(out.splitlines()[0], "vec3 f(vec3 v) { return v; }")
        self.assertEqual(out.splitlines()[1], "float f(float x) { trace(); return x; }")

    def test_occurrence_past_the_last_definition_is_unresolved(self):
        with self.assertRaises(UnresolvedInjection) as caught:
            self.apply(FUNCTIONS, function="main", occurrence=2, text="x();")
        self.assertIn("but it is defined 1 time(s)", str(caught.exception))

    def test_a_body_that_never_closes_is_unresolved(self):
        with self.assertRaises(UnresolvedInjection) as caught:
            self.apply("void main() {\n    x();\n", function="main", text="y();")
        self.assertIn("never closed", str(caught.exception))

    def test_the_injection_point_must_be_one_of_the_three(self):
        with self.assertRaises(PatchError) as caught:
            self.apply(FUNCTIONS, function="main", at="MIDDLE", text="x();")
        self.assertIn("HEAD, TAIL, RETURN", str(caught.exception))

    def test_a_function_name_is_required(self):
        with self.assertRaises(PatchError) as caught:
            self.apply(FUNCTIONS, at="HEAD", text="x();")
        self.assertIn("needs a 'function' name", str(caught.exception))

    def test_text_is_required(self):
        with self.assertRaises(PatchError):
            self.apply(FUNCTIONS, function="main", at="HEAD")

    def test_occurrence_must_be_a_positive_integer(self):
        with self.assertRaises(PatchError):
            self.apply(FUNCTIONS, function="main", text="x();", occurrence=0)

    def test_before_goes_above_the_signature(self):
        out = self.apply(FUNCTIONS, function="main", at="BEFORE",
                         text="vec4 iso_project(vec4 p);")
        self.assertIn("vec4 iso_project(vec4 p);\nvoid main() {", out)

    def test_after_goes_below_the_closing_brace(self):
        out = self.apply(FUNCTIONS, function="main", at="AFTER",
                         text="vec4 iso_project(vec4 p) { return p; }")
        lines = out.splitlines()
        closing = len(lines) - 1 - lines[::-1].index("}")
        self.assertEqual(lines[closing + 1], "vec4 iso_project(vec4 p) { return p; }")

    def test_before_and_after_keep_the_declaration_at_top_level(self):
        for point in ("BEFORE", "AFTER"):
            with self.subTest(at=point):
                out = self.apply(FUNCTIONS, function="main", at=point, text="float IsoScale;")
                self.assertIn("\nfloat IsoScale;\n", out)   # no indentation added

    def test_after_at_the_end_of_a_file_does_not_wrap_to_the_top(self):
        out = self.apply("void main() {}", function="main", at="AFTER", text="// end")
        self.assertEqual(out, "void main() {}\n// end\n")

    def test_before_picks_the_overload_it_is_pointed_at(self):
        source = "vec3 f(vec3 v) { return v; }\nfloat f(float x) { return x; }\n"
        out = self.apply(source, function="f", at="BEFORE", occurrence=2, text="// second")
        self.assertIn("// second\nfloat f(float x)", out)


INVOKED = """#version 330
void main() {
    vec3 pos = helper(x) + offset;
    if (pos.y < 0.0) {
        helper(1.0);
    }
    gl_Position = vec4(pos, 1.0);
}
"""


class TestInvokeInjection(unittest.TestCase):
    """at = "INVOKE": around the statement that calls a given function."""

    def apply(self, source=INVOKED, **spec):
        op, anchor = build_operation(
            {"op": "function", "function": "main", "at": "INVOKE", **spec}
        )
        return op.apply(source, anchor, "t")

    def test_before_is_the_default_side(self):
        self.assertEqual(
            self.apply(call="helper", text="trace();"),
            self.apply(call="helper", where="before", text="trace();"),
        )

    def test_before_puts_the_text_above_the_calling_statement(self):
        out = self.apply(call="helper", text="trace();")
        self.assertIn("    trace();\n    vec3 pos = helper(x) + offset;", out)

    def test_after_puts_the_text_below_the_calling_statement(self):
        out = self.apply(call="helper", where="after", text="trace();")
        self.assertIn("    vec3 pos = helper(x) + offset;\n    trace();", out)

    def test_every_call_in_the_body_is_hit_at_its_own_depth(self):
        out = self.apply(call="helper", text="trace();")
        self.assertEqual(out.count("trace();"), 2)
        self.assertIn("        trace();\n        helper(1.0);", out)   # nested, deeper indent

    def test_the_text_never_lands_inside_the_expression(self):
        # a statement cannot be spliced into `vec3 pos = helper(x) + offset;`
        out = self.apply(call="helper", text="trace();")
        self.assertIn("vec3 pos = helper(x) + offset;", out)
        self.assertNotIn("helper(trace();", out)

    def test_after_a_call_in_a_block_header_is_refused(self):
        source = "void main() {\n    if (helper(x)) {\n        y();\n    }\n}\n"
        with self.assertRaises(UnresolvedInjection) as caught:
            self.apply(source, call="helper", where="after", text="trace();")
        self.assertIn('use where = "before"', str(caught.exception))

    def test_before_a_call_in_a_block_header_is_fine(self):
        source = "void main() {\n    if (helper(x)) {\n        y();\n    }\n}\n"
        out = self.apply(source, call="helper", text="trace();")
        self.assertIn("    trace();\n    if (helper(x)) {", out)

    def test_a_call_that_never_happens_is_unresolved(self):
        with self.assertRaises(UnresolvedInjection) as caught:
            self.apply(call="nowhere", text="trace();")
        self.assertIn("no call to 'nowhere'", str(caught.exception))

    def test_invoke_needs_a_call_to_aim_at(self):
        with self.assertRaises(PatchError) as caught:
            self.apply(text="trace();")
        self.assertIn("needs a 'call'", str(caught.exception))

    def test_the_side_must_be_before_or_after(self):
        with self.assertRaises(PatchError) as caught:
            self.apply(call="helper", where="above", text="trace();")
        self.assertIn("'before' or 'after'", str(caught.exception))

    def test_call_and_where_belong_to_invoke_alone(self):
        for stray in ({"call": "helper"}, {"where": "after"}):
            with self.subTest(stray=stray):
                with self.assertRaises(PatchError) as caught:
                    build_operation({"op": "function", "function": "main", "at": "HEAD",
                                     "text": "x();", **stray})
                self.assertIn('only apply to at = "INVOKE"', str(caught.exception))
