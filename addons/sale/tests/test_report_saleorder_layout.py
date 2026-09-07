import pymupdf

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.sale.tests.common import SaleCommon


@tagged("post_install", "-at_install")
class TestReportSaleOrderLayout(SaleCommon):
    """How the printed order spends the width it has.

    Measured on the rendered PDF, not on the arch: the question is where the
    text lands on the page, and only the layout engine knows that.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The geometry has to be the one our customers get, or the pt figures
        # below measure a page nobody prints.
        cls.env.company.paperformat_id = cls.quick_ref("base.paperformat_euro")
        cls.order = cls.env["sale.order"].create(
            {
                "partner_id": cls.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": cls.product.id,
                            "product_qty": 3.0,
                        },
                    ),
                ],
            },
        )

    def _printed_page(self):
        """The first page of the real PDF.

        `force_report_rendering` is not optional: without it
        `_is_pdf_rendering_enabled` is False under `--test-enable` and
        `_render_qweb_pdf` hands back the HTML, which pymupdf then lays out
        itself on a 400pt page with none of our CSS -- a measurement of
        nothing that still produces plausible numbers.
        """
        pdf, _ = (
            self.env["ir.actions.report"]
            .with_context(force_report_rendering=True)
            ._render_qweb_pdf("sale.action_report_saleorder", self.order.ids)
        )
        return pymupdf.open(stream=pdf, filetype="pdf")[0]

    def _totals_row(self, page):
        """The words of the "Total" row of the totals table, and the page width.

        Located from the label itself so the measurement does not depend on a
        page geometry we would have to keep in sync.
        """
        words = page.get_text("words")
        label = next(w for w in words if w[4] == "Total")
        row = [w for w in words if abs(w[1] - label[1]) < 2]
        return label, row, page.rect.width

    def test_the_totals_table_is_as_wide_as_its_own_numbers(self):
        """It used to be pinned to half the page whatever it held, which left
        the label stranded mid-document, far from the amount it labels."""
        label, _row, width = self._totals_row(self._printed_page())
        self.assertGreater(
            label[0],
            0.6 * width,
            "the totals table still starts at %.2fpt of a %.2fpt page, so it "
            "is sized by the grid instead of by its content" % (label[0], width),
        )

    def test_the_total_label_sits_next_to_its_amount(self):
        """What the customer reads: "Total" and the figure as one line, not two
        ends of a half-page gap."""
        label, row, _width = self._totals_row(self._printed_page())
        amount = max(row, key=lambda w: w[2])
        gap = amount[0] - label[2]
        self.assertLess(
            gap,
            100.0,
            "%.2fpt of white space between the Total label and its amount" % gap,
        )
