"""The evaluation-free QWeb renderer, without a database.

`mail` renders a `t-out` body two ways and they must produce the same bytes.
The half of the second renderer that is a function of a tree and a value lives
in `odoo.tools.rendering_tools`, so it is pinned here -- in Tier 1, no registry,
no cursor -- rather than in a `post_install` integration suite that has to
install `test_mail` to ask what `<p/>` serialises to.
"""

import unittest

from lxml import html
from markupsafe import Markup

from odoo.tools.rendering_tools import (
    HOLE_CLOSE,
    HOLE_OPEN,
    StaticRenderUnsupported,
    compile_static_template,
    escape_static_text,
    render_static_program,
    serialize_static_tree,
)


def parse(source):
    """Parse a body the way the renderer's caller does."""
    return html.fragment_fromstring(source, create_parent="div")


def render(source, values=None, missing=None):
    """Compile ``source`` and fill it from ``values``."""
    values = values or {}
    segments, holes = compile_static_template(parse(source))
    return str(render_static_program(segments, holes, lambda e: values.get(e, missing)))


class TestCompile(unittest.TestCase):
    def test_a_body_with_no_placeholder_compiles_to_one_segment(self):
        segments, holes = compile_static_template(parse("<p>plain</p>"))
        self.assertEqual(segments, ["<p>plain</p>"])
        self.assertEqual(holes, [])

    def test_each_placeholder_yields_a_hole_and_its_default(self):
        segments, holes = compile_static_template(
            parse('<p t-out="a">x</p><b t-out="b"/>')
        )
        self.assertEqual(holes, [("a", "x"), ("b", "")])
        self.assertEqual(len(segments), len(holes) + 1)

    def test_the_default_is_stripped_and_escaped_once(self):
        _segments, holes = compile_static_template(
            parse('<p t-out="a">  Ben &amp; Jerry  </p>')
        )
        self.assertEqual(holes[0][1], "Ben &amp; Jerry")

    def test_the_expression_is_read_stripped(self):
        _segments, holes = compile_static_template(parse('<p t-out=" a.b "/>'))
        self.assertEqual(holes[0][0], "a.b")

    def test_a_t_element_leaves_no_tag_behind(self):
        self.assertEqual(render('<t t-out="a"/>', {"a": "V"}), "V")


class TestHoleMarkers(unittest.TestCase):
    """U+E000 is the first Private Use codepoint -- the first glyph of most icon
    fonts -- so it reaches a mail body by ordinary copy-paste."""

    def test_a_marker_in_the_body_is_refused_rather_than_substituted(self):
        source = f'<p>{HOLE_OPEN}0{HOLE_CLOSE}</p><b t-out="a">d</b>'
        with self.assertRaises(StaticRenderUnsupported):
            compile_static_template(parse(source))

    def test_a_marker_naming_a_hole_that_does_not_exist_is_refused(self):
        source = f'<p>{HOLE_OPEN}5{HOLE_CLOSE}</p><b t-out="a">d</b>'
        with self.assertRaises(StaticRenderUnsupported):
            compile_static_template(parse(source))

    def test_an_unpaired_marker_is_just_text(self):
        source = f'<p>{HOLE_OPEN} lone</p><b t-out="a">d</b>'
        self.assertEqual(render(source, {"a": "V"}), f"<p>{HOLE_OPEN} lone</p><b>V</b>")


class TestNoValue(unittest.TestCase):
    """None and False are what `_compile_out_emit` writes the default for."""

    def test_none_and_false_take_the_default(self):
        for value in (None, False):
            with self.subTest(value=value):
                self.assertEqual(render('<p t-out="a">d</p>', {"a": value}), "<p>d</p>")

    def test_an_empty_string_is_a_value(self):
        self.assertEqual(render('<p t-out="a">d</p>', {"a": ""}), "<p></p>")

    def test_zero_is_a_value(self):
        self.assertEqual(render('<p t-out="a">d</p>', {"a": 0}), "<p>0</p>")

    def test_no_value_and_no_default_keeps_the_element(self):
        self.assertEqual(render('<p t-out="a"/>', {"a": None}), "<p></p>")


class TestEscaping(unittest.TestCase):
    def test_a_value_is_escaped(self):
        self.assertEqual(
            render('<p t-out="a"/>', {"a": 'say "hi" & <b>'}),
            "<p>say &#34;hi&#34; &amp; &lt;b&gt;</p>",
        )

    def test_markup_is_inserted_as_markup(self):
        self.assertEqual(
            render('<p t-out="a"/>', {"a": Markup("<b>Sig &amp; co</b>")}),
            "<p><b>Sig &amp; co</b></p>",
        )

    def test_a_non_string_value_is_stringified_then_escaped(self):
        self.assertEqual(render('<p t-out="a"/>', {"a": 12}), "<p>12</p>")

    def test_escape_static_text_leaves_quotes_alone(self):
        """It escapes an element body, where a quote needs no escaping -- and
        `ir.qweb` emits none there either."""
        self.assertEqual(
            escape_static_text('a & b < c > d "q"'), 'a &amp; b &lt; c &gt; d "q"'
        )


class TestSerialisation(unittest.TestCase):
    """`ir.qweb` writes XHTML; this renderer must write the same bytes."""

    def test_an_empty_non_void_element_keeps_both_tags(self):
        self.assertEqual(str(serialize_static_tree(parse("<p></p>"))), "<p></p>")

    def test_a_void_element_stays_self_closing(self):
        for source in ("<p>a<br/>b</p>", "<p>a<br>b</p>"):
            with self.subTest(source=source):
                self.assertEqual(
                    str(serialize_static_tree(parse(source))), "<p>a<br/>b</p>"
                )

    def test_a_boolean_attribute_is_written_out(self):
        self.assertEqual(
            str(serialize_static_tree(parse('<input type="checkbox" checked/>'))),
            '<input type="checkbox" checked="checked"/>',
        )

    def test_the_parent_wrapper_is_stripped(self):
        self.assertEqual(str(serialize_static_tree(parse("<p>x</p>"))), "<p>x</p>")

    def test_an_empty_body_is_empty_not_a_collapsed_wrapper(self):
        self.assertEqual(str(serialize_static_tree(parse("<t></t>"))), "<t></t>")


class TestProgramShape(unittest.TestCase):
    def test_a_program_is_one_more_segment_than_it_has_holes(self):
        for source in ("<p>x</p>", '<p t-out="a"/>', '<p t-out="a"/><p t-out="b"/>'):
            with self.subTest(source=source):
                segments, holes = compile_static_template(parse(source))
                self.assertEqual(len(segments), len(holes) + 1)

    def test_a_mismatched_program_is_a_programming_error_not_bad_output(self):
        with self.assertRaises(ValueError):
            render_static_program(["a"], [("x", "")], lambda _e: "v")

    def test_resolve_is_called_once_per_hole_in_document_order(self):
        seen = []
        segments, holes = compile_static_template(
            parse('<p t-out="first"/><p t-out="second"/>')
        )
        render_static_program(segments, holes, lambda e: seen.append(e) or "v")
        self.assertEqual(seen, ["first", "second"])
