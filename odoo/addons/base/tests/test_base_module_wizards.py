from odoo.exceptions import AccessDenied, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestBaseModuleWizards(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Module = self.env["ir.module.module"]
        self.Dependency = self.env["ir.module.module.dependency"]
        self.admin = new_test_user(
            self.env,
            login="wizard_module_admin",
            groups="base.group_system",
        )
        self.plain_user = new_test_user(
            self.env,
            login="wizard_module_plain",
            groups="base.group_user",
        )

    def _make_module(self, name, state, **vals):
        module = self.Module.create(
            dict({"name": name, "shortdesc": name.upper()}, **vals)
        )
        module.state = state
        return module

    def _add_dependency(self, module, dep_name):
        return self.Dependency.create({"module_id": module.id, "name": dep_name})

    @mute_logger("odoo.addons.base.models.ir_module")
    def test_upgrade_module_denies_non_admin(self):
        wizard = self.env["base.module.upgrade"].create({})
        with self.assertRaises(AccessDenied):
            wizard.with_user(self.plain_user).upgrade_module()

    def test_upgrade_module_allows_admin_until_apply(self):
        mod = self._make_module("wizard_upg_root", "to install")
        self._add_dependency(mod, "wizard_upg_missing_dep")

        wizard = self.env["base.module.upgrade"].create({})
        with self.assertRaises(UserError) as ctx:
            wizard.with_user(self.admin).upgrade_module()
        self.assertIn("wizard_upg_missing_dep", str(ctx.exception))

    def test_upgrade_module_cancel_reverts_schedule(self):
        to_upgrade = self._make_module("wizard_cancel_upg", "to upgrade")
        to_remove = self._make_module("wizard_cancel_rem", "to remove")
        to_install = self._make_module("wizard_cancel_ins", "to install")

        wizard = self.env["base.module.upgrade"].create({})
        wizard.with_user(self.admin).upgrade_module_cancel()

        self.assertEqual(to_upgrade.state, "installed")
        self.assertEqual(to_remove.state, "installed")
        self.assertEqual(to_install.state, "uninstalled")

    def test_uninstall_actual_set_covers_hidden_dependent(self):
        root = self._make_module("wizard_uninst_root", "installed", application=True)
        tech_dep = self._make_module(
            "wizard_uninst_tech", "installed", application=False
        )
        self._add_dependency(tech_dep, "wizard_uninst_root")

        wizard = (
            self.env["base.module.uninstall"]
            .with_user(self.admin)
            .create({"module_ids": [(6, 0, root.ids)], "show_all": False})
        )

        actual = wizard._get_modules()
        self.assertIn(tech_dep.id, actual.ids)
        self.assertNotIn(tech_dep.id, wizard.impacted_module_ids.ids)
        self.assertLessEqual(set(wizard.impacted_module_ids.ids), set(actual.ids))

    def test_uninstall_model_ids_recompute_trigger(self):
        root = self._make_module("wizard_model_root", "installed", application=True)
        wizard = (
            self.env["base.module.uninstall"]
            .with_user(self.admin)
            .create({"module_ids": [(6, 0, root.ids)], "show_all": False})
        )

        before = wizard.model_ids
        wizard.show_all = True
        self.assertEqual(
            wizard.model_ids,
            before,
            "toggling show_all must not change the lost-models set",
        )

    def test_module_update_action_view_is_translatable(self):
        wizard = self.env["base.module.update"].with_user(self.admin).create({})
        action = wizard.action_module_open()
        self.assertEqual(action["res_model"], "ir.module.module")
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["name"], "Modules")
