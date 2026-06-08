from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools import mute_logger


class IrModuleCase(TransactionCase):
    @mute_logger("odoo.modules.module")
    def test_missing_module_icon(self):
        module = self.env["ir.module.module"].create({"name": "missing"})
        base = self.env["ir.module.module"].search([("name", "=", "base")])
        self.assertEqual(base.icon_image, module.icon_image)

    @mute_logger("odoo.modules.module")
    def test_new_module_icon(self):
        module = self.env["ir.module.module"].new({"name": "missing"})
        self.assertFalse(module.icon_image)

    @mute_logger("odoo.modules.module")
    def test_module_wrong_icon(self):
        module = self.env["ir.module.module"].create(
            {"name": "wrong_icon", "icon": "/not/valid.png"}
        )
        self.assertFalse(module.icon_image)

    def test_get_id_reflects_freshly_created_module(self):
        # IRMOD-L2: _get_id caches a negative result in the "stable" cache.
        # create() must clear that cache (mirroring unlink) so a previously
        # cached None does not go stale within the same registry.
        Module = self.env["ir.module.module"]
        self.assertIsNone(Module._get_id("irmod_l2_probe"))
        module = Module.create({"name": "irmod_l2_probe"})
        self.assertEqual(Module._get_id("irmod_l2_probe"), module.id)

    def test_update_list_returns_named_result(self):
        # IRMOD-M4: update_list returns a self-documenting UpdateListResult
        # while staying positionally compatible with tuple unpacking.
        result = self.env["ir.module.module"].update_list()
        updated, added = result
        self.assertEqual(result.updated, updated)
        self.assertEqual(result.added, added)
        self.assertIsInstance(result.updated, int)
        self.assertIsInstance(result.added, int)

    @mute_logger("odoo.addons.base.models.ir_module")
    def test_button_install_blocked_for_erp_manager_without_system(self):
        # IRMOD-L1 / T-IRMOD2: assert_log_admin_access gates on is_admin()
        # (su OR group_erp_manager), which is one level below the group_system
        # write ACL that actually protects the model. An erp_manager-only user
        # therefore passes the decorator but is still hard-stopped by the ACL
        # before reaching a state write. The ACL, not the decorator, is the
        # security boundary.
        user = new_test_user(
            self.env,
            login="irmod_erp_manager",
            groups="base.group_erp_manager",
        )
        module = self.env["ir.module.module"].create(
            {"name": "irmod_l1_probe", "state": "uninstalled"}
        )
        with self.assertRaises(AccessError):
            module.with_user(user).button_install()
        # The state write must not have happened.
        self.assertEqual(module.state, "uninstalled")

    @mute_logger("odoo.addons.base.models.ir_module")
    def test_button_upgrade_sweeps_reverse_dependencies(self):
        # IRMOD-T5: button_upgrade follows reverse dependencies and marks the
        # whole closure "to upgrade" without applying it (no immediate driver).
        Module = self.env["ir.module.module"]
        base_mod = Module.create({"name": "irmod_base", "state": "installed"})
        dependent = Module.create({"name": "irmod_dependent", "state": "installed"})
        self.env["ir.module.module.dependency"].create(
            {"module_id": dependent.id, "name": "irmod_base"}
        )
        base_mod.button_upgrade()
        self.assertEqual(base_mod.state, "to upgrade")
        self.assertEqual(
            dependent.state,
            "to upgrade",
            "reverse-dependency sweep should mark dependents to upgrade",
        )
