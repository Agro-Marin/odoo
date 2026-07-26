"""``{{ ... }}`` inline templates must not stringify the ORM's "unset" markers.

``render_inline_template`` used to end an expression with ``or default`` and
``if result:``, which dropped every falsy result -- including a numeric ``0``,
so ``Total: {{ object.amount_total }}`` rendered ``Total:`` on a zero invoice.
Fixing that by testing ``result is None or result == ""`` overshot: ``False``
is neither, and ``False != ""``, so an unset field started rendering as the
literal text ``"False"`` -- into subjects, bodies, and (via
``mail.template.lang``) into ``env.lang``, where it surfaced as
``UserError: Invalid language code: False``.

The two conditions cannot be collapsed into one truthiness test because
``False == 0`` and ``bool`` subclasses ``int``. ``renders_as_no_value`` is the
single definition of the contract, shared with the regex mode of the same
engine in ``mail.render.mixin._render_template_inline_template_regex``, and
matching QWeb's ``t-out`` (the engine ``convert_inline_template_to_qweb``
compiles these placeholders down to): *None or False means no value*.
"""

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
        """False is what the ORM returns for every unset non-numeric field."""
        for value in (None, False, "", [], {}, ()):
            with self.subTest(value=value):
                self.assertTrue(renders_as_no_value(value))

    def test_numeric_zero_is_a_value(self):
        """0 is a genuine amount/quantity and must render, unlike False."""
        for value in (0, 0.0, Decimal(0), -0.0):
            with self.subTest(value=value):
                self.assertFalse(renders_as_no_value(value))

    def test_ordinary_values_render(self):
        for value in (True, 1, "x", "0", "False", [0], 0.1):
            with self.subTest(value=value):
                self.assertFalse(renders_as_no_value(value))


class TestRenderInlineTemplateNoValue(unittest.TestCase):
    def test_false_renders_as_nothing_not_the_word_false(self):
        self.assertEqual(render("{{ x }}", x=False), "")
        self.assertEqual(render("Hello {{ x }}!", x=False), "Hello !")

    def test_false_falls_back_to_the_default(self):
        self.assertEqual(render("{{ x ||| Anonymous}}", x=False), "Anonymous")
        self.assertEqual(render("{{ x ||| Anonymous}}", x=None), "Anonymous")

    def test_lang_placeholder_never_yields_the_string_false(self):
        """The regression that broke ~57 mail tests: a template whose ``lang``
        renders to ``"False"`` reaches ``env.lang``, which rejects it as an
        invalid language code instead of falling back to the default lang."""
        self.assertEqual(render("{{ object_lang }}", object_lang=False), "")

    def test_numeric_zero_still_renders(self):
        self.assertEqual(render("{{ x }}", x=0), "0")
        self.assertEqual(render("Total: {{ x }}", x=0), "Total: 0")
        self.assertEqual(render("{{ x }}", x=0.0), "0.0")

    def test_zero_beats_the_default(self):
        """A zero is a real value, so the ``|||`` fallback must not fire."""
        self.assertEqual(render("{{ x ||| n/a}}", x=0), "0")

    def test_unrelated_values_are_untouched(self):
        self.assertEqual(render("Hi {{ x ||| there}}!", x="Bob"), "Hi Bob!")
        self.assertEqual(render("{{ x }}", x=True), "True")
        self.assertEqual(render("no placeholder", x=False), "no placeholder")
