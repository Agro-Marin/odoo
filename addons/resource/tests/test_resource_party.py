from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResourceParty(TransactionCase):
    """A human resource follows its party's name and timezone; a material one
    keeps its own."""

    def test_a_resource_with_a_party_reads_the_party(self):
        partner = self.env["res.partner"].create(
            {"name": "Party One", "tz": "Asia/Tokyo"}
        )
        resource = self.env["resource.resource"].create(
            {"name": "ignored", "partner_id": partner.id}
        )
        self.assertEqual(resource.name, "Party One")
        self.assertEqual(resource.tz, "Asia/Tokyo")
        partner.write({"name": "Party Renamed", "tz": "Europe/Paris"})
        self.assertEqual(resource.name, "Party Renamed")
        self.assertEqual(resource.tz, "Europe/Paris")

    def test_writing_the_resource_writes_the_party(self):
        partner = self.env["res.partner"].create({"name": "Party Two", "tz": "UTC"})
        resource = self.env["resource.resource"].create({"partner_id": partner.id})
        resource.write({"name": "Party Two Edited", "tz": "America/Lima"})
        self.assertEqual(partner.name, "Party Two Edited")
        self.assertEqual(partner.tz, "America/Lima")

    def test_a_material_resource_keeps_its_own(self):
        resource = self.env["resource.resource"].create(
            {"name": "Lathe", "resource_type": "material", "tz": "Europe/Brussels"}
        )
        resource.name = "Lathe 2"
        self.assertEqual(resource.name, "Lathe 2")
        self.assertEqual(resource.tz, "Europe/Brussels")
        self.assertFalse(resource.partner_id)

    def test_a_party_without_timezone_leaves_the_resource_its_own(self):
        partner = self.env["res.partner"].create({"name": "No TZ"})
        partner.tz = False
        resource = self.env["resource.resource"].create(
            {"partner_id": partner.id, "tz": "Pacific/Apia"}
        )
        self.assertEqual(resource.tz, "Pacific/Apia")
