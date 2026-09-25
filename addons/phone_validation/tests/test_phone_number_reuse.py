from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPhoneNumberReuse(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.romania = cls.env.ref("base.ro")
        cls.first = cls.env["res.partner"].create(
            {
                "name": "Bucharest office",
                "country_id": cls.romania.id,
                "phone_ids": [Command.create({"number": "(021) 209.99.99"})],
            }
        )

    def test_a_local_number_added_to_a_second_contact_reuses_the_first(self):
        second = self.env["res.partner"].create(
            {"name": "Bucharest branch", "country_id": self.romania.id}
        )
        second.phone_ids = [Command.create({"number": "(021) 209.99.99"})]
        self.env.flush_all()
        self.assertEqual(second.phone_ids, self.first.phone_ids)
        self.assertEqual(second.phone_ids.sanitized, "+40212099999")
        self.assertEqual(
            self.env["phone.number"].search_count([("sanitized", "=", "+40212099999")]),
            1,
        )

    def test_a_contact_rewriting_its_own_number_keeps_one_row(self):
        self.first.write({"phone_ids": [Command.create({"number": "(021) 209.99.99"})]})
        self.env.flush_all()
        self.assertEqual(len(self.first.phone_ids), 1)

    def test_a_bank_reuses_its_partners_number_through_the_inherited_field(self):
        bank = self.env["res.bank"].create(
            {"name": "Alpha Bank", "country_id": self.romania.id}
        )
        bank.write({"phone_ids": [Command.create({"number": "(021) 209.99.99"})]})
        self.env.flush_all()
        self.assertEqual(bank.phone_ids, self.first.phone_ids)
        self.assertIn(bank.partner_id, bank.phone_ids.partner_ids)
