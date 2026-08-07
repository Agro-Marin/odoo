import unittest

from odoo.tools.view_validation import (
    get_domain_value_names,
    get_expression_field_names,
)


class TestDomainErrorNormalization(unittest.TestCase):
    MALFORMED = ["compute_it()", "{'a': 1}", "42", "-x", "foo[1]", "lambda: 1"]

    def test_malformed_domains_raise_clean_message(self):
        for domain in self.MALFORMED:
            with self.subTest(domain=domain):
                with self.assertRaises(ValueError) as ctx:
                    get_domain_value_names(domain)
                self.assertEqual(str(ctx.exception), "Wrong domain formatting.")

    def test_valid_domain_still_parses(self):
        self.assertEqual(get_domain_value_names("[('a', '=', 1)]"), ({"a"}, set()))


class TestExpressionNodeHandling(unittest.TestCase):
    def test_dict_spread_extracts_source_not_crash(self):
        self.assertEqual(get_expression_field_names("{**a}"), {"a"})

    def test_unsupported_node_message_hides_the_ast(self):
        for expr, node in [
            ("f'{x}'", "JoinedStr"),
            ("[a for a in b]", "ListComp"),
            ("lambda: x", "Lambda"),
        ]:
            with self.subTest(expr=expr):
                with self.assertRaises(ValueError) as ctx:
                    get_expression_field_names(expr)
                msg = str(ctx.exception)
                self.assertEqual(msg, f"Unsupported expression: {node}.")
                self.assertNotIn("(", msg.rstrip("."))


if __name__ == "__main__":
    unittest.main()
