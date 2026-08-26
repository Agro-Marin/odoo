from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .common import only as _only
from odoo.addons.document_extract.tools import FREE, BaseExtractor


class _Stub(BaseExtractor):
    name = "bill_test_stub"
    doc_types = ("invoice",)
    needs = ("text",)
    cost = FREE
    confidence = 0.9

    def __init__(self, values):
        self._values = values

    def extract(self, source, doc_type, wanted, env=None):
        return dict(self._values) if self._values else None


@tagged("post_install", "-at_install")
class TestBillExtraction(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create(
            {"name": "Proveedor SA", "vat": "AAA010101AAA"}
        )

    def _bill(self, move_type="in_invoice", **values):
        move = self.env["account.move"].create({"move_type": move_type, **values})
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

    _FULL = {
        "vendor_vat": "AAA010101AAA",
        "invoice_date": "2026-01-15",
        "due_date": "2026-02-15",
        "invoice_number": "A1",
        "currency": "MXN",
        "total": 1160.0,
    }

    def test_it_fills_the_header_from_the_document(self):
        with _only(_Stub(self._FULL)):
            bill = self._bill()

            bill.action_extract_document()

        self.assertEqual(str(bill.invoice_date), "2026-01-15")
        self.assertEqual(str(bill.invoice_date_due), "2026-02-15")
        self.assertEqual(bill.ref, "A1")
        self.assertEqual(bill.extract_state, "done")

    def test_it_matches_the_supplier_on_the_tax_identifier(self):
        with _only(_Stub(self._FULL)):
            bill = self._bill()

            bill.action_extract_document()

        self.assertEqual(bill.partner_id, self.vendor)

    def test_it_keeps_which_reader_produced_each_value(self):
        with _only(_Stub(self._FULL)):
            bill = self._bill()

            bill.action_extract_document()

        self.assertEqual(bill.extract_result["total"]["source"], "bill_test_stub")

    def test_it_does_not_overwrite_what_a_person_typed(self):
        with _only(_Stub(self._FULL)):
            bill = self._bill(ref="the reference I meant")

            bill.action_extract_document()

        self.assertEqual(bill.ref, "the reference I meant")

    def test_it_does_not_replace_a_supplier_already_chosen(self):
        other = self.env["res.partner"].create({"name": "Someone else"})

        with _only(_Stub(self._FULL)):
            bill = self._bill(partner_id=other.id)

            bill.action_extract_document()

        self.assertEqual(bill.partner_id, other)

    def test_an_unknown_tax_identifier_invents_no_supplier(self):
        before = self.env["res.partner"].search_count([])

        with _only(_Stub({**self._FULL, "vendor_vat": "ZZZ999999ZZZ"})):
            bill = self._bill()

            bill.action_extract_document()

        self.assertFalse(bill.partner_id)
        self.assertEqual(self.env["res.partner"].search_count([]), before)

    def test_a_vendor_with_a_contact_is_still_matched(self):
        self.env["res.partner"].create(
            {"name": "Sucursal Norte", "parent_id": self.vendor.id, "type": "delivery"}
        )

        with _only(_Stub(self._FULL)):
            bill = self._bill()

            bill.action_extract_document()

        self.assertEqual(bill.partner_id, self.vendor)

    def test_two_unrelated_companies_sharing_a_tax_identifier_choose_nobody(self):
        self.env["res.partner"].create(
            {"name": "Otra Empresa SA", "vat": "AAA010101AAA"}
        )

        with _only(_Stub(self._FULL)):
            bill = self._bill()

            bill.action_extract_document()

        self.assertFalse(bill.partner_id)

    def test_an_ambiguous_tax_identifier_chooses_nobody(self):
        self.env["res.partner"].create(
            {"name": "Proveedor SA (duplicate)", "vat": "AAA010101AAA"}
        )

        with _only(_Stub(self._FULL)):
            bill = self._bill()

            bill.action_extract_document()

        self.assertFalse(bill.partner_id)

    def test_it_does_not_replace_a_currency_a_person_chose(self):
        usd = self.env.ref("base.USD")
        usd.active = True

        with _only(_Stub(self._FULL)):
            bill = self._bill()
            bill.currency_id = usd

            bill.action_extract_document()

        self.assertEqual(bill.currency_id, usd)

    def test_it_never_writes_an_archived_currency(self):
        archived = self.env["res.currency"].search([("name", "=", "CHF")], limit=1)
        if not archived:
            archived = (
                self.env["res.currency"]
                .with_context(active_test=False)
                .search([("name", "=", "CHF")], limit=1)
            )
        archived.active = False

        with _only(_Stub({**self._FULL, "currency": "CHF"})):
            bill = self._bill()

            bill.action_extract_document()

        self.assertNotEqual(bill.currency_id, archived)
        self.assertFalse(bill.display_inactive_currency_warning)

    def test_lines_are_reported_and_not_posted(self):
        with _only(
            _Stub(
                {
                    **self._FULL,
                    "lines": [
                        {"description": "Tornillo", "quantity": 2, "unit_price": 300.0}
                    ],
                }
            )
        ):
            bill = self._bill()

            bill.action_extract_document()

        self.assertFalse(bill.invoice_line_ids)
        self.assertEqual(len(bill.extract_result["lines"]["value"]), 1)

    def test_a_customer_invoice_is_refused_in_words(self):
        with _only(_Stub(self._FULL)):
            bill = self._bill(move_type="out_invoice")

            with self.assertRaises(UserError):
                bill.action_extract_document()

    def test_a_document_it_could_only_half_read_says_which_half(self):
        with _only(_Stub({"invoice_date": "2026-01-15"})):
            bill = self._bill()

            bill.action_extract_document()

        self.assertEqual(bill.extract_state, "partial")
        self.assertEqual(bill.extract_missing["fields"], ["total"])

    def test_a_bill_already_read_is_not_offered_for_reading_again(self):
        with _only(_Stub(self._FULL)):
            bill = self._bill()

            bill.action_extract_document()

        self.assertFalse(bill.extract_can_be_read)

    def test_a_bill_read_only_in_part_is_offered_again(self):
        with _only(_Stub({"invoice_date": "2026-01-15"})):
            bill = self._bill()

            bill.action_extract_document()

        self.assertTrue(bill.extract_can_be_read)

    def test_correcting_an_extracted_field_is_recorded(self):
        with _only(_Stub(self._FULL)):
            bill = self._bill()
            bill.action_extract_document()

            bill.write({"ref": "what it actually said"})

        correction = bill.extract_corrections["invoice_number"]
        self.assertEqual(correction["read"], "A1")
        self.assertEqual(correction["corrected_to"], "what it actually said")

    def test_the_printed_due_date_is_used_when_no_term_was_agreed(self):
        with _only(_Stub(self._FULL)):
            bill = self._bill()

            bill.action_extract_document()

        self.assertEqual(str(bill.invoice_date_due), "2026-02-15")

    def test_a_term_from_the_matched_supplier_outranks_a_printed_due_date(self):
        term = self.env["account.payment.term"].create(
            {
                "name": "30 days",
                "company_id": self.env.company.id,
                "line_ids": [
                    (5, 0, 0),
                    (0, 0, {"value": "percent", "value_amount": 100.0, "nb_days": 30}),
                ],
            }
        )
        self.vendor.property_supplier_payment_term_id = term

        with _only(_Stub(self._FULL)):
            bill = self._bill()

            bill.action_extract_document()

        self.assertEqual(bill.partner_id, self.vendor)
        self.assertEqual(bill.invoice_payment_term_id, term)
        self.assertNotEqual(str(bill.invoice_date_due), "2026-02-15")

        # Terms are computed from what the bill owes, so the agreed date only
        # appears once the bill has lines. What matters is that the printed
        # date never displaced the agreement on the way there.
        bill.write(
            {"invoice_line_ids": [(0, 0, {"name": "algo", "price_unit": 1000.0})]}
        )

        self.assertEqual(str(bill.invoice_date_due), "2026-02-14")

    def test_an_agreed_payment_term_outranks_a_printed_due_date(self):
        term = self.env["account.payment.term"].search([], limit=1)
        self.assertTrue(term, "no payment term to test with")

        with _only(_Stub(self._FULL)):
            bill = self._bill(invoice_payment_term_id=term.id)

            bill.action_extract_document()

        self.assertEqual(bill.invoice_payment_term_id, term)
        self.assertNotEqual(str(bill.invoice_date_due), "2026-02-15")
