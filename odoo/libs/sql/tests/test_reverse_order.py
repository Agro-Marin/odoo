"""Regression tests for ``odoo.libs.sql.utils.reverse_order``."""

import unittest

from odoo.libs.sql.utils import reverse_order


class TestReverseOrder(unittest.TestCase):
    def test_default_direction(self):
        self.assertEqual(reverse_order("id"), "id desc")

    def test_flip_asc_desc(self):
        self.assertEqual(reverse_order("name asc, date desc"), "name desc, date asc")

    def test_flips_explicit_nulls_placement(self):
        self.assertEqual(reverse_order("name asc nulls last"), "name desc nulls first")
        self.assertEqual(reverse_order("name desc nulls first"), "name asc nulls last")

    def test_preserves_quoted_identifier_case(self):
        # quoting and case must survive (was lowercased to '"name"' before).
        self.assertEqual(reverse_order('"Name" desc'), '"Name" asc')

    def test_qualified_column(self):
        self.assertEqual(reverse_order("res_partner.name asc"), "res_partner.name desc")

    def test_trailing_comma_is_skipped(self):
        # was an IndexError on the empty segment.
        self.assertEqual(reverse_order("a asc,"), "a desc")
        self.assertEqual(reverse_order("a, b desc"), "a desc, b asc")

    def test_double_reverse_is_identity(self):
        for order in (
            "id",
            "name asc, date desc",
            '"Name" desc nulls first',
            "a asc nulls last, b desc",
        ):
            self.assertEqual(reverse_order(reverse_order(order)), _normalize(order))


def _normalize(order: str) -> str:
    # reverse_order lowercases the ASC/DESC/NULLS keywords and normalizes spacing
    # while keeping the expression; normalize the expected side the same way.
    out = []
    for item in order.split(","):
        tokens = item.split()
        nulls = ""
        if len(tokens) >= 2 and tokens[-2].lower() == "nulls":
            nulls = f" nulls {tokens[-1].lower()}"
            tokens = tokens[:-2]
        direction = "asc"
        if tokens and tokens[-1].lower() in ("asc", "desc"):
            direction = tokens[-1].lower()
            tokens = tokens[:-1]
        out.append(f"{' '.join(tokens)} {direction}{nulls}")
    return ", ".join(out)


if __name__ == "__main__":
    unittest.main()
