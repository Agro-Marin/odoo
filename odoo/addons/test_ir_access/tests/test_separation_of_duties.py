from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestSeparationOfDuties(TransactionCase):
    """Two duties one person must not hold together.

    `pay` is holding the Payers group, `approve` holding the Approvers group or
    the `post` verb of test_ir_access.document (granted to Settings).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Groups = cls.env["res.groups"]
        cls.payers = Groups.create({"name": "SoD Payers"})
        cls.approvers = Groups.create({"name": "SoD Approvers"})
        Function = cls.env["ir.access.sod.function"]
        cls.pay = Function.create(
            {"name": "pay suppliers", "group_ids": [Command.link(cls.payers.id)]}
        )
        cls.approve = Function.create(
            {
                "name": "approve payments",
                "group_ids": [Command.link(cls.approvers.id)],
                "verb_ids": [
                    Command.create(
                        {
                            "model_id": cls.env["ir.model"]._get_id(
                                "test_ir_access.document"
                            ),
                            "verb": "post",
                        }
                    )
                ],
            }
        )
        cls.rule = cls.env["ir.access.sod.rule"].create(
            {
                "name": "pay and approve",
                "function_a_id": cls.pay.id,
                "function_b_id": cls.approve.id,
                "action": "block",
            }
        )
        cls.clerk = new_test_user(cls.env, login="sod_clerk", groups="base.group_user")
        cls.Grant = cls.env["res.users.grant"]

    def _grant(self, group):
        return self.Grant._grant(self.clerk, group, cause="manual")

    def _logged(self, event):
        return self.env["ir.access.log"].search(
            [
                ("event", "=", event),
                ("subject_user_id", "=", self.clerk.id),
                ("cause_model", "=", "ir.access.sod.rule"),
            ]
        )

    def test_a_grant_that_joins_two_duties_is_refused(self):
        self._grant(self.payers)
        with (
            mute_logger("odoo.addons.base.models.ir_access_sod"),
            self.assertRaises(AccessError),
        ):
            self._grant(self.approvers)

    def test_a_verb_is_a_duty_as_much_as_a_group(self):
        self._grant(self.payers)
        with (
            mute_logger("odoo.addons.base.models.ir_access_sod"),
            self.assertRaises(AccessError),
        ):
            self._grant(self.env.ref("base.group_system"))

    def test_an_exception_lets_one_person_hold_both_and_counts_the_use(self):
        self._grant(self.payers)
        exception = self.env["ir.access.exception"].create(
            {
                "user_id": self.clerk.id,
                "kind": "sod",
                "res_model": self.rule._name,
                "res_id": self.rule.id,
                "reason": "two-person company",
                "date_to": fields.Datetime.now() + timedelta(days=30),
            }
        )
        self._grant(self.approvers)
        self.assertEqual(exception.use_count, 1)

    def test_a_warning_rule_logs_the_conflict_and_lets_it_through(self):
        self.rule.action = "warn"
        self._grant(self.payers)
        self.assertFalse(self._logged("sod_conflict"))
        self._grant(self.approvers)
        self.assertEqual(len(self._logged("sod_conflict")), 1)

    def test_a_holder_of_an_excluded_group_does_not_hold_the_duty(self):
        managers = self.env["res.groups"].create({"name": "SoD Pay Managers"})
        self.pay.excluded_group_ids = managers
        self._grant(self.payers | managers)
        self._grant(self.approvers)
        self.assertFalse(self.rule._get_conflicting_user_ids(self.clerk))

    def test_the_report_lists_who_holds_both(self):
        self.rule.action = "warn"
        self._grant(self.payers | self.approvers)
        action = self.env["ir.access.sod.rule"].action_view_conflicts()
        conflicts = self.env["ir.access.sod.conflict"].search(action["domain"])
        self.assertIn(
            (self.rule, self.clerk),
            [(conflict.rule_id, conflict.user_id) for conflict in conflicts],
        )

    def test_an_upgrade_whose_end_stage_never_ran_still_grants_its_exceptions(self):
        self.rule.action = "warn"
        self._grant(self.payers | self.approvers)
        self.rule.action = "block"
        Exception_ = self.env["ir.access.exception"]
        Param = self.env["ir.config_parameter"]
        cron = self.env.ref("base.ir_cron_sod_upgrade_exceptions")

        self.rule._arm_upgrade_exceptions("held both on upgrade day")
        self.assertTrue(cron.active)
        self.assertFalse(Exception_._find(self.clerk, "sod", self.rule))

        self.env["ir.access.sod.rule"]._cron_grant_pending_upgrade_exceptions()
        exception = Exception_._find(self.clerk, "sod", self.rule)
        self.assertEqual(exception.reason, "held both on upgrade day")
        self.assertFalse(cron.active)
        self.assertFalse(Param.get_param("base.sod_pending_upgrade_exceptions"))

    def test_the_end_stage_grants_and_disarms(self):
        self.rule.action = "warn"
        self._grant(self.payers | self.approvers)
        self.rule._arm_upgrade_exceptions("held both on upgrade day")
        self.rule._grant_upgrade_exceptions("held both on upgrade day")
        self.assertTrue(
            self.env["ir.access.exception"]._find(self.clerk, "sod", self.rule)
        )
        self.assertFalse(
            self.env["ir.config_parameter"].get_param(
                "base.sod_pending_upgrade_exceptions"
            )
        )
        self.assertFalse(self.env.ref("base.ir_cron_sod_upgrade_exceptions").active)
