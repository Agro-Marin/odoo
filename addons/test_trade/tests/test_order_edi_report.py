import io

from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools.pdf import OdooPdfFileReader, OdooPdfFileWriter


@tagged("post_install", "-at_install")
class TestOrderEdiReport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Report = cls.env["ir.actions.report"]
        cls.partner = cls.env["res.partner"].create({"name": "EDI Partner"})
        cls.product = cls.env["product.product"].create(
            {"name": "EDI Product", "type": "consu"},
        )

    def _make_order(self, model):
        return self.env[model].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": 1.0,
                            "price_unit": 5.0,
                        },
                    ),
                ],
            },
        )

    @staticmethod
    def _blank_pdf_stream():
        writer = OdooPdfFileWriter()
        writer.add_blank_page(200, 200)
        stream = io.BytesIO()
        writer.write(stream)
        return stream

    def test_map_contains_sale_reports(self):
        report_map = self.Report._get_order_edi_report_map()
        self.assertEqual(report_map.get("sale.report_saleorder"), "sale.order")
        self.assertEqual(
            report_map.get("sale.report_saleorder_document"),
            "sale.order",
        )
        self.assertEqual(report_map.get("sale.report_saleorder_raw"), "sale.order")

    def test_map_contains_purchase_reports(self):
        report_map = self.Report._get_order_edi_report_map()
        self.assertEqual(
            report_map.get("purchase.report_purchaseorder"),
            "purchase.order",
        )
        self.assertEqual(
            report_map.get("purchase.report_purchasequotation"),
            "purchase.order",
        )

    def test_map_merges_both_modules(self):
        report_map = self.Report._get_order_edi_report_map()
        models = set(report_map.values())
        self.assertIn("sale.order", models)
        self.assertIn("purchase.order", models)

    def test_unmapped_report_is_untouched(self):
        self.assertIsNone(
            self.Report._get_order_edi_report_map().get("account.report_invoice"),
        )

    def _assert_embeds_xml(self, model):
        order = self._make_order(model)
        builders = order._get_edi_builders()
        if not builders:
            self.skipTest(f"no EDI builder installed for {model}")

        stream = self._blank_pdf_stream()
        original_size = len(stream.getvalue())
        collected = {order.id: {"stream": stream}}

        result = self.Report._embed_order_edi_documents(collected, order, builders)

        new_stream = result[order.id]["stream"]
        self.assertIsNot(new_stream, stream, "the stream must be replaced")
        content = new_stream.getvalue()
        self.assertGreater(
            len(content),
            original_size,
            "the embedded XML should make the PDF larger",
        )

        reader = OdooPdfFileReader(io.BytesIO(content), strict=False)
        attachments = dict(reader.get_attachments())
        self.assertTrue(attachments, "the PDF must carry at least one attachment")
        self.assertTrue(
            any(
                content.lstrip().startswith(b"<?xml")
                for content in attachments.values()
            ),
            f"an embedded attachment should be the EDI XML, got {list(attachments)}",
        )

    def test_embed_sale_order(self):
        self._assert_embeds_xml("sale.order")

    def test_embed_purchase_order(self):
        self._assert_embeds_xml("purchase.order")
