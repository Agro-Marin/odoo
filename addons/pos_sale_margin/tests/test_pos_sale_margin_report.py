import odoo
from odoo.tools import SQL

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestPoSSaleMarginReport(TestPoSCommon):
    def setUp(self):
        super().setUp()
        self.config = self.basic_config

    def _pos_report_margins(self):
        """Run ``sale.report``'s real POS-side query and return its
        ``margin`` column for every row.

        A plain ``sale.report.search()`` can't be used here: ``pos_sale``'s
        ``_get_fields_pos_select()`` feeds its *whole* field registry
        through ``_fill_pos_fields()``, whose base implementation NULLs any
        key it does not explicitly whitelist -- so almost every POS column,
        including ``id``, reads back as NULL (task 28563, in ``pos_sale``,
        out of this module's scope; not fixed here). With ``id`` NULL on
        every POS row, the ORM cannot tell the rows apart by identity
        either, so a domain filter or ``.mapped()`` on the resulting
        recordset is unreliable. Running the query directly and reading the
        ``margin`` column back as plain SQL sidesteps both issues while
        still exercising the real, unmodified query this module builds.
        """
        self.env.flush_all()
        report = self.env["sale.report"].sudo()
        query = SQL(
            "SELECT %s FROM %s WHERE %s GROUP BY %s",
            report._select_pos(),
            report._from_pos(),
            report._where_pos(),
            report._group_by_pos(),
        )
        self.env.cr.execute(query)
        cols = [d.name for d in self.env.cr.description]
        margin_index = cols.index("margin")
        return [row[margin_index] for row in self.env.cr.fetchall()]

    def test_pos_sale_margin_report(self):

        product1 = self.create_product(
            "Product 1", self.categ_basic, 150, standard_price=50
        )

        self.open_new_session()
        session = self.pos_session

        self.env["pos.order"].create(
            {
                "session_id": session.id,
                "lines": [
                    (
                        0,
                        0,
                        {
                            "name": "OL/0001",
                            "product_id": product1.id,
                            "price_unit": 450,
                            "discount": 5.0,
                            "qty": 1.0,
                            "price_subtotal": 150,
                            "price_subtotal_incl": 150,
                            "total_cost": 50,
                        },
                    ),
                ],
                "amount_total": 150.0,
                "amount_tax": 0.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
            }
        )

        margins = self._pos_report_margins()
        self.assertEqual(margins, [100])

    def test_pos_sale_margin_report_refund(self):
        """A refund's reported margin must match the sign the stored,
        already-correctly-signed ``pos.order.line.margin`` field carries.

        Regression test for task 28564: the POS-side ``margin`` SQL used to
        re-derive ``price_subtotal - total_cost`` from raw columns instead
        of reusing ``l.margin``, so a refund line (whose stored margin is
        negative) reported the *original* sale's positive margin instead.
        """
        product1 = self.create_product(
            "Refund Product", self.categ_basic, 150, standard_price=50
        )

        self.open_new_session()
        session = self.pos_session

        order = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "lines": [
                    (
                        0,
                        0,
                        {
                            "name": "OL/REFUND",
                            "product_id": product1.id,
                            "price_unit": 150,
                            "discount": 0.0,
                            "qty": 1.0,
                            "price_subtotal": 150,
                            "price_subtotal_incl": 150,
                            "total_cost": 50,
                        },
                    ),
                ],
                "amount_total": 150.0,
                "amount_tax": 0.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
            }
        )
        order.lines.is_total_cost_computed = True
        self.assertEqual(order.lines.margin, 100)

        refund_order = order._refund()
        self.assertEqual(refund_order.lines.margin, -200)

        self.assertEqual(sorted(self._pos_report_margins()), [-200, 100])

    def test_pos_sale_margin_uses_currency_table_factor(self):
        """Guard against re-introducing the missing currency-table factor.

        Regression test for task 28564: every sibling POS-side monetary
        field multiplies by ``account_currency_table.rate`` after dividing
        by ``pos.currency_rate``; the ``margin`` expression used to skip
        that factor entirely, so a report viewed in a different reporting
        currency (or any multi-company deployment with more than one
        currency) got systematically wrong figures.
        """
        expression = self.env["sale.report"]._fill_pos_fields({})["margin"]
        self.assertIn("l.margin", expression)
        self.assertIn("account_currency_table.rate", expression)
        self.assertIn("pos.currency_rate", expression)
