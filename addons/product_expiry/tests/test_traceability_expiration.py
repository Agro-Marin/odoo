from datetime import datetime

from lxml import etree

from odoo.tests import tagged
from odoo.tools import format_date

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestTraceabilityExpirationDate(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env["stock.traceability.report"]
        cls.tracked = cls.env["product.product"].create(
            {
                "name": "Traced Yoghurt",
                "is_storable": True,
                "tracking": "lot",
                "use_expiration_date": True,
            }
        )
        cls.lot = cls.env["stock.lot"].create(
            {
                "name": "LOT-EXP-TRC",
                "product_id": cls.tracked.id,
                "expiration_date": datetime(2026, 12, 31, 10, 0, 0),
            }
        )

    def _done_move_line(self, src, dst, date):
        move = self.env["stock.move"].create(
            {
                "product_id": self.tracked.id,
                "product_uom_qty": 5,
                "location_id": src.id,
                "location_dest_id": dst.id,
            }
        )
        line = self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "product_id": self.tracked.id,
                "lot_id": self.lot.id,
                "location_id": src.id,
                "location_dest_id": dst.id,
                "quantity": 5,
            }
        )
        move.state = "done"
        line.date = date
        return line

    def _create_move_line_chain(self):
        return (
            self._done_move_line(
                self.supplier_location, self.stock_location, datetime(2026, 1, 1)
            ),
            self._done_move_line(
                self.stock_location, self.shelf_1, datetime(2026, 2, 1)
            ),
        )

    @property
    def _formatted(self):
        return format_date(self.env, self.lot.expiration_date)

    def test_web_lines_carry_the_expiration_date_after_the_lot(self):
        self._create_move_line_chain()
        lines = self.report.with_context(
            active_id=self.lot.id, model="stock.lot"
        ).get_lines()
        self.assertTrue(lines, "the lot has done move lines to report")
        for line in lines:
            self.assertEqual(
                len(line["columns"]),
                8,
                "the expiration date is a column of its own",
            )
            self.assertEqual(line["columns"][3], self.lot.name)
            self.assertEqual(line["columns"][4], self._formatted)
            self.assertEqual(line["expiration_date"], self.lot.expiration_date)

    def _print_payload(self):
        """The payload the client action posts back when printing."""
        return [
            {
                "id": line["id"],
                "model_id": line["model_id"],
                "model_name": line["model"],
                "unfoldable": line["unfoldable"],
                "level": line["level"],
            }
            for line in self.report.with_context(
                active_id=self.lot.id, model="stock.lot"
            ).get_lines()
        ]

    def test_pdf_lines_carry_the_expiration_date_after_the_lot(self):
        self._create_move_line_chain()
        lines = self.report.get_pdf_lines(self._print_payload())
        self.assertTrue(lines)
        for line in lines:
            self.assertEqual(len(line["columns"]), 8)
            self.assertEqual(line["columns"][4], self._formatted)

    def test_a_lot_without_expiration_date_keeps_the_column_empty(self):
        plain = self.env["product.product"].create(
            {"name": "Traced Bolt", "is_storable": True, "tracking": "lot"}
        )
        lot = self.env["stock.lot"].create(
            {"name": "LOT-NO-EXP", "product_id": plain.id}
        )
        move = self.env["stock.move"].create(
            {
                "product_id": plain.id,
                "product_uom_qty": 1,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
            }
        )
        self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "product_id": plain.id,
                "lot_id": lot.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "quantity": 1,
            }
        )
        move.state = "done"
        lines = self.report.with_context(
            active_id=lot.id, model="stock.lot"
        ).get_lines()
        self.assertTrue(lines)
        for line in lines:
            self.assertEqual(
                len(line["columns"]),
                8,
                "every row keeps the same width or the table misaligns",
            )
            self.assertEqual(line["columns"][4], "")

    def test_pdf_template_heads_and_fills_the_new_column(self):
        self._create_move_line_chain()
        lines = self.report.get_pdf_lines(self._print_payload())
        html = self.env["ir.qweb"]._render(
            "stock.report_stock_body_print",
            {"lines": lines, "reference": self.lot.name},
        )
        tree = etree.fromstring(f"<root>{html}</root>")
        headers = [th.text.strip() for th in tree.xpath("//thead/tr/th") if th.text]
        self.assertIn("Expiration Date", headers)
        self.assertEqual(headers.index("Expiration Date"), 4)
        for row in tree.xpath("//tbody/tr"):
            self.assertEqual(
                len(row.xpath("./td")),
                len(headers),
                "every printed row must be as wide as the header",
            )
        self.assertIn(self._formatted, html)
