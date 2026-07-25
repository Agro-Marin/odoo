"""A ``Markup`` argument must survive ``get_translation`` whether it is passed
directly or nested inside an iterable argument.

``get_translation`` escapes the translation template (and so returns ``Markup``)
when an argument is ``Markup`` -- but the scan only looked at the *top level*.
An iterable argument goes through ``babel``'s ``format_list``, which
``str()``-ifies every element and returns a plain ``str``, so
``_("Missing: %s", [Markup(html), "b"])`` came back as a plain ``str`` carrying
raw, unescaped HTML.

That is the one shape that is wrong in both directions: a caller that treats a
``_()`` result as markup (Odoo routinely feeds them to HTML fields and QWeb
``t-out``) injected the payload verbatim, and a caller that escapes the result
destroyed the markup the caller deliberately passed.  Both are silent.

No Odoo ORM / database dependency -- ``get_translation`` is called directly with
an explicit module and language.
"""

import unittest

from markupsafe import Markup

from odoo.tools.translate import get_translation

TRUSTED = Markup("<b>bold</b>")
UNTRUSTED = '<img src=x onerror="alert(1)">'


def tr(template, args):
    return get_translation("base", "en_US", template, args)


class TestMarkupInIterableArgument(unittest.TestCase):
    def test_markup_nested_in_a_list_makes_the_result_markup(self):
        out = tr("Value: %s", ([TRUSTED, "b"],))
        self.assertIsInstance(out, Markup)

    def test_trusted_markup_is_not_escaped(self):
        out = tr("Value: %s", ([TRUSTED, "b"],))
        self.assertIn("<b>bold</b>", out)

    def test_untrusted_neighbour_is_escaped(self):
        """The headline case: raw HTML must not ride along unescaped."""
        out = tr("Value: %s", ([TRUSTED, UNTRUSTED],))
        self.assertNotIn("<img", out)
        self.assertIn("&lt;img", out)
        self.assertIn("<b>bold</b>", out)

    def test_same_contract_for_named_arguments(self):
        out = tr("Value: %(x)s", {"x": [TRUSTED, UNTRUSTED]})
        self.assertIsInstance(out, Markup)
        self.assertNotIn("<img", out)
        self.assertIn("<b>bold</b>", out)

    def test_the_template_itself_is_escaped_too(self):
        """Escaping the template is what makes the result safe to treat as markup."""
        out = tr("a < b: %s", ([TRUSTED],))
        self.assertIn("a &lt; b", out)


class TestUnchangedBehaviour(unittest.TestCase):
    """The paths that already worked must keep working."""

    def test_top_level_markup_still_returns_markup(self):
        out = tr("Value: %s", (TRUSTED,))
        self.assertIsInstance(out, Markup)
        self.assertIn("<b>bold</b>", out)

    def test_plain_list_is_still_a_plain_str(self):
        out = tr("Value: %s", (["a", "b"],))
        self.assertNotIsInstance(out, Markup)
        self.assertEqual(out, "Value: a and b")

    def test_plain_arguments_are_untouched(self):
        self.assertEqual(tr("Value: %s", ("plain",)), "Value: plain")
        self.assertEqual(tr("Value: %d", (42,)), "Value: 42")

    def test_no_arguments(self):
        self.assertEqual(tr("Value", ()), "Value")

    def test_list_localisation_is_preserved(self):
        """The Markup path must still go through babel's list formatting."""
        self.assertEqual(tr("%s", (["a", "b", "c"],)), "a, b, and c")
        out = tr("%s", ([TRUSTED, "b", "c"],))
        self.assertEqual(out, Markup("<b>bold</b>, b, and c"))


if __name__ == "__main__":
    unittest.main()
