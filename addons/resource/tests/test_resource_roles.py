from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestResourceRoles(TransactionCase):
    def setUp(self):
        super().setUp()
        self.roles = self.env["resource.role"].create(
            [
                {"name": "Operator", "sequence": 1},
                {"name": "Supervisor", "sequence": 2},
            ]
        )
        self.resource = self.env["resource.resource"].create(
            {"name": "Shared role holder"}
        )

    def test_default_role_is_a_membership(self):
        self.resource.default_role_id = self.roles[0]
        self.assertEqual(self.resource.role_ids, self.roles[0])
        self.assertEqual(self.roles[0].resource_ids, self.resource)
        self.resource.default_role_id = self.roles[1]
        self.assertEqual(self.resource.role_ids, self.roles)

    def test_removing_default_selects_remaining_role(self):
        self.resource.role_ids = self.roles
        self.assertEqual(self.resource.default_role_id, self.roles[0])
        self.resource.role_ids = self.roles[1]
        self.assertEqual(self.resource.default_role_id, self.roles[1])
        self.resource.role_ids = False
        self.assertFalse(self.resource.default_role_id)

    def test_inverse_membership_updates_default(self):
        self.roles[0].resource_ids = [Command.link(self.resource.id)]
        self.assertEqual(self.resource.role_ids, self.roles[0])
        self.assertEqual(self.resource.default_role_id, self.roles[0])
        self.roles[0].resource_ids = [Command.unlink(self.resource.id)]
        self.assertFalse(self.resource.role_ids)
        self.assertFalse(self.resource.default_role_id)
