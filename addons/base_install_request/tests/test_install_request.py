from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestBaseModuleInstallRequest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Module = cls.env["ir.module.module"]
        cls.installed_module = Module.search([("state", "=", "installed")], limit=1)
        cls.uninstalled_app = Module.search(
            [("state", "=", "uninstalled"), ("application", "=", True)], limit=1
        )

    def test_get_depending_apps_without_module_raises(self):
        """An empty module recordset is rejected by the review wizard."""
        Review = self.env["base.module.install.review"]
        with self.assertRaises(UserError):
            Review._get_depending_apps(self.env["ir.module.module"])

    def test_get_depending_apps_installed_module_raises(self):
        """Requesting the review of an already-installed module is rejected."""
        Review = self.env["base.module.install.review"]
        with self.assertRaises(UserError):
            Review._get_depending_apps(self.installed_module)

    def test_get_depending_apps_includes_target_module(self):
        """The dependency set of an uninstalled app contains the module itself."""
        self.assertTrue(
            self.uninstalled_app, "core-only DB must expose an uninstalled app"
        )
        apps = self.env["base.module.install.review"]._get_depending_apps(
            self.uninstalled_app
        )
        self.assertIn(self.uninstalled_app, apps)
        self.assertTrue(all(record._name == "ir.module.module" for record in apps))

    def test_compute_user_ids_are_system_users(self):
        """The request wizard targets exactly the members of the System group."""
        request = self.env["base.module.install.request"].create(
            {"module_id": self.uninstalled_app.id}
        )
        system_users = self.env.ref("base.group_system").all_user_ids
        self.assertTrue(system_users, "the System group must have at least one member")
        self.assertEqual(set(request.user_ids.ids), set(system_users.ids))

    def test_compute_modules_description_lists_target_module(self):
        """The review wizard lists its target module among the depending apps."""
        review = self.env["base.module.install.review"].create(
            {"module_id": self.uninstalled_app.id}
        )
        self.assertIn(self.uninstalled_app, review.module_ids)
        self.assertTrue(review.modules_description)

    def test_action_view_install_request_wires_default_module(self):
        """The module action opens the request wizard prefilled with the module."""
        action = self.uninstalled_app.action_view_install_request()
        self.assertEqual(action["res_model"], "base.module.install.request")
        self.assertEqual(action["target"], "new")
        self.assertEqual(
            action["context"]["default_module_id"], self.uninstalled_app.id
        )


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
