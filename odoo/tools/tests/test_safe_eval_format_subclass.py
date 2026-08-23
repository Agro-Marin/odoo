"""The format guard against a ``str`` *subclass* receiver.

``assert_no_dunder_format_field`` reads the template out of ``co_consts``, so it
only ever sees a literal written in the expression. Everything that arrives from
the evaluation context -- an ``html`` field, which reads back as
``markupsafe.Markup`` -- is covered by ``_guard_format`` alone, and that guard
used to test ``type(recv) is str``, which no subclass satisfies.

Two halves have to hold at once, and the cheap fix only gets the first:
rebuilding the receiver as a plain ``_GuardedStr`` blocks the attribute read and
silently drops Markup's auto-escaping, which trades a disclosure bug for an
injection one. Both columns are pinned here for that reason.
"""

import unittest
from datetime import date

from markupsafe import Markup

from odoo.tools.safe_eval import safe_eval


class Receiver:
    """Stands in for a record: an ordinary object with a bound method."""

    body = Markup("{0.method.__globals__}")

    def method(self):
        pass


class TestFormatGuardStrSubclass(unittest.TestCase):
    def assertBlocked(self, expr, context):
        with self.assertRaises(ValueError) as caught:
            safe_eval(expr, context)
        self.assertIn("attribute access is not allowed", str(caught.exception))

    # --- the guard fires for a subclass receiver -------------------------

    def test_markup_attribute_access_is_blocked(self):
        self.assertBlocked(
            "m.format(o)", {"m": Markup("{0.__class__}"), "o": Receiver()}
        )

    def test_markup_reaches_globals_when_unguarded(self):
        self.assertBlocked(
            "m.format(o)",
            {"m": Markup("{0.method.__globals__}"), "o": Receiver()},
        )

    def test_markup_format_map_is_blocked(self):
        self.assertBlocked(
            "m.format_map(d)",
            {"m": Markup("{o.__class__}"), "d": {"o": Receiver()}},
        )

    def test_conversion_does_not_smuggle_an_attribute(self):
        self.assertBlocked(
            "m.format(o)", {"m": Markup("{0.method!r}"), "o": Receiver()}
        )

    def test_receiver_reached_through_a_field_read(self):
        """Nothing is seeded in the context: this is the mail-template shape."""
        self.assertBlocked("r.body.format(r)", {"r": Receiver()})

    # --- nested replacement fields ---------------------------------------

    def test_nested_format_spec_is_blocked(self):
        """``{0:{1.attr}}``.

        A pre-scan of the template with ``Formatter.parse`` does not descend
        into a format spec, so it reads ``{1.attr}`` as opaque text. Only
        ``get_field`` -- reached through ``vformat``'s recursion -- sees it.
        ``date.__format__`` returns a spec holding no ``%`` codes verbatim, so
        the payload would come straight back to the caller.
        """
        for receiver in (
            Markup("{0:{1.method.__globals__}}"),
            "{0:{1.method.__globals__}}",
        ):
            with self.subTest(receiver=type(receiver).__name__):
                self.assertBlocked(
                    "m.format(d, o)",
                    {"m": receiver, "d": date(2026, 1, 1), "o": Receiver()},
                )

    # --- and the receiver keeps its own semantics -------------------------

    def test_markup_still_escapes_and_stays_markup(self):
        result = safe_eval("m.format(x)", {"m": Markup("<b>{0}</b>"), "x": "<i>"})
        self.assertEqual(result, Markup("<b>&lt;i&gt;</b>"))
        self.assertIsInstance(result, Markup)

    def test_markup_keeps_working_nested_specs(self):
        result = safe_eval(
            "m.format(a, b)", {"m": Markup("{0:{1}}"), "a": 3.14159, "b": ".2f"}
        )
        self.assertEqual(result, Markup("3.14"))
        self.assertIsInstance(result, Markup)

    def test_plain_formatting_is_untouched(self):
        for expr, context, expected in (
            ("'{} {}'.format(a, b)", {"a": 1, "b": 2}, "1 2"),
            ("'{0[1]}'.format(t)", {"t": [9, 8]}, "8"),
            ("'{x:>5.2f}'.format(x=3.14159)", {}, " 3.14"),
            ("'{0:{1}}'.format(a, b)", {"a": 3.14159, "b": ".2f"}, "3.14"),
        ):
            with self.subTest(expr=expr):
                result = safe_eval(expr, dict(context))
                self.assertEqual(result, expected)
                self.assertIs(type(result), str)

    def test_indexing_is_still_allowed_on_a_subclass(self):
        result = safe_eval("m.format(t)", {"m": Markup("{0[1]}"), "t": ["a", "b"]})
        self.assertEqual(result, Markup("b"))

    def test_str_itself_as_receiver_is_still_guarded(self):
        self.assertBlocked("str.format(m, o)", {"m": "{0.__class__}", "o": Receiver()})


if __name__ == "__main__":
    unittest.main()
