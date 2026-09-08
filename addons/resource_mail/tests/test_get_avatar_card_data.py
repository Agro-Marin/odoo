from odoo.tests import TransactionCase, tagged


@tagged("at_install", "-post_install")
class TestGetAvatarCardData(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Avatar Card Partner"})
        cls.partner.phone_ids = [(0, 0, {"number": "+15551234567", "type": "mobile"})]
        cls.resource = cls.env["resource.resource"].create(
            {"name": "Avatar Card Resource", "partner_id": cls.partner.id}
        )

    def test_phone_only_request_returns_only_id_and_phone(self):
        data = self.resource.get_avatar_card_data(["phone"])[0]
        self.assertEqual(set(data), {"id", "phone"})
        self.assertEqual(data["phone"], "+15551234567")

    def test_mixed_request_returns_only_requested_fields_plus_id(self):
        data = self.resource.get_avatar_card_data(["name", "phone"])[0]
        self.assertEqual(set(data), {"id", "name", "phone"})
