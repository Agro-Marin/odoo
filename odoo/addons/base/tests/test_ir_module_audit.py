from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.modules.module import Manifest, MissingDependency
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestModuleDependencies(TransactionCase):
    """Regression coverage for the dependency-closure logic, the install
    exclusion gate and the auto-install country gate of ir.module.module.

    Audit Tranche 4 — finding IRMOD-T1. All tests run fully in-transaction on
    synthetic module records; none triggers a real install/upgrade (no
    button_immediate_* call, hence no Registry rebuild).
    """

    def setUp(self):
        super().setUp()
        self.Module = self.env["ir.module.module"]
        self.Dependency = self.env["ir.module.module.dependency"]
        self.admin = new_test_user(
            self.env,
            login="audit_module_admin",
            groups="base.group_system",
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

    def test_downstream_closure(self):
        """downstream_dependencies walks the transitive set of dependents.

        Graph: C depends on B, B depends on A. Starting from A, the closure is
        {B, C}, restricted to non-excluded states (installed here).
        """
        mod_a = self._make_module("audit_dep_a", "installed")
        mod_b = self._make_module("audit_dep_b", "installed")
        mod_c = self._make_module("audit_dep_c", "installed")
        self._add_dependency(mod_b, "audit_dep_a")
        self._add_dependency(mod_c, "audit_dep_b")

        closure = mod_a.downstream_dependencies()
        self.assertEqual(
            closure,
            mod_b | mod_c,
            "downstream closure of A must be exactly its transitive dependents B and C",
        )
        # A 'to remove' dependent is filtered out by the default exclude_states.
        mod_b.state = "to remove"
        filtered = mod_a.downstream_dependencies()
        self.assertNotIn(
            mod_b.id,
            filtered.ids,
            "a 'to remove' module is excluded by default exclude_states",
        )
        # With B excluded the recursion can no longer reach C through B.
        self.assertNotIn(
            mod_c.id,
            filtered.ids,
            "C is unreachable once the intermediate dependent B is filtered out",
        )

    def test_upstream_closure(self):
        """upstream_dependencies walks the transitive set of dependencies.

        Same graph (C->B->A). Starting from C, the dependency closure is
        {B, A}, restricted to the default exclude_states (which keeps
        'uninstalled' modules and drops 'installed' ones).
        """
        mod_a = self._make_module("audit_up_a", "uninstalled")
        mod_b = self._make_module("audit_up_b", "uninstalled")
        mod_c = self._make_module("audit_up_c", "uninstalled")
        self._add_dependency(mod_b, "audit_up_a")
        self._add_dependency(mod_c, "audit_up_b")

        closure = mod_c.upstream_dependencies()
        self.assertEqual(
            closure,
            mod_a | mod_b,
            "upstream closure of C must be exactly its transitive dependencies B and A",
        )
        # The default exclude_states drops 'installed' dependencies.
        mod_b.state = "installed"
        filtered = mod_c.upstream_dependencies()
        self.assertNotIn(
            mod_b.id,
            filtered.ids,
            "an 'installed' dependency is excluded by default exclude_states",
        )
        self.assertNotIn(
            mod_a.id,
            filtered.ids,
            "A is unreachable once the intermediate dependency B is filtered out",
        )

    def test_all_dependencies_map(self):
        """all_dependencies returns the direct-dependency map per module name.

        Graph C->B->A. all_dependencies(['audit_all_c']) recursively collects
        every module reachable through the depends chain and maps each module
        name to its list of direct dependency names.
        """
        self._make_module("audit_all_a", "uninstalled")
        mod_b = self._make_module("audit_all_b", "uninstalled")
        mod_c = self._make_module("audit_all_c", "uninstalled")
        self._add_dependency(mod_b, "audit_all_a")
        self._add_dependency(mod_c, "audit_all_b")

        result = self.Dependency.all_dependencies(["audit_all_c"])
        self.assertEqual(
            result.get("audit_all_c"),
            ["audit_all_b"],
            "C declares a direct dependency on B",
        )
        self.assertEqual(
            result.get("audit_all_b"),
            ["audit_all_a"],
            "B (pulled in transitively) declares a direct dependency on A",
        )
        # A has no dependency rows, so it never appears as a key in the map.
        self.assertNotIn(
            "audit_all_a",
            result,
            "A has no dependencies and is therefore not a key in the map",
        )

    @mute_logger("odoo.addons.base.models.ir_module")
    def test_install_exclusion_raises(self):
        """button_install rejects two mutually-installed modules that exclude
        each other, with a UserError naming both shortdescs.

        button_install only writes states and validates exclusions in-transaction
        (it is the inner function of _button_immediate_function); it does not
        rebuild the registry, so it is safe to call directly here.
        """
        mod_x = self._make_module("audit_excl_x", "uninstalled")
        mod_y = self._make_module("audit_excl_y", "uninstalled")
        # Mutual exclusion materialized as exclusion rows on both modules.
        self.env["ir.module.module.exclusion"].create(
            {"module_id": mod_x.id, "name": "audit_excl_y"}
        )
        self.env["ir.module.module.exclusion"].create(
            {"module_id": mod_y.id, "name": "audit_excl_x"}
        )

        modules = (mod_x | mod_y).with_user(self.admin)
        with self.assertRaises(UserError) as ctx:
            modules.button_install()
        message = str(ctx.exception)
        # The UserError formats both incompatible modules by their shortdesc.
        self.assertIn(mod_x.shortdesc, message)
        self.assertIn(mod_y.shortdesc, message)

    @mute_logger("odoo.addons.base.models.ir_module")
    def test_install_country_gate(self):
        """must_install honours the country gate for auto-install modules.

        An auto-install module flagged for a country is only pulled in when a
        company sits in one of its countries. We exercise this by driving a
        button_install on a base dependency and checking whether the country-
        gated auto-install module follows. button_install writes states only;
        it does not rebuild the registry.
        """
        base_dep = self._make_module("audit_country_base", "uninstalled")

        # Country-specific auto-install module depending on base_dep.
        gated = self._make_module(
            "audit_country_gated",
            "uninstalled",
            auto_install=True,
        )
        dep_row = self._add_dependency(gated, "audit_country_base")
        # auto_install_required defaults True; must_install reads it.
        self.assertTrue(dep_row.auto_install_required)

        # Pick a country that no existing company belongs to.
        company_countries = self.env["res.company"].search([]).country_id
        foreign_country = self.env["res.country"].search(
            [("id", "not in", company_countries.ids)], limit=1
        )
        self.assertTrue(foreign_country, "need a country no company is set to")
        gated.country_ids = foreign_country

        # Out of country: the gate excludes the auto-install module.
        (base_dep.with_user(self.admin)).button_install()
        self.assertEqual(
            gated.state,
            "uninstalled",
            "country-gated auto-install module must stay uninstalled when no "
            "company is in its country",
        )

        # Now place a company in the gated country and retry from a clean state.
        base_dep.state = "uninstalled"
        company = self.env["res.company"].search([], limit=1)
        company.country_id = foreign_country
        (base_dep.with_user(self.admin)).button_install()
        self.assertEqual(
            gated.state,
            "to install",
            "country-gated auto-install module must be pulled in once a company "
            "is in its country",
        )


@tagged("post_install", "-at_install")
class TestModuleAuditRound2(TransactionCase):
    """Regression coverage for the 2026-06-10 audit round: relational search
    operators on dependency/exclusion, the external-dependency error path and
    update_list idempotence."""

    def setUp(self):
        super().setUp()
        self.Module = self.env["ir.module.module"]
        self.Dependency = self.env["ir.module.module.dependency"]

    def _make_module(self, name, state="installed"):
        """Create a synthetic module record in the given state.

        :param str name: technical name
        :param str state: target state (forced after create)
        :return: the created module record
        :rtype: recordset
        """
        module = self.Module.create({"name": name, "shortdesc": name.upper()})
        module.state = state
        return module

    def test_search_depend_any_and_dotted_path(self):
        """depend_id supports 'any' sub-domains and dotted-path conditions.

        The 'any' operator carries a (sub)domain — also produced by the ORM's
        path decomposition for ('depend_id.name', '=', x) — which must be
        resolved to module ids, not browsed as if it were ids.
        """
        mod_a = self._make_module("audit_r2_a")
        mod_b = self._make_module("audit_r2_b")
        dep = self.Dependency.create({"module_id": mod_b.id, "name": "audit_r2_a"})

        found = self.Dependency.search(
            [("depend_id", "any", [("name", "=", "audit_r2_a")])]
        )
        self.assertIn(dep, found, "'any' with a list domain must resolve")
        found = self.Dependency.search([("depend_id.name", "=", "audit_r2_a")])
        self.assertIn(dep, found, "dotted path through depend_id must resolve")
        found = self.Dependency.search([("depend_id", "in", mod_a.ids)])
        self.assertIn(dep, found, "'in' with ids keeps working")
        found = self.Dependency.search(
            [("depend_id", "not any", [("name", "=", "audit_r2_a")])]
        )
        self.assertNotIn(dep, found, "'not any' is handled through the inverse")

    def test_search_exclusion_any_and_dotted_path(self):
        """exclusion_id supports 'any' sub-domains and dotted-path conditions."""
        self._make_module("audit_r2_x")
        mod_y = self._make_module("audit_r2_y")
        excl = self.env["ir.module.module.exclusion"].create(
            {"module_id": mod_y.id, "name": "audit_r2_x"}
        )

        found = self.env["ir.module.module.exclusion"].search(
            [("exclusion_id", "any", [("name", "=", "audit_r2_x")])]
        )
        self.assertIn(excl, found)
        found = self.env["ir.module.module.exclusion"].search(
            [("exclusion_id.name", "=", "audit_r2_x")]
        )
        self.assertIn(excl, found)

    def test_has_iap_via_transitive_dependency(self):
        """has_iap holds for direct and transitive dependents of iap, and is
        computed from a single downstream closure of iap per batch."""
        if not self.Module._get_id("iap"):
            self.skipTest("iap module not present in the addons path")
        direct = self._make_module("audit_r2_iap_direct")
        self.Dependency.create({"module_id": direct.id, "name": "iap"})
        indirect = self._make_module("audit_r2_iap_indirect")
        self.Dependency.create(
            {"module_id": indirect.id, "name": "audit_r2_iap_direct"}
        )
        unrelated = self._make_module("audit_r2_iap_none")
        self.assertTrue(direct.has_iap)
        self.assertTrue(indirect.has_iap)
        self.assertFalse(unrelated.has_iap)

    def test_check_external_dependencies_no_os_release(self):
        """The apt-hint path must not mask the UserError when the host has no
        os-release file (platform.freedesktop_os_release raises OSError)."""
        manifest = MagicMock()
        manifest.check_manifest_dependencies.side_effect = MissingDependency(
            "Unable to find {dependency!r}", "audit_r2_missing_binary"
        )
        with (
            patch.object(Manifest, "for_addon", return_value=manifest),
            patch(
                "platform.freedesktop_os_release",
                side_effect=OSError(2, "no os-release file"),
            ),
        ):
            with self.assertRaises(UserError) as ctx:
                self.Module.check_external_dependencies("audit_r2_module")
        self.assertIn("audit_r2_missing_binary", str(ctx.exception))

    def test_update_list_dependency_idempotent(self):
        """A second update_list run must not rewrite unchanged dependency rows
        (auto_install_required is guarded by IS DISTINCT FROM)."""
        self.Module.update_list()
        rewritten = {"rows": 0}
        cr = self.env.cr
        orig_execute = cr.execute

        def counting_execute(query, *args, **kwargs):
            res = orig_execute(query, *args, **kwargs)
            q = query if isinstance(query, str) else str(query)
            if (
                "UPDATE ir_module_module_dependency" in q
                and "auto_install_required" in q
            ):
                rewritten["rows"] += cr.rowcount
            return res

        cr.execute = counting_execute
        try:
            self.Module.update_list()
        finally:
            cr.execute = orig_execute
        self.assertEqual(
            rewritten["rows"],
            0,
            "a no-op update_list must not produce dependency row versions",
        )

    def test_get_views_single_model_data_query(self):
        """_compute_views_by_module fetches ir.model.data once for the whole
        batch instead of issuing one search per module."""
        mods = self.Module.search([("state", "=", "installed")])
        mods.modified(["state"])  # mark the stored computes for recompute
        counter = {"imd_selects": 0}
        cr = self.env.cr
        orig_execute = cr.execute

        def counting_execute(query, *args, **kwargs):
            q = query if isinstance(query, str) else str(query)
            if "ir_model_data" in q and q.lstrip().upper().startswith("SELECT"):
                counter["imd_selects"] += 1
            return orig_execute(query, *args, **kwargs)

        cr.execute = counting_execute
        try:
            mods.mapped("views_by_module")
        finally:
            cr.execute = orig_execute
        self.assertLessEqual(
            counter["imd_selects"],
            2,
            f"recomputing the view lists for {len(mods)} modules must batch "
            "the ir.model.data search",
        )
