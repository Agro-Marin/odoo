import io
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
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
    def test_new_module_icon_flag(self):
        module = self.env["ir.module.module"].new({"name": "missing"})
        self.assertFalse(module.icon_flag)
        self.assertFalse(module.icon_image)

    def test_description_html_tolerates_malformed_index_html(self):
        module = self.env["ir.module.module"].search([("name", "=", "base")])

        with patch(
            "odoo.tools.file_open",
            side_effect=lambda *a, **kw: io.BytesIO(b"\x89PNG\xff\xfe broken \xff"),
        ):
            module.invalidate_recordset(["description_html"])
            self.assertIsNotNone(module.description_html)

        with patch(
            "odoo.tools.file_open",
            side_effect=lambda *a, **kw: io.BytesIO(b""),
        ):
            module.invalidate_recordset(["description_html"])
            self.assertIsNotNone(module.description_html)
        module.invalidate_recordset(["description_html"])

    @mute_logger("odoo.modules.module")
    def test_module_wrong_icon(self):
        module = self.env["ir.module.module"].create(
            {"name": "wrong_icon", "icon": "/not/valid.png"}
        )
        self.assertFalse(module.icon_image)

    def test_get_id_reflects_freshly_created_module(self):
        Module = self.env["ir.module.module"]
        self.assertIsNone(Module._get_id("irmod_l2_probe"))
        module = Module.create({"name": "irmod_l2_probe"})
        self.assertEqual(Module._get_id("irmod_l2_probe"), module.id)

    def test_update_list_returns_named_result(self):
        result = self.env["ir.module.module"].update_list()
        updated, added = result
        self.assertEqual(result.updated, updated)
        self.assertEqual(result.added, added)
        self.assertIsInstance(result.updated, int)
        self.assertIsInstance(result.added, int)

    @mute_logger("odoo.addons.base.models.ir_module")
    def test_button_install_blocked_for_erp_manager_without_system(self):
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
        self.assertEqual(module.state, "uninstalled")

    @mute_logger("odoo.addons.base.models.ir_module")
    def test_button_upgrade_sweeps_reverse_dependencies(self):
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

    def test_sync_auto_install_required_batched(self):
        Module = self.env["ir.module.module"]
        Dependency = self.env["ir.module.module.dependency"]
        mod_x = Module.create({"name": "irmod_sync_x", "state": "uninstalled"})
        mod_y = Module.create({"name": "irmod_sync_y", "state": "uninstalled"})
        dep_xa, dep_xb, dep_ya = Dependency.create(
            [
                {"module_id": mod_x.id, "name": "irmod_sync_dep_a"},
                {"module_id": mod_x.id, "name": "irmod_sync_dep_b"},
                {"module_id": mod_y.id, "name": "irmod_sync_dep_a"},
            ]
        )
        Module._sync_auto_install_required(
            {mod_x.id: ["irmod_sync_dep_a"], mod_y.id: ()}
        )
        self.assertTrue(dep_xa.auto_install_required)
        self.assertFalse(dep_xb.auto_install_required)
        self.assertFalse(dep_ya.auto_install_required)
        Module._sync_auto_install_required(
            {mod_x.id: ["irmod_sync_dep_a"], mod_y.id: ()}
        )
        self.assertEqual(self.env.cr.rowcount, 0)
        Module._sync_auto_install_required({mod_x.id: ["irmod_sync_dep_b"]})
        self.assertFalse(dep_xa.auto_install_required)
        self.assertTrue(dep_xb.auto_install_required)

    @mute_logger("odoo.addons.base.models.ir_module", "odoo.modules.module")
    def test_button_install_exclusive_category_closure(self):
        Module = self.env["ir.module.module"]
        category = self.env["ir.module.category"].create(
            {"name": "irmod excl cat", "exclusive": True}
        )
        Module.create(
            {"name": "irmod_excl_a", "state": "installed", "category_id": category.id}
        )
        mod_b = Module.create(
            {"name": "irmod_excl_b", "state": "installed", "category_id": category.id}
        )
        self.env["ir.module.module.dependency"].create(
            {"module_id": mod_b.id, "name": "irmod_excl_a"}
        )
        mod_b.button_install()
        Module.create(
            {"name": "irmod_excl_c", "state": "installed", "category_id": category.id}
        )
        with self.assertRaises(UserError):
            mod_b.button_install()

    def test_has_iap_transitive_dependents(self):
        Module = self.env["ir.module.module"]
        if not Module._get_id("iap"):
            self.skipTest("iap module not present in the addons path")
        direct = Module.create({"name": "irmod_iap_dep", "state": "uninstalled"})
        indirect = Module.create({"name": "irmod_iap_dep2", "state": "uninstalled"})
        self.env["ir.module.module.dependency"].create(
            [
                {"module_id": direct.id, "name": "iap"},
                {"module_id": indirect.id, "name": "irmod_iap_dep"},
            ]
        )
        unrelated = Module.create({"name": "irmod_no_iap", "state": "uninstalled"})
        self.assertTrue(direct.has_iap)
        self.assertTrue(indirect.has_iap)
        self.assertFalse(unrelated.has_iap)


class TestModuleDependencyClosure(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Module = cls.env["ir.module.module"]
        cls.mod_a = Module.create({"name": "tclos_a", "state": "installed"})
        cls.mod_b = Module.create({"name": "tclos_b", "state": "installed"})
        cls.mod_c = Module.create({"name": "tclos_c", "state": "uninstalled"})
        cls.mod_d = Module.create({"name": "tclos_d", "state": "installed"})
        cls.env["ir.module.module.dependency"].create(
            [
                {"module_id": cls.mod_b.id, "name": "tclos_a"},
                {"module_id": cls.mod_c.id, "name": "tclos_b"},
                {"module_id": cls.mod_d.id, "name": "tclos_c"},
            ]
        )

    def test_downstream_full_closure(self):
        got = self.mod_a.downstream_dependencies(exclude_states=())
        self.assertEqual(set(got.ids), {self.mod_b.id, self.mod_c.id, self.mod_d.id})
        self.assertNotIn(self.mod_a.id, got.ids)

    def test_downstream_state_pruning_blocks_paths(self):
        got = self.mod_a.downstream_dependencies()
        self.assertEqual(set(got.ids), {self.mod_b.id})

    def test_upstream_full_closure(self):
        got = self.mod_d.upstream_dependencies(exclude_states=())
        self.assertEqual(set(got.ids), {self.mod_a.id, self.mod_b.id, self.mod_c.id})
        self.assertNotIn(self.mod_d.id, got.ids)

    def test_upstream_default_excludes_installed(self):
        got = self.mod_d.upstream_dependencies()
        self.assertEqual(set(got.ids), {self.mod_c.id})

    def test_empty_string_exclude_matches_no_state(self):
        got = self.mod_d.upstream_dependencies(exclude_states=("",))
        self.assertEqual(set(got.ids), {self.mod_a.id, self.mod_b.id, self.mod_c.id})

    def test_known_deps_blocks_traversal_and_unions_result(self):
        got = self.mod_a.downstream_dependencies(
            known_deps=self.mod_b, exclude_states=()
        )
        self.assertEqual(set(got.ids), {self.mod_b.id})

    def test_seed_traversed_regardless_of_state(self):
        self.mod_a.state = "to remove"
        got = self.mod_a.downstream_dependencies()
        self.assertEqual(set(got.ids), {self.mod_b.id})

    def test_empty_recordset_closure(self):
        empty = self.env["ir.module.module"]
        self.assertFalse(empty.downstream_dependencies(exclude_states=()))
        self.assertFalse(empty.upstream_dependencies(exclude_states=()))


class IrModuleUnsavedRecordCase(TransactionCase):
    def test_get_module_info_without_name(self):
        self.assertEqual(self.env["ir.module.module"].get_module_info(False), {})
        self.assertEqual(self.env["ir.module.module"].get_module_info(""), {})

    def test_manifest_version_on_unsaved_record(self):
        module = self.env["ir.module.module"].new({})
        self.assertTrue(module.manifest_version)

    def test_get_module_info_still_reads_real_manifest(self):
        manifest = self.env["ir.module.module"].get_module_info("base")
        self.assertTrue(manifest)
        self.assertTrue(manifest.get("version"))
