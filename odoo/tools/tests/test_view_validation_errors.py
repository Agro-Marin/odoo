"""Regression tests for error normalization in ``view_validation``.

Two defects: malformed *string* domains reached ``.elts`` on AST nodes that
don't have it, raising a raw ``AttributeError`` (e.g. ``'Call' object has no
attribute 'elts'``) that the function's ``except ValueError`` never normalized —
so the raw Python message leaked into the user-facing view error instead of the
intended "Wrong domain formatting." And unsupported expression nodes were
reported with ``repr(ast_node)``, dumping the whole AST into that same error;
``**``-spread dict entries additionally crashed on a ``None`` key.

No Odoo ORM / database dependency — runs under the standalone pytest suite.
"""

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
        self.assertEqual(
            get_domain_value_names("[('a', '=', 1)]"), ({"a"}, set())
        )


class TestExpressionNodeHandling(unittest.TestCase):
    def test_dict_spread_extracts_source_not_crash(self):
        # ``{**a}`` carries a None key; the spread source must still be extracted.
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
                # never leak an AST repr
                self.assertNotIn("(", msg.rstrip("."))


if __name__ == "__main__":
    unittest.main()
