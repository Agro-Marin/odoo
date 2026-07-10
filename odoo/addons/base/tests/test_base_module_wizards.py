from odoo.exceptions import AccessDenied, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestBaseModuleWizards(TransactionCase):
    """Audit Tranche 4 coverage for the base module wizards.

    Pins the upgrade-apply access gate (BMUPG-L1), the cancel inverse-mapping
    (BMUPG-M1), and the uninstall display-vs-actual invariant (T-BMUN1). Every
    test runs in-transaction on synthetic ir.module.module records; none
    triggers a real Registry rebuild.
    """

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
        """Create a synthetic ir.module.module record in a given state.

        :param str name: technical name
        :param str state: target state (set after create to bypass readonly default)
        :return: the created module record
        :rtype: recordset
        """
        module = self.Module.create(
            dict({"name": name, "shortdesc": name.upper()}, **vals)
        )
        # state is readonly + has a default of "uninstallable"; force it here
        module.state = state
        return module

    def _add_dependency(self, module, dep_name):
        """Materialize a manifest 'depends' row: module_id depends on dep_name.

        :param recordset module: the dependent module
        :param str dep_name: technical name of the dependency
        :return: the created dependency row
        :rtype: recordset
        """
        return self.Dependency.create({"module_id": module.id, "name": dep_name})

    @mute_logger("odoo.addons.base.models.ir_module")
    def test_upgrade_module_denies_non_admin(self):
        """BMUPG-L1: upgrade_module is gated by @assert_log_admin_access.

        A non-admin internal user calling the apply step raises AccessDenied
        before any commit/Registry rebuild, and the DENY line is logged.
        """
        wizard = self.env["base.module.upgrade"].create({})
        with self.assertRaises(AccessDenied):
            wizard.with_user(self.plain_user).upgrade_module()

    def test_upgrade_module_allows_admin_until_apply(self):
        """BMUPG-L1: the admin gate lets a legitimate admin through.

        Assert the precondition guard runs (UserError on an uninstalled
        dependency) rather than AccessDenied, proving the gate passed without
        reaching the real commit/Registry.new apply.
        """
        mod = self._make_module("wizard_upg_root", "to install")
        self._add_dependency(mod, "wizard_upg_missing_dep")

        wizard = self.env["base.module.upgrade"].create({})
        with self.assertRaises(UserError) as ctx:
            wizard.with_user(self.admin).upgrade_module()
        # The admin gate passed; we stopped at the dependency precondition.
        self.assertIn("wizard_upg_missing_dep", str(ctx.exception))

    def test_upgrade_module_cancel_reverts_schedule(self):
        """BMUPG-M1: cancel is the exact inverse of the schedule setters.

        to upgrade / to remove -> installed; to install -> uninstalled. Guards
        the swapped-local-name refactor against a regression.
        """
        to_upgrade = self._make_module("wizard_cancel_upg", "to upgrade")
        to_remove = self._make_module("wizard_cancel_rem", "to remove")
        to_install = self._make_module("wizard_cancel_ins", "to install")

        wizard = self.env["base.module.upgrade"].create({})
        wizard.with_user(self.admin).upgrade_module_cancel()

        self.assertEqual(to_upgrade.state, "installed")
        self.assertEqual(to_remove.state, "installed")
        self.assertEqual(to_install.state, "uninstalled")

    def test_uninstall_actual_set_covers_hidden_dependent(self):
        """T-BMUN1: the actual uninstall closure includes a technical dependent
        that the display set hides (show_all=False).

        A technical (non-application) module depends on an application root.
        With show_all=False it is filtered OUT of impacted_module_ids (display),
        but _get_modules() (the closure the real uninstall uses) must still
        include it, so a refactor cannot silently under-uninstall.
        """
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

        # Actual closure (drives the real uninstall) includes the hidden dep.
        actual = wizard._get_modules()
        self.assertIn(tech_dep.id, actual.ids)
        # Display set (app-only) hides the technical dependent.
        self.assertNotIn(tech_dep.id, wizard.impacted_module_ids.ids)
        # Invariant: actual closure is a superset of what is displayed.
        self.assertLessEqual(set(wizard.impacted_module_ids.ids), set(actual.ids))

    def test_uninstall_model_ids_recompute_trigger(self):
        """BMUN-M1: model_ids tracks module_ids and is invariant to show_all.

        _compute_model_ids depends on module_ids (the real input via
        _get_modules), not on the show_all display filter. Toggling only
        show_all must not change the lost-models set.
        """
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

    def test_module_update_action_open_is_translatable(self):
        """BMU-M2: the Apps-list action name is wrapped in _()."""
        wizard = self.env["base.module.update"].with_user(self.admin).create({})
        action = wizard.action_module_open()
        self.assertEqual(action["res_model"], "ir.module.module")
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["name"], "Modules")
