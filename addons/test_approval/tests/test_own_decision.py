import importlib.util
from datetime import timedelta
from pathlib import Path

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import new_test_user, tagged

from odoo.addons.approval.tests.common import ApprovalCommon


def _approval_migration(version):
    path = Path(__file__).parents[2] / "approval" / "migrations" / version
    spec = importlib.util.spec_from_file_location("migration", path / "post-migrate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.migrate


@tagged("post_install", "-at_install")
class TestOwnDecision(ApprovalCommon):
    """Nobody decides a request made by them or for them, bar a named exception.

    Whoever asked, and whom the document names as its requester, are left off the
    request's steps and refused a decision -- also one a delegate takes for their
    own row -- unless the category allows self-approval or an access exception
    names them. An exception is used where it lets a decision through, and a
    lapsed one lets nothing through.
    """

    def setUp(self):
        super().setUp()
        self.category = self._make_category(
            name=f"Own Decision {self.id()}",
            approvers=[
                (self.owner_user, False, 10),
                (self.approver_1, False, 20),
                (self.approver_2, False, 30),
            ],
            approval_minimum=1,
        )

    def _gated(self, user=None):
        return self.env["approval.test.gated"].create(
            {
                "name": "Own Decision Gated",
                "partner_id": self.partner.id,
                "amount_total": 100.0,
                "test_category_id": self.category.id,
                "user_id": (user or self.env["res.users"]).id,
            }
        )

    def _exception(self, user, kind, **vals):
        return (
            self.env["ir.access.exception"]
            .sudo()
            .create(
                {
                    "user_id": user.id,
                    "kind": kind,
                    "res_model": "approval.category",
                    "res_id": self.category.id,
                    "reason": "Covering while the category is reviewed",
                    "reviewer_ids": [(6, 0, self.manager_user.ids)],
                    "date_to": fields.Datetime.now() + timedelta(days=30),
                    **vals,
                }
            )
        )

    def _row(self, request, user):
        return request.approver_ids.filtered(lambda row: row.user_id == user)

    def _uses(self, exception):
        return self.env["ir.access.log"].search_count(
            [
                ("event", "=", "exception_used"),
                ("cause_model", "=", "ir.access.exception"),
                ("cause_res_id", "=", exception.id),
            ]
        )

    def test_the_declared_requester_is_not_asked(self):
        document = self._gated(user=self.approver_1)
        document.with_user(self.owner_user).sudo().action_create_approval_request()
        request = document.approval_request_id
        self.assertEqual(request.requester_id, self.approver_1)
        self.assertFalse(self._row(request, self.approver_1))
        self.assertFalse(self._row(request, self.owner_user))

    def test_an_exception_lets_the_declared_requester_decide_and_is_logged(self):
        exception = self._exception(self.approver_1, "requester_exclusion")
        document = self._gated(user=self.approver_1)
        document.with_user(self.owner_user).sudo().action_create_approval_request()
        request = document.approval_request_id
        row = self._row(request, self.approver_1)
        self.assertTrue(row)
        request.with_user(self.approver_1).action_approve(row)
        self.assertEqual(request.state, "approved")
        self.assertEqual(self._uses(exception), 1)
        self.assertEqual(exception.use_count, 1)

    def test_a_delegate_deciding_the_owners_own_row_is_refused(self):
        self.category.allow_self_approval = True
        request = self._prepare_request(self.category)
        row = self._row(request, self.owner_user)
        self.assertTrue(row, "allowed, the owner is asked")
        self.category.allow_self_approval = False
        delegate = new_test_user(
            self.env, login="own_decision_delegate", groups="base.group_user"
        )
        self._delegate_row(row, delegate)
        with self.assertRaises(AccessError):
            request.with_user(delegate).action_approve(row)

    def test_an_exception_lets_the_owner_decide_and_a_lapsed_one_does_not(self):
        exception = self._exception(self.owner_user, "self_approval")
        request = self._prepare_request(self.category)
        row = self._row(request, self.owner_user)
        self.assertTrue(row, "the exception keeps the owner on the step")
        exception.sudo().write(
            {
                "date_from": fields.Datetime.now() - timedelta(days=60),
                "date_to": fields.Datetime.now() - timedelta(days=1),
            }
        )
        with self.assertRaises(AccessError):
            request.with_user(self.owner_user).action_approve(row)
        self.assertEqual(self._uses(exception), 0)

    def test_nobody_may_delegate_to_the_declared_requester(self):
        buyer = new_test_user(
            self.env, login="own_decision_buyer", groups="base.group_user"
        )
        document = self._gated(user=buyer)
        document.with_user(self.owner_user).sudo().action_create_approval_request()
        row = self._row(document.approval_request_id, self.approver_1)
        with self.assertRaises(ValidationError):
            self._delegate_row(row, buyer)

    def test_the_upgrade_turns_self_approval_off_and_keeps_who_relied_on_it(self):
        self.category.allow_self_approval = True
        alone = self._prepare_request(self.category)
        alone.with_user(self.owner_user).action_approve(
            self._row(alone, self.owner_user)
        )
        self.assertEqual(alone.state, "approved")
        archived = self._make_category(
            name=f"Archived {self.id()}",
            approvers=[(self.owner_user, False, 10)],
            allow_self_approval=True,
        )
        old = self._prepare_request(archived)
        old.with_user(self.owner_user).action_approve(self._row(old, self.owner_user))
        archived.active = False

        _approval_migration("2.13")(self.env.cr, "19.0.2.12.0")

        self.env.invalidate_all()
        self.assertFalse(self.category.allow_self_approval)
        self.assertFalse(archived.allow_self_approval)
        Exceptions = self.env["ir.access.exception"].sudo()
        kept = Exceptions.search(
            [("user_id", "=", self.owner_user.id), ("kind", "=", "self_approval")]
        )
        self.assertEqual(kept.mapped("res_id"), [self.category.id])
        self.assertEqual(kept.state, "active")
        self.assertAlmostEqual((kept.date_to - fields.Datetime.now()).days, 89, delta=1)
        self.assertNotIn(self.owner_user, kept.reviewer_ids)

    def test_the_upgrade_keeps_a_requester_who_approved_on_their_behalf(self):
        self.category.allow_self_approval = True
        document = self._gated(user=self.approver_1)
        document.with_user(self.owner_user).sudo().action_create_approval_request()
        request = document.approval_request_id
        request.with_user(self.approver_1).action_approve(
            self._row(request, self.approver_1)
        )
        self.env["approval.request"]._upgrade_declared_requester(
            "approval.test.gated", "user_id"
        )
        kept = (
            self.env["ir.access.exception"]
            .sudo()
            .search(
                [
                    ("user_id", "=", self.approver_1.id),
                    ("kind", "=", "requester_exclusion"),
                ]
            )
        )
        self.assertEqual(kept.mapped("res_id"), [self.category.id])
