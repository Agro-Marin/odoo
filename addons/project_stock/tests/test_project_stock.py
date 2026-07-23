# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProjectStock(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Customer"})
        cls.project = cls.env["project.project"].create(
            {"name": "Build", "partner_id": cls.partner.id}
        )

    def test_open_deliveries_targets_outgoing_pickings(self):
        """The deliveries button restricts to outgoing pickings for the project."""
        action = self.project.action_open_deliveries()
        self.assertEqual(action["res_model"], "stock.picking")
        self.assertEqual(action["context"]["default_project_id"], self.project.id)
        self.assertEqual(action["context"]["restricted_picking_type_code"], "outgoing")
        self.assertEqual(action["context"]["default_partner_id"], self.partner.id)
        self.assertNotIn("activity", action["view_mode"])

    def test_open_receipts_targets_incoming_pickings(self):
        """The receipts button restricts to incoming pickings with an activity view."""
        action = self.project.action_open_receipts()
        self.assertEqual(action["context"]["restricted_picking_type_code"], "incoming")
        self.assertNotIn("default_partner_id", action["context"])
        self.assertIn("activity", action["view_mode"])

    def test_open_all_pickings_is_unrestricted(self):
        """The all-moves button keeps the project filter without a type restriction."""
        action = self.project.action_open_all_pickings()
        self.assertEqual(action["context"]["default_project_id"], self.project.id)
        self.assertNotIn("restricted_picking_type_code", action["context"])
        self.assertIn("activity", action["view_mode"])
