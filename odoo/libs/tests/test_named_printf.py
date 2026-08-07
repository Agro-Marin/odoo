import unittest

from odoo.libs.utils import named_to_positional_printf


class TestNamedToPositionalPrintf(unittest.TestCase):
    def test_plain_conversion(self):
        self.assertEqual(named_to_positional_printf("%(x)s", {"x": 1}), ("%s", (1,)))

    def test_conversions_carrying_a_spec_are_converted(self):
        self.assertEqual(
            named_to_positional_printf("%(amt).2f", {"amt": 1.5}), ("%s", (1.5,))
        )
        self.assertEqual(
            named_to_positional_printf("%(n)-10s", {"n": "q"}), ("%s", ("q",))
        )

    def test_argument_order_follows_the_string(self):
        self.assertEqual(
            named_to_positional_printf("%(a)s/%(b)d", {"a": "x", "b": 2}),
            ("%s/%s", ("x", 2)),
        )

    def test_escaped_percent_is_not_a_conversion(self):
        self.assertEqual(
            named_to_positional_printf("100%% of %(x)s", {"x": 1}),
            ("100%% of %s", (1,)),
        )
        self.assertEqual(named_to_positional_printf("50%% done", {}), ("50%% done", ()))

    def test_no_placeholders_is_a_passthrough(self):
        self.assertEqual(
            named_to_positional_printf("nothing here", {}), ("nothing here", ())
        )

    def test_prose_after_a_name_is_not_swallowed(self):
        for text in ("literal %(notaconv) here", "%(user) said hello"):
            with self.assertRaises(ValueError) as ctx:
                named_to_positional_printf(text, {})
            self.assertIn("unsupported named placeholder", str(ctx.exception))

    def test_missing_key_raises_keyerror(self):
        with self.assertRaises(KeyError):
            named_to_positional_printf("%(missing)s", {})


if __name__ == "__main__":
    unittest.main()
