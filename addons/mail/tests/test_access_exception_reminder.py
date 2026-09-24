from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestAccessExceptionReminder(TransactionCase):
    def test_reviewers_are_reminded_once_before_an_exception_lapses(self):
        subject = new_test_user(self.env, login="reminded_subject")
        reviewer = new_test_user(
            self.env, login="reminded_reviewer", groups="base.group_erp_manager"
        )
        Exceptions = self.env["ir.access.exception"].sudo()
        values = {
            "user_id": subject.id,
            "kind": "sod",
            "res_model": "res.groups",
            "res_id": self.env.ref("base.group_user").id,
            "reason": "Covering the month end",
            "reviewer_ids": [(6, 0, reviewer.ids)],
        }
        lapsing = Exceptions.create(
            {**values, "date_to": fields.Datetime.now() + timedelta(days=3)}
        )
        distant = Exceptions.create(
            {**values, "date_to": fields.Datetime.now() + timedelta(days=60)}
        )
        Exceptions._cron_remind_lapsing()
        Exceptions._cron_remind_lapsing()
        self.assertEqual(lapsing.activity_ids.user_id, reviewer)
        self.assertEqual(len(lapsing.activity_ids), 1)
        self.assertFalse(distant.activity_ids)
