# Copyright (c) 2015 ACSONE SA/NV (<http://acsone.eu>)

from psycopg import IntegrityError

from odoo.tools import mute_logger

from odoo.addons.base.tests.common import SavepointCaseWithUserDemo


class TestResPartnerBank(SavepointCaseWithUserDemo):
    """Tests acc_number"""

    def test_sanitized_acc_number(self):
        partner_bank_model = self.env["res.partner.bank"]
        acc_number = " BE-001 2518823 03 "
        vals = partner_bank_model.search([("acc_number", "=", acc_number)])
        self.assertEqual(0, len(vals))
        partner_bank = partner_bank_model.create(
            {
                "acc_number": acc_number,
                "partner_id": self.env["res.partner"]
                .create({"name": "Pepper Test"})
                .id,
                "acc_type": "bank",
            }
        )
        vals = partner_bank_model.search([("acc_number", "=", acc_number)])
        self.assertEqual(1, len(vals))
        self.assertEqual(partner_bank, vals[0])
        vals = partner_bank_model.search([("acc_number", "in", [acc_number])])
        self.assertEqual(1, len(vals))
        self.assertEqual(partner_bank, vals[0])

        self.assertEqual(partner_bank.acc_number, acc_number)

        # sanitaze the acc_number
        sanitized_acc_number = "BE001251882303"
        self.assertEqual(partner_bank.sanitized_acc_number, sanitized_acc_number)
        vals = partner_bank_model.search([("acc_number", "=", sanitized_acc_number)])
        self.assertEqual(1, len(vals))
        self.assertEqual(partner_bank, vals[0])
        vals = partner_bank_model.search([("acc_number", "in", [sanitized_acc_number])])
        self.assertEqual(1, len(vals))
        self.assertEqual(partner_bank, vals[0])
        self.assertEqual(partner_bank.sanitized_acc_number, sanitized_acc_number)

        # search is case insensitive
        vals = partner_bank_model.search(
            [("acc_number", "=", sanitized_acc_number.lower())]
        )
        self.assertEqual(1, len(vals))
        vals = partner_bank_model.search([("acc_number", "=", acc_number.lower())])
        self.assertEqual(1, len(vals))

        # updating the sanitized value will also update the acc_number
        partner_bank.write({"sanitized_acc_number": "BE001251882303WRONG"})
        self.assertEqual(partner_bank.acc_number, partner_bank.sanitized_acc_number)

    def test_unlink_archives_instead_of_deleting(self):
        """unlink() archives the account (active=False) rather than deleting it."""
        partner = self.env["res.partner"].create({"name": "Pepper Test"})
        partner_bank = self.env["res.partner.bank"].create(
            {"acc_number": "BE001 2518823 03", "partner_id": partner.id}
        )
        partner_bank.unlink()
        # The record still exists, only archived.
        self.assertTrue(partner_bank.exists())
        self.assertFalse(partner_bank.active)

    @mute_logger("odoo.db")
    def test_unique_constraint_counts_archived_rows(self):
        """The unique(sanitized_acc_number, partner_id) constraint counts archived rows."""
        partner = self.env["res.partner"].create({"name": "Pepper Test"})
        partner_bank = self.env["res.partner.bank"].create(
            {"acc_number": "BE001 2518823 03", "partner_id": partner.id}
        )
        partner_bank.unlink()
        self.assertFalse(partner_bank.active)
        # Re-creating the same number for the same partner collides with the
        # archived row; base raises the raw constraint violation (the friendly
        # "unarchive it instead" guard lives in the account module).
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.env["res.partner.bank"].create(
                {"acc_number": "BE0012518823 03", "partner_id": partner.id}
            )
            self.env["res.partner.bank"].flush_model()
