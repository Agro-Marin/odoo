from lxml import html

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestSaleOrderLineNumbering(SaleCommon):
    """The number the customer reads next to a line.

    It is derived once, in Python, from the very lines the document reports,
    so the printed order and the portal page cannot disagree about which line
    is "line 3".
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "line_ids": [
                    Command.create(
                        {"display_type": "line_section", "name": "Materials"}
                    ),
                    Command.create({"product_id": cls.product.id, "product_qty": 1.0}),
                    Command.create(
                        {"display_type": "line_subsection", "name": "Extras"}
                    ),
                    Command.create(
                        {"product_id": cls.service_product.id, "product_qty": 2.0}
                    ),
                    Command.create(
                        {"display_type": "line_note", "name": "Flat delivery"}
                    ),
                ],
            }
        )

    def _render(self, order):
        html_bytes, _report_type = self.env["ir.actions.report"]._render_qweb_html(
            "sale.report_saleorder", order.ids
        )
        return html.fromstring(html_bytes)

    def test_numbering_is_off_until_the_company_asks_for_it(self):
        self.assertFalse(
            self.env.company.show_sol_numbers,
            "line numbers must stay off unless a company turns them on",
        )
        self.assertEqual(self.order._get_report_line_numbers(), {})

    def test_the_order_mirrors_the_company_setting(self):
        self.env.company.show_sol_numbers = True
        self.order.invalidate_recordset(["show_sol_numbers"])
        self.assertTrue(self.order.show_sol_numbers)

    def test_every_reported_line_is_numbered_in_order(self):
        self.env.company.show_sol_numbers = True
        reported = self.order._get_order_lines_to_report()
        numbers = self.order._get_report_line_numbers()
        self.assertEqual(
            [numbers[line.id] for line in reported],
            list(range(1, len(reported) + 1)),
            "sections, subsections, notes and products all take a number, "
            "in the order the document reports them",
        )

    def test_the_numbering_covers_every_kind_of_line(self):
        self.env.company.show_sol_numbers = True
        numbers = self.order._get_report_line_numbers()
        by_display_type = {
            line.display_type or "product": numbers[line.id]
            for line in self.order._get_order_lines_to_report()
        }
        self.assertEqual(
            by_display_type,
            {"line_section": 1, "product": 4, "line_subsection": 3, "line_note": 5},
            "the second product is 4 because the subsection before it took 3",
        )

    def test_the_printed_document_shows_the_numbers(self):
        self.env.company.show_sol_numbers = True
        tree = self._render(self.order)
        printed = [
            cell.text_content().strip()
            for cell in tree.xpath("//td[contains(@name, '_line_no')]")
        ]
        self.assertEqual(
            printed,
            ["1", "2", "3", "4", "5"],
            "the printed order must number the same lines, in the same order",
        )

    def test_the_printed_document_has_no_number_column_when_off(self):
        tree = self._render(self.order)
        self.assertFalse(tree.xpath("//td[contains(@name, '_line_no')]"))
        self.assertFalse(tree.xpath("//th[@name='th_line_no']"))
