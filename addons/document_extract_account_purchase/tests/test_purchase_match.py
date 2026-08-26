import contextlib

from odoo import Command
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.document_extract.tools import FREE, BaseExtractor
from odoo.addons.document_extract.tools import extractors as registry


class _Stub(BaseExtractor):
    name = "po_test_stub"
    doc_types = ("invoice",)
    needs = ("text",)
    cost = FREE
    confidence = 0.9

    def __init__(self, values):
        self._values = values

    def extract(self, source, doc_type, wanted, env=None):
        return dict(self._values) if self._values else None


@contextlib.contextmanager
def _only(extractor):
    saved = dict(registry._EXTRACTORS)
    registry._EXTRACTORS.clear()
    try:
        registry.register_extractor(extractor)
        yield
    finally:
        registry._EXTRACTORS.clear()
        registry._EXTRACTORS.update(saved)


@tagged("post_install", "-at_install")
class TestPurchaseMatchFromExtraction(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create(
            {"name": "Proveedor SA", "vat": "AAA010101AAA"}
        )
        cls.product = cls.env["product.product"].create(
            {"name": "A thing", "standard_price": 100.0, "list_price": 100.0}
        )
        cls.purchase_order = cls.env["purchase.order"].create(
            {
                "partner_id": cls.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": cls.product.id,
                            "product_qty": 1.0,
                            "price_unit": 100.0,
                            "tax_ids": False,
                        }
                    )
                ],
            }
        )
        cls.purchase_order.action_confirm()

    def _bill(self, **values):
        move = self.env["account.move"].create({"move_type": "in_invoice", **values})
        self.env["ir.attachment"].create(
            {
                "name": "bill.txt",
                "res_model": "account.move",
                "res_id": move.id,
                "mimetype": "text/plain",
                "raw": b"a bill with words on it",
            }
        )
        return move

    def _read(self, **overrides):
        values = {
            "vendor_vat": "AAA010101AAA",
            "invoice_date": "2026-01-15",
            "total": 100.0,
        }
        values.update(overrides)
        return values

    def test_it_links_the_order_named_on_the_document(self):
        with _only(_Stub(self._read(purchase_order=self.purchase_order.name))):
            bill = self._bill()

            bill.action_extract_document()

        self.assertIn(bill.id, self.purchase_order.invoice_ids.ids)

    def test_it_leaves_a_bill_that_already_has_lines_alone(self):
        bill = self._bill()
        bill.write(
            {
                "partner_id": self.vendor.id,
                "invoice_line_ids": [
                    Command.create({"name": "typed by a person", "price_unit": 50.0})
                ],
            }
        )

        with _only(_Stub(self._read(purchase_order=self.purchase_order.name))):
            bill.action_extract_document()

        self.assertNotIn(bill.id, self.purchase_order.invoice_ids.ids)

    def test_it_does_nothing_when_the_document_names_no_order(self):
        with _only(_Stub(self._read())):
            bill = self._bill()

            bill.action_extract_document()

        self.assertNotIn(bill.id, self.purchase_order.invoice_ids.ids)
        self.assertEqual(bill.extract_state, "done")

    def test_it_splits_several_references_the_way_invoice_origin_does(self):
        move = self.env["account.move"]
        self.assertEqual(
            move._get_extract_purchase_order_references("P00001, P00002 P00003"),
            ["P00001", "P00002", "P00003"],
        )
        self.assertEqual(move._get_extract_purchase_order_references(None), [])
        self.assertEqual(move._get_extract_purchase_order_references(""), [])
