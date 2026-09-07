from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMainChannelsPickTheRightRecord(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Main Channels"})

    def _number(self, number, phone_type, **extra):
        return self.env["phone.number"].create(
            {"number": number, "type": phone_type, **extra}
        )

    def test_the_main_phone_is_the_first_landline_and_the_mobile_the_first_mobile(self):
        far = self._number("+52 55 1111 1111", "landline", sequence=20)
        near = self._number("+52 55 2222 2222", "landline", sequence=5)
        mobile = self._number("+52 55 3333 3333", "mobile")
        fax = self._number("+52 55 4444 4444", "fax")
        self.partner.phone_ids = far + near + mobile + fax

        self.assertEqual(self.partner.main_phone_id, near)
        self.assertEqual(self.partner.main_mobile_id, mobile)

    def test_the_order_holds_without_an_intervening_invalidation(self):
        far = self._number("+52 55 1111 1111", "landline", sequence=20)
        near = self._number("+52 55 2222 2222", "landline", sequence=5)
        self.partner.phone_ids = far + near

        self.assertEqual(self.partner.main_phone_id, near)

        self.env.invalidate_all()
        self.assertEqual(self.partner.main_phone_id, near)

    def test_primary_outranks_sequence(self):
        first = self._number("+52 55 1111 1111", "landline", sequence=5)
        marked = self._number("+52 55 2222 2222", "landline", sequence=20)
        self.partner.phone_ids = first + marked
        self.assertEqual(self.partner.main_phone_id, first)

        marked.primary = True
        self.assertEqual(self.partner.main_phone_id, marked)

    def test_an_archived_number_is_not_the_main_one(self):
        kept = self._number("+52 55 1111 1111", "landline", sequence=20)
        archived = self._number("+52 55 2222 2222", "landline", sequence=5)
        self.partner.phone_ids = kept + archived
        self.assertEqual(self.partner.main_phone_id, archived)

        archived.active = False
        self.assertEqual(self.partner.main_phone_id, kept)

    def test_a_contact_with_no_number_of_that_type_has_no_main_one(self):
        self.partner.phone_ids = self._number("+52 55 3333 3333", "mobile")
        self.assertFalse(self.partner.main_phone_id)
        self.assertEqual(self.partner.main_mobile_id.number, "+52 55 3333 3333")

    def test_the_main_bank_account_is_the_first_active_one(self):
        Bank = self.env["res.partner.bank"]
        far = Bank.create(
            {"acc_number": "MAIN-1", "partner_id": self.partner.id, "sequence": 20}
        )
        near = Bank.create(
            {"acc_number": "MAIN-2", "partner_id": self.partner.id, "sequence": 5}
        )
        self.assertEqual(self.partner.main_bank_id, near)

        near.active = False
        self.assertEqual(self.partner.main_bank_id, far)

    def test_they_are_stored_so_a_domain_and_a_group_by_reach_them(self):
        mobile = self._number("+52 55 3333 3333", "mobile")
        self.partner.phone_ids = mobile
        self.env["res.partner.bank"].create(
            {"acc_number": "MAIN-3", "partner_id": self.partner.id}
        )
        self.env.flush_all()

        Partner = self.env["res.partner"]
        self.assertEqual(
            Partner.search([("main_mobile_id", "=", mobile.id)]), self.partner
        )
        grouped = Partner._read_group(
            [("id", "=", self.partner.id)], ["main_bank_id"], ["__count"]
        )
        self.assertEqual(grouped[0][0], self.partner.main_bank_id)
