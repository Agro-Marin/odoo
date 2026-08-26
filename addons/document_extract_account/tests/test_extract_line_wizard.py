from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .common import only as _only
from odoo.addons.document_extract.tools import FREE, BaseExtractor


class _Stub(BaseExtractor):
    name = "wizard_test_stub"
    doc_types = ("invoice",)
    needs = ("text",)
    cost = FREE
    confidence = 0.9

    def __init__(self, values):
        self._values = values

    def extract(self, source, doc_type, wanted, env=None):
        return dict(self._values)


READ = {
    "invoice_date": "2026-01-15",
    "total": 1000.0,
    "lines": [
        {"description": "Tornillo grande", "quantity": 2.0, "unit_price": 300.0},
        {"description": "Tuerca chica", "quantity": 1.0, "unit_price": 400.0},
    ],
}


@tagged("post_install", "-at_install")
class TestExtractLineWizard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Proveedor SA"})

    def _read_bill(self, values=None):
        values = READ if values is None else values
        move = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner.id,
                "invoice_date": "2026-01-15",
            }
        )
        self.env["ir.attachment"].create(
            {
                "name": "bill.txt",
                "res_model": "account.move",
                "res_id": move.id,
                "mimetype": "text/plain",
                "raw": b"a bill with words on it",
            }
        )
        with _only(_Stub(values)):
            move.action_extract_document()
        return move

    def _wizard(self, move):
        action = move.action_review_extracted_lines()
        return self.env["account.move.extract.line.wizard"].browse(action["res_id"])

    def test_reading_a_bill_adds_no_lines_by_itself(self):
        move = self._read_bill()

        self.assertFalse(move.invoice_line_ids)
        self.assertTrue(move.extract_has_lines)

    def test_the_screen_offers_what_the_document_said(self):
        wizard = self._wizard(self._read_bill())

        self.assertEqual(len(wizard.line_ids), 2)
        self.assertEqual(wizard.line_ids[0].description, "Tornillo grande")
        self.assertEqual(wizard.line_ids[0].quantity, 2.0)
        self.assertEqual(wizard.line_ids[0].price_unit, 300.0)
        self.assertEqual(wizard.line_ids[0].read_by, "wizard_test_stub")

    def test_accepting_them_puts_them_on_the_bill(self):
        move = self._read_bill()
        wizard = self._wizard(move)

        wizard.action_apply()

        self.assertEqual(len(move.invoice_line_ids), 2)
        self.assertEqual(move.invoice_line_ids[0].name, "Tornillo grande")
        self.assertEqual(move.invoice_line_ids[0].price_unit, 300.0)

    def test_a_line_refused_is_not_added(self):
        move = self._read_bill()
        wizard = self._wizard(move)
        wizard.line_ids[1].accepted = False

        wizard.action_apply()

        self.assertEqual(len(move.invoice_line_ids), 1)
        self.assertEqual(move.invoice_line_ids[0].name, "Tornillo grande")

    def test_refusing_everything_adds_nothing_and_says_so(self):
        wizard = self._wizard(self._read_bill())
        wizard.line_ids.accepted = False

        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_it_totals_the_accepted_lines_against_the_document(self):
        wizard = self._wizard(self._read_bill())

        self.assertEqual(wizard.read_total, 1000.0)
        self.assertEqual(wizard.proposed_total, 1000.0)
        self.assertTrue(wizard.totals_agree)

    def test_a_taxed_document_agrees_with_its_own_subtotal(self):
        wizard = self._wizard(
            self._read_bill(
                {
                    **READ,
                    "total": 1160.0,
                    "subtotal": 1000.0,
                    "tax_amount": 160.0,
                }
            )
        )

        self.assertEqual(wizard.read_total, 1160.0)
        self.assertEqual(wizard.read_untaxed_total, 1000.0)
        self.assertTrue(wizard.totals_agree)

    def test_a_taxed_document_without_a_subtotal_nets_off_the_tax(self):
        wizard = self._wizard(
            self._read_bill({**READ, "total": 1160.0, "tax_amount": 160.0})
        )

        self.assertEqual(wizard.read_untaxed_total, 1000.0)
        self.assertTrue(wizard.totals_agree)

    def test_the_totals_follow_the_bill_currency(self):
        wizard = self._wizard(self._read_bill())

        self.assertEqual(wizard.currency_id, wizard.move_id.currency_id)
        self.assertEqual(wizard.line_ids[0].currency_id, wizard.move_id.currency_id)

    def test_a_currency_rounding_to_the_unit_tolerates_its_own_rounding(self):
        move = self._read_bill()
        wizard = self._wizard(move)
        rounding = wizard.currency_id.rounding
        wizard.currency_id.rounding = 1.0
        try:
            wizard.line_ids[0].price_unit = 300.4
            wizard.invalidate_recordset()

            self.assertTrue(wizard.totals_agree)
        finally:
            wizard.currency_id.rounding = rounding

    def test_lines_that_do_not_add_up_to_the_document_are_flagged(self):
        wizard = self._wizard(self._read_bill())

        wizard.line_ids[0].price_unit = 1.0

        self.assertFalse(wizard.totals_agree)

    def test_refusing_a_line_shows_in_the_totals(self):
        wizard = self._wizard(self._read_bill())

        wizard.line_ids[1].accepted = False

        self.assertEqual(wizard.proposed_total, 600.0)
        self.assertFalse(wizard.totals_agree)

    def test_a_person_editing_a_line_is_recorded_as_a_correction(self):
        move = self._read_bill()
        wizard = self._wizard(move)
        wizard.line_ids[0].price_unit = 350.0

        wizard.action_apply()

        changes = move.extract_corrections["lines"]["changes"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["read"]["unit_price"], 300.0)
        self.assertEqual(changes[0]["corrected_to"]["unit_price"], 350.0)
        self.assertEqual(
            move.extract_corrections["lines"]["read_by"], "wizard_test_stub"
        )

    def test_a_line_refused_is_recorded_as_refused(self):
        move = self._read_bill()
        wizard = self._wizard(move)
        wizard.line_ids[1].accepted = False

        wizard.action_apply()

        changes = move.extract_corrections["lines"]["changes"]
        self.assertIsNone(changes[0]["corrected_to"])
        self.assertEqual(changes[0]["read"]["description"], "Tuerca chica")

    def test_reordering_the_rows_does_not_misattribute_a_correction(self):
        move = self._read_bill()
        wizard = self._wizard(move)
        wizard.line_ids[0].sequence = 20
        wizard.line_ids[1].sequence = 10
        wizard.invalidate_recordset()
        wizard.line_ids.filtered(
            lambda l: l.description == "Tuerca chica"
        ).price_unit = 450.0

        wizard.action_apply()

        changes = move.extract_corrections["lines"]["changes"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["read"]["description"], "Tuerca chica")
        self.assertEqual(changes[0]["corrected_to"]["unit_price"], 450.0)

    def test_accepting_them_unchanged_records_nothing(self):
        move = self._read_bill()

        self._wizard(move).action_apply()

        self.assertFalse(move.extract_corrections)

    def test_applying_twice_adds_the_lines_only_once(self):
        move = self._read_bill()
        self._wizard(move).action_apply()

        self.assertEqual(len(move.invoice_line_ids), 2)
        self.assertFalse(move.extract_has_lines)

    def test_a_bill_that_took_its_lines_refuses_them_again(self):
        move = self._read_bill()
        wizard = self._wizard(move)
        wizard.action_apply()

        with self.assertRaises(UserError):
            self._wizard(move).action_apply()

        self.assertEqual(len(move.invoice_line_ids), 2)

    def test_reading_the_document_again_offers_the_lines_afresh(self):
        move = self._read_bill()
        self._wizard(move).action_apply()

        with _only(_Stub(READ)):
            move.action_extract_document()

        self.assertTrue(move.extract_has_lines)

    def test_a_line_the_document_did_not_name_records_no_correction(self):
        move = self._read_bill(
            {
                "invoice_date": "2026-01-15",
                "total": 600.0,
                "lines": [{"description": "", "quantity": 2.0, "unit_price": 300.0}],
            }
        )

        self._wizard(move).action_apply()

        self.assertFalse(move.extract_corrections)

    def test_a_quantity_of_zero_is_not_turned_into_one(self):
        move = self._read_bill(
            {
                "invoice_date": "2026-01-15",
                "total": 0.0,
                "lines": [
                    {"description": "Muestra", "quantity": 0, "unit_price": 300.0}
                ],
            }
        )

        self._wizard(move).action_apply()

        self.assertEqual(move.invoice_line_ids[0].quantity, 0.0)
        self.assertFalse(move.extract_corrections)

    def test_a_unit_price_finer_than_the_field_records_no_correction(self):
        move = self._read_bill(
            {
                "invoice_date": "2026-01-15",
                "total": 600.0,
                "lines": [
                    {"description": "Tornillo", "quantity": 2.0, "unit_price": 300.005}
                ],
            }
        )

        self._wizard(move).action_apply()

        self.assertFalse(move.extract_corrections)

    def test_a_second_reading_keeps_what_the_first_pass_recorded(self):
        move = self._read_bill()
        wizard = self._wizard(move)
        wizard.line_ids[0].price_unit = 350.0
        wizard.action_apply()

        with _only(_Stub(READ)):
            move.action_extract_document()
        again = self._wizard(move)
        again.line_ids[1].accepted = False
        again.action_apply()

        changes = move.extract_corrections["lines"]["changes"]
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[0]["corrected_to"]["unit_price"], 350.0)
        self.assertIsNone(changes[1]["corrected_to"])
        self.assertEqual(changes[0]["read_by"], "wizard_test_stub")

    def test_a_posted_bill_takes_no_lines(self):
        move = self._read_bill()
        wizard = self._wizard(move)
        wizard.action_apply()
        move.action_post()

        with self.assertRaises(UserError):
            self._wizard(move).action_apply()

    def test_a_posted_bill_offers_no_review_screen(self):
        move = self._read_bill()
        self._wizard(move).action_apply()
        move.action_post()

        with self.assertRaises(UserError):
            move.action_review_extracted_lines()

    def test_a_bill_whose_document_had_no_lines_offers_no_screen(self):
        move = self._read_bill({"invoice_date": "2026-01-15", "total": 10.0})

        self.assertFalse(move.extract_has_lines)
        with self.assertRaises(UserError):
            move.action_review_extracted_lines()
