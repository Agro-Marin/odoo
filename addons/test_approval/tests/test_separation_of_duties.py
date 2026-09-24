from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestApprovalDuties(ApprovalCommon):
    """Being in an approval step's pool is a duty separation of duties can name."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.payers = cls.env["res.groups"].create({"name": "Duty Payers"})
        Function = cls.env["ir.access.sod.function"]
        cls.rule = cls.env["ir.access.sod.rule"].create(
            {
                "name": "pay and approve",
                "function_a_id": Function.create(
                    {"name": "pay", "group_ids": [Command.link(cls.payers.id)]}
                ).id,
                "function_b_id": Function.create(
                    {"name": "approve", "approves_anything": True}
                ).id,
                "action": "block",
            }
        )
        cls.env["res.users.grant"]._grant(cls.approver_1, cls.payers, cause="manual")
        cls.category = cls._make_category(name="Duties", approvers=[cls.approver_2])

    def test_joining_a_step_s_pool_is_taking_on_its_duty(self):
        with (
            mute_logger("odoo.addons.base.models.ir_access_sod"),
            self.assertRaises(AccessError),
        ):
            self.category.step_ids[:1].member_ids = [
                Command.create({"user_id": self.approver_1.id})
            ]

    def test_an_approver_given_the_other_duty_is_refused(self):
        with (
            mute_logger("odoo.addons.base.models.ir_access_sod"),
            self.assertRaises(AccessError),
        ):
            self.env["res.users.grant"]._grant(
                self.approver_2, self.payers, cause="manual"
            )
