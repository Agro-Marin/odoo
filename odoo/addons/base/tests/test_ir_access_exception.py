from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestIrAccessException(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.subject = new_test_user(
            cls.env, login="exception_subject", groups="base.group_user"
        )
        cls.admin_a = new_test_user(
            cls.env, login="exception_admin_a", groups="base.group_erp_manager"
        )
        cls.admin_b = new_test_user(
            cls.env, login="exception_admin_b", groups="base.group_erp_manager"
        )
        cls.scope = cls.env.ref("base.group_user")

    def _create(self, user=None, env_user=None, **vals):
        Exceptions = self.env["ir.access.exception"]
        if env_user:
            Exceptions = Exceptions.with_user(env_user)
        return Exceptions.create(
            {
                "user_id": (user or self.subject).id,
                "kind": "sod",
                "res_model": self.scope._name,
                "res_id": self.scope.id,
                "reason": "Covering the month end",
                "date_to": fields.Datetime.now() + timedelta(days=10),
                **vals,
            }
        )

    def test_the_reviewers_default_to_the_administrators_but_the_subject(self):
        exception = self._create(user=self.admin_a, env_user=self.admin_b)
        self.assertIn(self.admin_b, exception.reviewer_ids)
        self.assertNotIn(self.admin_a, exception.reviewer_ids)

    def test_the_subject_never_reviews_their_own_exception(self):
        with self.assertRaises(ValidationError):
            self._create(reviewer_ids=[(6, 0, self.subject.ids)])

    def test_nobody_grants_or_extends_their_own_exception(self):
        with self.assertRaises(UserError):
            self._create(user=self.admin_a, env_user=self.admin_a)
        exception = self._create(user=self.admin_a, env_user=self.admin_b)
        with self.assertRaises(UserError):
            exception.with_user(self.admin_a).date_to = fields.Datetime.now() + (
                timedelta(days=400)
            )

    def test_it_is_found_while_live_and_not_once_lapsed_or_revoked(self):
        exception = self._create(env_user=self.admin_a)
        Exceptions = self.env["ir.access.exception"]
        self.assertEqual(Exceptions._find(self.subject, "sod", self.scope), exception)
        exception.write(
            {
                "date_from": fields.Datetime.now() - timedelta(days=20),
                "date_to": fields.Datetime.now() - timedelta(seconds=1),
            }
        )
        self.assertEqual(exception.state, "lapsed")
        self.assertFalse(Exceptions._find(self.subject, "sod", self.scope))
        other = self._create(env_user=self.admin_a)
        other.with_user(self.admin_b).action_revoke("no longer needed")
        self.assertEqual(other.state, "revoked")
        self.assertFalse(Exceptions._find(self.subject, "sod", self.scope))

    def test_each_use_is_logged_and_counted(self):
        exception = self._create(env_user=self.admin_a)
        exception._record_use("first")
        exception._record_use("second")
        exception.invalidate_recordset(["use_count", "last_used"])
        self.assertEqual(exception.use_count, 2)
        self.assertTrue(exception.last_used)
        events = (
            self.env["ir.access.log"]
            .search(
                [
                    ("cause_res_id", "=", exception.id),
                    ("cause_model", "=", exception._name),
                ]
            )
            .mapped("event")
        )
        self.assertEqual(
            sorted(events), ["exception_created", "exception_used", "exception_used"]
        )

    def test_an_exception_is_revoked_never_deleted(self):
        exception = self._create(env_user=self.admin_a)
        with self.assertRaises(UserError):
            exception.with_user(self.admin_b).unlink()
