import unittest
from decimal import Decimal

from odoo.tools.rendering_tools import (
    parse_inline_template,
    render_inline_template,
    renders_as_no_value,
)


def render(template, **variables):
    return render_inline_template(parse_inline_template(template), variables)


class TestRendersAsNoValue(unittest.TestCase):
    def test_orm_unset_markers_are_no_value(self):
        for value in (None, False, "", [], {}, ()):
            with self.subTest(value=value):
                self.assertTrue(renders_as_no_value(value))

    def test_numeric_zero_is_a_value(self):
        for value in (0, 0.0, Decimal(0), -0.0):
            with self.subTest(value=value):
                self.assertFalse(renders_as_no_value(value))

    def test_ordinary_values_render(self):
        for value in (True, 1, "x", "0", "False", [0], 0.1):
            with self.subTest(value=value):
                self.assertFalse(renders_as_no_value(value))

    def test_binary_has_no_text_form(self):
        # `str` answers `b'iVBORw0KGgo...'` -- the whole base64 payload plus the
        # Python repr around it -- which used to be what a binary field put in
        # a mail subject.
        for value in (b"iVBORw0KGgo", b"", bytearray(b"x"), memoryview(b"x")):
            with self.subTest(value=value):
                self.assertTrue(renders_as_no_value(value))


class TestRenderInlineTemplateNoValue(unittest.TestCase):
    def test_false_renders_as_nothing_not_the_word_false(self):
        self.assertEqual(render("{{ x }}", x=False), "")
        self.assertEqual(render("Hello {{ x }}!", x=False), "Hello !")

    def test_false_falls_back_to_the_default(self):
        self.assertEqual(render("{{ x ||| Anonymous}}", x=False), "Anonymous")
        self.assertEqual(render("{{ x ||| Anonymous}}", x=None), "Anonymous")

    def test_lang_placeholder_never_yields_the_string_false(self):
        self.assertEqual(render("{{ object_lang }}", object_lang=False), "")

    def test_numeric_zero_still_renders(self):
        self.assertEqual(render("{{ x }}", x=0), "0")
        self.assertEqual(render("Total: {{ x }}", x=0), "Total: 0")
        self.assertEqual(render("{{ x }}", x=0.0), "0.0")

    def test_zero_beats_the_default(self):
        self.assertEqual(render("{{ x ||| n/a}}", x=0), "0")

    def test_unrelated_values_are_untouched(self):
        self.assertEqual(render("Hi {{ x ||| there}}!", x="Bob"), "Hi Bob!")
        self.assertEqual(render("{{ x }}", x=True), "True")
        self.assertEqual(render("no placeholder", x=False), "no placeholder")


class TestInlineDefaultEscaping(unittest.TestCase):
    """`}}` ends a placeholder, so a default holding one needs an escape."""

    def test_escaped_terminator_survives(self):
        self.assertEqual(
            parse_inline_template(r"{{x ||| see \}\} here}}"),
            [("", "x", "see }} here")],
        )
        self.assertEqual(render(r"{{ x ||| see \}\} here}}", x=False), "see }} here")

    def test_escaped_backslash_survives(self):
        self.assertEqual(render(r"{{ x ||| trail\\}}", x=False), "trail\\")

    def test_a_lone_backslash_is_left_as_authored(self):
        # Written before the escape existed, and must keep parsing the same way.
        self.assertEqual(render(r"{{ x ||| C:\temp}}", x=False), r"C:\temp")
        self.assertEqual(render(r"{{ x ||| back\}}", x=False), "back\\")

    def test_an_unescaped_terminator_still_truncates(self):
        # Not a regression: the old grammar did this too, and templates already
        # stored in that shape must not change meaning.
        self.assertEqual(render("{{ x ||| see }} here}}", x=False), "see  here}}")

    def test_the_separator_needs_no_escaping(self):
        self.assertEqual(render("{{ x ||| a ||| b}}", x=False), "a ||| b")

    def test_two_placeholders_on_one_line(self):
        self.assertEqual(render("{{ a ||| p}} {{ b ||| q}}", a=False, b=False), "p q")

    def test_binary_falls_back_to_the_default(self):
        self.assertEqual(render("{{ x ||| (none)}}", x=b"payload"), "(none)")
