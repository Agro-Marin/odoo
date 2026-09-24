from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.approval.models.approval_utils import ApprovalStepUnstaffed
from odoo.addons.approval.tests.common import ApprovalCommon


@tagged("post_install", "-at_install")
class TestAuthorityWalk(ApprovalCommon):
    """A step walks to the one approver whose authority limit covers the amount.

    A limit qualifies a grant (P2's res.users.grant) for a verb the document
    declares with an amount: approval.test.gated's `ship`, read on
    `amount_total`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.signers = cls.env["res.groups"].create({"name": "Walk Signers"})
        cls.clerk = cls._signer("walk_clerk", 1000.0)
        cls.head = cls._signer("walk_head", 5000.0)
        cls.board = cls._signer("walk_board", 20000.0)
        cls.category = cls.env["approval.category"].create(
            {
                "name": "Walked shipments",
                "approval_minimum": 1,
                "step_ids": [
                    Command.create(
                        {
                            "name": "By limit",
                            "minimum": 1,
                            "group_id": cls.signers.id,
                            "walk": "group_by_limit",
                        }
                    )
                ],
            }
        )

    @classmethod
    def _signer(cls, login, limit):
        user = cls.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "group_ids": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(cls.signers.id),
                ],
            }
        )
        grant = cls.env["res.users.grant"].search(
            [("user_id", "=", user.id), ("group_id", "=", cls.signers.id)]
        )
        cls.env["approval.authority.limit"].create(
            {
                "grant_id": grant.id,
                "model_id": cls.env["ir.model"]._get_id("approval.test.gated"),
                "verb": "ship",
                "amount_max": limit,
                "currency_id": cls.env.company.currency_id.id,
            }
        )
        return user

    def _asked(self, amount, asker=None):
        document = self.env["approval.test.gated"].create(
            {
                "name": f"Walked {amount}",
                "partner_id": self.partner.id,
                "amount_total": amount,
                "test_category_id": self.category.id,
            }
        )
        (document.with_user(asker) if asker else document).action_ship()
        return document.approval_request_id

    def test_the_walk_stops_at_the_lowest_limit_that_covers(self):
        self.assertEqual(self._asked(800.0).approver_ids.user_id, self.clerk)
        self.assertEqual(self._asked(3000.0).approver_ids.user_id, self.head)
        self.assertEqual(self._asked(15000.0).approver_ids.user_id, self.board)

    def test_an_amount_nobody_covers_names_the_highest_limit(self):
        with self.assertRaises(ApprovalStepUnstaffed) as caught:
            self._asked(50000.0)
        self.assertIn("20,000", str(caught.exception))

    def test_a_limit_holds_only_while_its_grant_does(self):
        grant = self.env["res.users.grant"].search(
            [("user_id", "=", self.head.id), ("group_id", "=", self.signers.id)]
        )
        grant.action_revoke()
        self.assertEqual(self._asked(3000.0).approver_ids.user_id, self.board)

    def test_the_walk_passes_over_the_one_who_asks(self):
        self.env["ir.access"].create(
            {
                "name": "approval.test.gated: signers ship",
                "model_id": self.env["ir.model"]._get_id("approval.test.gated"),
                "group_id": self.signers.id,
                "kind": "permission",
                "operation": "ru",
            }
        )
        request = self._asked(3000.0, asker=self.head)
        self.assertEqual(request.approver_ids.user_id, self.board)

    def test_the_document_shows_who_would_approve_before_asking(self):
        document = self.env["approval.test.gated"].create(
            {
                "name": "Previewed",
                "partner_id": self.partner.id,
                "amount_total": 3000.0,
                "test_category_id": self.category.id,
            }
        )
        preview = document._get_approval_chain_preview()
        self.assertEqual([row["user"] for row in preview], [self.head.display_name])
        self.assertFalse(document.approval_request_id, "previewing asks nothing")

    def test_a_limit_names_a_verb_with_an_amount(self):
        grant = self.env["res.users.grant"].search(
            [("user_id", "=", self.clerk.id), ("group_id", "=", self.signers.id)]
        )
        with self.assertRaises(ValidationError):
            self.env["approval.authority.limit"].create(
                {
                    "grant_id": grant.id,
                    "model_id": self.env["ir.model"]._get_id("approval.test.gated"),
                    "verb": "bill",
                    "amount_max": 1.0,
                }
            )

    def test_a_walking_step_decides_alone_and_names_what_it_walks(self):
        step = self.category.step_ids
        with self.assertRaises(ValidationError):
            step.minimum = 2
        with self.assertRaises(ValidationError):
            step.group_id = False
        Request = type(self.env["approval.request"])
        with (
            patch.object(Request, "_supplies_manager_chain", lambda self: False),
            self.assertRaises(ValidationError),
        ):
            step.walk = "manager_chain"

    def test_a_manager_chain_walk_climbs_to_the_first_manager_who_covers(self):
        Request = type(self.env["approval.request"])
        chain = self.clerk | self.head | self.board
        with (
            patch.object(Request, "_supplies_manager_chain", lambda self: True),
            patch.object(Request, "_get_manager_chain", lambda self, user: chain),
        ):
            self.category.step_ids.write({"walk": "manager_chain", "group_id": False})
            self.assertEqual(self._asked(3000.0).approver_ids.user_id, self.head)
            self.assertEqual(self._asked(900.0).approver_ids.user_id, self.clerk)
