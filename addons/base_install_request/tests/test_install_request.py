from unittest.mock import patch

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
class TestInstallRequestRecord(TransactionCase):
    """Without the approval engine the request is still a record, and the
    administrators are told by e-mail."""

    def test_sending_records_the_request_and_mails_every_administrator(self):
        if "approval_request_id" in self.env["base.module.install.request"]._fields:
            self.skipTest("approval_base_install_request replaces the e-mail")
        asker = new_test_user(self.env, login="mail_asker", groups="base.group_user")
        module = self.env["ir.module.module"].search(
            [("state", "=", "uninstalled"), ("application", "=", True)], limit=1
        )
        request = (
            self.env["base.module.install.request"]
            .with_user(asker)
            .create({"module_id": module.id, "body_html": "<p>please</p>"})
        )
        sent_to = []
        Template = type(self.env["mail.template"])
        original = Template.send_mail

        def record(template, res_id, *args, **kwargs):
            sent_to.append(template.env.context["partner"])
            return original(template, res_id, *args, **kwargs)

        with patch.object(Template, "send_mail", record):
            request.action_send_request()
        self.assertTrue(request.exists())
        self.assertEqual(
            set(sent_to),
            set(self.env.ref("base.group_system").all_user_ids.partner_id),
            "every administrator is mailed, and nobody else",
        )
