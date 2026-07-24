"""Regression tests for ``odoo.libs.utils`` helpers."""

import unittest

from odoo.libs.utils import named_to_positional_printf, replace_exceptions


class TestNamedToPositionalPrintf(unittest.TestCase):
    def test_preserves_width_and_precision(self):
        fmt, args = named_to_positional_printf("%(x)05d", {"x": 7})
        self.assertEqual(fmt % args, "00007")
        fmt, args = named_to_positional_printf("%(x).2f", {"x": 3.14159})
        self.assertEqual(fmt % args, "3.14")
        fmt, args = named_to_positional_printf("%(s)-4s|", {"s": "hi"})
        self.assertEqual(fmt % args, "hi  |")

    def test_escaped_percent_passes_through(self):
        # '%%' is a literal percent and must not be read as a named spec.
        fmt, args = named_to_positional_printf("%%(lit)s %(n)s", {"n": "W"})
        self.assertEqual(args, ("W",))
        self.assertEqual(fmt % args, "%(lit)s W")

    def test_plain_named_spec(self):
        fmt, args = named_to_positional_printf("Hello %(name)s", {"name": "World"})
        self.assertEqual(fmt % args, "Hello World")


class TestReplaceExceptions(unittest.TestCase):
    def test_class_replacement_preserves_all_args(self):
        with self.assertRaises(ValueError) as cm:
            with replace_exceptions(KeyError, by=ValueError):
                raise KeyError("a", "b", "c")
        self.assertEqual(cm.exception.args, ("a", "b", "c"))

    def test_instance_replacement_raises_a_copy(self):
        shared = RuntimeError("boom")
        raised = []
        for i in range(2):
            try:
                with replace_exceptions(KeyError, by=shared):
                    raise KeyError(i)
            except RuntimeError as exc:
                raised.append(exc)
        # a fresh copy each time, so the shared instance is never mutated
        self.assertIsNot(raised[0], shared)
        self.assertIsNot(raised[1], shared)
        self.assertIsNot(raised[0], raised[1])

    def test_uncaught_exception_passes_through(self):
        with self.assertRaises(TypeError):
            with replace_exceptions(KeyError, by=ValueError):
                raise TypeError("unrelated")


if __name__ == "__main__":
    unittest.main()
