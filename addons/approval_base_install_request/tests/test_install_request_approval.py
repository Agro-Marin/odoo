from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestInstallRequestApproval(TransactionCase):
    """An activation request is an approval request: who asked, who decided, and
    what they said are recorded, where an e-mail to each administrator recorded
    nothing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.asker = new_test_user(
            cls.env, login="install_asker", groups="base.group_user", name="Asker"
        )
        cls.admin = new_test_user(
            cls.env,
            login="install_admin",
            groups="base.group_user,base.group_system",
            name="Admin",
        )
        cls.module = cls.env["ir.module.module"].search(
            [("state", "=", "uninstalled"), ("application", "=", True)], limit=1
        )
        cls.Request = cls.env["base.module.install.request"]

    def _send(self, user=None):
        request = self.Request.with_user(user or self.asker).create(
            {"module_id": self.module.id, "body_html": "<p>For the events team.</p>"}
        )
        request.action_send_request()
        return request

    def _decide(self, request, decision):
        row = request.approval_request_id.approver_ids.filtered(
            lambda approver: approver.user_id == self.admin
        )
        self.assertTrue(row, "the administrator is not asked")
        getattr(
            row.with_user(self.admin).with_context(skip_wizard=True),
            f"action_{decision}",
        )()

    def test_sending_a_request_asks_the_administrators(self):
        request = self._send()
        self.assertEqual(request.approval_state, "pending")
        self.assertIn(self.admin, request.pending_approver_ids)
        self.assertNotIn(self.asker, request.pending_approver_ids)
        self.assertFalse(
            request.pending_approver_ids
            - self.env.ref("base.group_system").all_user_ids,
            "only administrators are asked",
        )

    def test_the_reason_reaches_the_approval_request(self):
        request = self._send()
        self.assertIn("events team", request.approval_request_id.reason or "")

    def test_approving_unlocks_the_install_review(self):
        request = self._send()
        self._decide(request, "approve")
        self.assertEqual(request.approval_state, "approved")
        action = request.with_user(self.admin).action_open_install_review()
        self.assertEqual(action["res_model"], "base.module.install.review")
        self.assertEqual(action["context"]["default_module_id"], self.module.id)

    def test_an_undecided_request_does_not_open_the_install_review(self):
        request = self._send()
        with self.assertRaises(UserError):
            request.with_user(self.admin).action_open_install_review()

    def test_refusing_leaves_the_module_uninstalled(self):
        request = self._send()
        self._decide(request, "refuse")
        self.assertEqual(request.approval_state, "refused")
        self.assertEqual(self.module.state, "uninstalled")

    def test_a_user_sees_only_their_own_requests(self):
        mine = self._send()
        other = new_test_user(
            self.env, login="install_other", groups="base.group_user", name="Other"
        )
        self.assertNotIn(mine, self.Request.with_user(other).search([]))
        self.assertIn(mine, self.Request.with_user(self.admin).search([]))

    def test_what_is_asked_cannot_change_while_it_is_decided(self):
        request = self._send()
        other = self.env["ir.module.module"].search(
            [
                ("state", "=", "uninstalled"),
                ("application", "=", True),
                ("id", "!=", self.module.id),
            ],
            limit=1,
        )
        with self.assertRaises(UserError):
            request.with_user(self.asker).write({"body_html": "<p>changed</p>"})
        if other:
            with self.assertRaises(UserError):
                request.with_user(self.asker).write({"module_id": other.id})
