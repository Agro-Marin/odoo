import re

from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestPurchaseSections(AccountTestInvoicingCommon):
    """A section's amount must include the lines hanging off its subsections.

    The report and the portal used to carry a running `current_subtotal` that was
    reset on *both* `line_section` and `line_subsection`, so a subsection stole
    its lines from the section above it and the parent printed short.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order = cls.env["purchase.order"].create(
            {
                "partner_id": cls.partner_a.id,
                "line_ids": [
                    Command.create(
                        {"name": "Section A", "display_type": "line_section"},
                    ),
                    Command.create(
                        {
                            "name": "A-1",
                            "product_id": cls.product_a.id,
                            "product_qty": 1,
                            "price_unit": 100.0,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                    Command.create(
                        {"name": "Subsection A.1", "display_type": "line_subsection"},
                    ),
                    Command.create(
                        {
                            "name": "A.1-1",
                            "product_id": cls.product_a.id,
                            "product_qty": 1,
                            "price_unit": 50.0,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                    Command.create(
                        {"name": "Section B", "display_type": "line_section"},
                    ),
                    Command.create(
                        {
                            "name": "B-1",
                            "product_id": cls.product_a.id,
                            "product_qty": 1,
                            "price_unit": 7.0,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                ],
            },
        )
        cls.section_a = cls.order.line_ids[0]
        cls.subsection_a1 = cls.order.line_ids[2]
        cls.section_b = cls.order.line_ids[4]

    def test_section_total_includes_subsection_lines(self):
        self.assertEqual(
            self.section_a._get_section_totals("price_subtotal"),
            150.0,
            "a section owns the lines of its subsections, not only its direct ones",
        )

    def test_subsection_total_is_its_own_lines_only(self):
        self.assertEqual(
            self.subsection_a1._get_section_totals("price_subtotal"),
            50.0,
        )

    def test_section_total_stops_at_the_next_section(self):
        self.assertEqual(self.section_b._get_section_totals("price_subtotal"), 7.0)

    def test_section_lines_exclude_display_lines(self):
        self.assertFalse(
            self.section_a._get_section_lines().filtered("display_type"),
            "a subsection is not one of the lines its parent sums",
        )

    def test_report_prints_the_section_total_on_the_section_row(self):
        html = (
            self.env["ir.actions.report"]
            ._render_qweb_html(
                "purchase.report_purchaseorder",
                self.order.ids,
            )[0]
            .decode()
        )

        self.assertNotIn(
            "Subtotal",
            html,
            "the standalone subtotal rows are replaced by the amount on the section row",
        )
        self.assertRegex(
            re.sub(r"\s+", " ", html),
            r"Section A.*?150\.00",
            "Section A must print 150, not the 100 of its direct line alone",
        )
        self.assertRegex(
            re.sub(r"\s+", " ", html),
            r"Subsection A\.1.*?50\.00",
        )
