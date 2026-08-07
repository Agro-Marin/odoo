from psycopg import IntegrityError

from odoo.tools import mute_logger

from odoo.addons.base.tests.common import SavepointCaseWithUserDemo


class TestResPartnerBank(SavepointCaseWithUserDemo):
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

        sanitized_acc_number = "BE001251882303"
        self.assertEqual(partner_bank.sanitized_acc_number, sanitized_acc_number)
        vals = partner_bank_model.search([("acc_number", "=", sanitized_acc_number)])
        self.assertEqual(1, len(vals))
        self.assertEqual(partner_bank, vals[0])
        vals = partner_bank_model.search([("acc_number", "in", [sanitized_acc_number])])
        self.assertEqual(1, len(vals))
        self.assertEqual(partner_bank, vals[0])
        self.assertEqual(partner_bank.sanitized_acc_number, sanitized_acc_number)

        vals = partner_bank_model.search(
            [("acc_number", "=", sanitized_acc_number.lower())]
        )
        self.assertEqual(1, len(vals))
        vals = partner_bank_model.search([("acc_number", "=", acc_number.lower())])
        self.assertEqual(1, len(vals))

        partner_bank.write({"sanitized_acc_number": "BE001251882303WRONG"})
        self.assertEqual(partner_bank.acc_number, partner_bank.sanitized_acc_number)

    def test_acc_holder_name_follows_partner_rename_when_not_customized(self):
        partner = self.env["res.partner"].create({"name": "Old Name"})
        bank = self.env["res.partner.bank"].create(
            {"acc_number": "BE001 2518823 03", "partner_id": partner.id}
        )
        self.assertEqual(bank.acc_holder_name, "Old Name")
        partner.write({"name": "New Name"})
        self.assertEqual(bank.acc_holder_name, "New Name")

    def test_acc_holder_name_customization_survives_partner_rename(self):
        partner = self.env["res.partner"].create({"name": "Old Name"})
        bank = self.env["res.partner.bank"].create(
            {"acc_number": "BE001 2518823 03", "partner_id": partner.id}
        )
        bank.acc_holder_name = "Custom Holder"
        partner.write({"name": "New Name"})
        self.assertEqual(bank.acc_holder_name, "Custom Holder")

    def test_acc_holder_name_recomputed_on_partner_change(self):
        partner_a = self.env["res.partner"].create({"name": "Holder A"})
        partner_b = self.env["res.partner"].create({"name": "Holder B"})
        bank = self.env["res.partner.bank"].create(
            {"acc_number": "BE001 2518823 03", "partner_id": partner_a.id}
        )
        bank.partner_id = partner_b
        self.assertEqual(bank.acc_holder_name, "Holder B")

    def test_bank_bic_uppercased_on_create_and_write(self):
        bank = self.env["res.bank"].create({"name": "Bic Bank", "bic": "gebabebb"})
        self.assertEqual(bank.bic, "GEBABEBB")
        bank.write({"bic": "bbrubebb"})
        self.assertEqual(bank.bic, "BBRUBEBB")

    def test_acc_type_selection_uses_private_hook(self):
        selection = (
            self.env["res.partner.bank"]._fields["acc_type"].get_values(self.env)
        )
        self.assertIn("bank", selection)

    def test_unlink_archives_instead_of_deleting(self):
        partner = self.env["res.partner"].create({"name": "Pepper Test"})
        partner_bank = self.env["res.partner.bank"].create(
            {"acc_number": "BE001 2518823 03", "partner_id": partner.id}
        )
        partner_bank.unlink()
        self.assertTrue(partner_bank.exists())
        self.assertFalse(partner_bank.active)

    @mute_logger("odoo.db")
    def test_unique_constraint_counts_archived_rows(self):
        partner = self.env["res.partner"].create({"name": "Pepper Test"})
        partner_bank = self.env["res.partner.bank"].create(
            {"acc_number": "BE001 2518823 03", "partner_id": partner.id}
        )
        partner_bank.unlink()
        self.assertFalse(partner_bank.active)
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.env["res.partner.bank"].create(
                {"acc_number": "BE0012518823 03", "partner_id": partner.id}
            )
            self.env["res.partner.bank"].flush_model()
