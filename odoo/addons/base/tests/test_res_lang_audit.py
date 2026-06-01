import ast

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.base.models.res_lang import _parse_grouping


@tagged("post_install", "-at_install")
class TestResLangFormatGrouping(TransactionCase):
    """RL-P1: res.lang.format() with grouping must stay behaviour-preserving now
    that the grouping spec is parsed via the cached _parse_grouping helper
    instead of ast.literal_eval on every formatted value.
    """

    def test_parse_grouping_matches_literal_eval(self):
        # The cached helper returns exactly what ast.literal_eval produced (as a
        # tuple, consumed read-only by intersperse/split).
        for spec in ("[3,0]", "[3,2,0]", "[]"):
            self.assertEqual(_parse_grouping(spec), tuple(ast.literal_eval(spec)))

    def test_format_grouping_thousands(self):
        lang = self.env["res.lang"].search([("code", "=", "en_US")], limit=1)
        self.assertTrue(lang, "en_US locale expected")
        # Float and integer formatting with grouping insert the thousands sep.
        self.assertEqual(lang.format("%.2f", 1000000.0, grouping=True), "1,000,000.00")
        self.assertEqual(lang.format("%d", 1234567, grouping=True), "1,234,567")
        # Without grouping, no separators are inserted.
        self.assertEqual(lang.format("%.2f", 1000000.0), "1000000.00")
