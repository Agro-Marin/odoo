from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tools.assets.esm_registry import esm_registry

from .common import asset_file
from odoo.addons.base.models.assetsbundle import AssetsBundle


class TestBundleProductsAreMemoized(TransactionCase):
    TEMPLATE = '<templates><t t-name="test.audit.tpl"><div/></t></templates>'

    def test_generate_xml_bundle_renders_once(self):
        bundle = AssetsBundle(
            "test.audit.xml",
            [asset_file("/m/t.xml", self.TEMPLATE)],
            env=self.env,
        )
        first = bundle.generate_esm_template_bundle()
        with patch.object(
            type(bundle._xml), "_render_xml_bundle", side_effect=AssertionError
        ):
            self.assertEqual(bundle.generate_esm_template_bundle(), first)
        self.assertIn("test.audit.tpl", first)

    def test_native_module_data_is_computed_once_per_flag(self):
        bundle = AssetsBundle(
            "test.audit.esm",
            [asset_file("/m/a.js", "/** @odoo-module native */\nexport const a = 1;")],
            env=self.env,
        )
        first = bundle.get_native_module_data(with_bridges=False)
        with patch.object(
            type(bundle), "_native_module_data", side_effect=AssertionError
        ):
            self.assertIs(bundle.get_native_module_data(with_bridges=False), first)

    def test_the_two_bridge_variants_do_not_share_a_cache_entry(self):
        bundle = AssetsBundle(
            "test.audit.esm",
            [asset_file("/m/a.js", "/** @odoo-module native */\nexport const a = 1;")],
            env=self.env,
        )
        without = bundle.get_native_module_data(with_bridges=False)
        with patch.object(type(bundle), "_native_module_data", return_value="SENTINEL"):
            self.assertEqual(
                bundle.get_native_module_data(with_bridges=True), "SENTINEL"
            )
        self.assertEqual(without["bridge_import_map"], {})


class TestSecondaryBundlePageScope(TransactionCase):
    """A secondary bundle externalises against the page, not against a guess.

    ``web.assets_tests`` is layered onto pages with different inventories --
    ``web.assets_web`` on the backend, ``web.assets_frontend_lazy`` +
    ``web.assets_frontend_minimal`` on the frontend -- and every layout renders
    it last.  Intersecting the declared parents instead treated one artifact as
    if it had to satisfy all those pages at once, dropped anything only one of
    them carried, and let esbuild inline a second copy of it.
    """

    BUNDLE = "web.assets_tests"

    def _fake_bundles(self, inventory):
        def _get(_self, name, **kwargs):
            return SimpleNamespace(
                get_native_module_data=lambda **kw: {
                    "import_map": dict.fromkeys(inventory.get(name, ()), "/x.js")
                }
            )

        return patch.object(type(self.env["ir.qweb"]), "_get_asset_bundle", _get)

    def test_a_page_unions_its_bundles_while_a_declaration_intersects_them(self):
        IrQweb = self.env["ir.qweb"]
        inventory = {
            "a.backend": ("@shared/one", "@backend/only"),
            "b.frontend": ("@shared/one", "@frontend/only"),
        }
        with (
            self._fake_bundles(inventory),
            patch(
                "odoo.addons.base.models.ir_qweb_assets.esm_registry",
                return_value=SimpleNamespace(
                    secondary_parents={self.BUNDLE: ("a.backend", "b.frontend")},
                ),
            ),
        ):
            page = IrQweb._get_secondary_provider_specs(
                self.BUNDLE, None, ("a.backend", "b.frontend")
            )
            declared = IrQweb._get_secondary_provider_specs(self.BUNDLE, None, ())
        self.assertEqual(page, {"@shared/one", "@backend/only", "@frontend/only"})
        self.assertEqual(declared, {"@shared/one"})

    def test_the_page_scope_is_empty_for_a_bundle_that_is_not_secondary(self):
        IrQweb = self.env["ir.qweb"]
        self.assertEqual(IrQweb._get_esm_page_scope("web.assets_web"), ())

    def test_a_backend_only_module_is_externalised_on_a_backend_page(self):
        IrQweb = self.env["ir.qweb"]
        params = self.env["ir.asset"]._prepare_assets_params()
        backend = IrQweb._get_asset_bundle(
            "web.assets_web",
            js=True,
            css=False,
            debug_assets=False,
            assets_params=params,
        )
        backend_specs = set(
            backend.get_native_module_data(with_bridges=False)["import_map"]
        )
        secondary = IrQweb._get_asset_bundle(
            self.BUNDLE,
            js=True,
            css=False,
            debug_assets=False,
            assets_params=params,
        )
        own = set(secondary.get_native_module_data(with_bridges=False)["import_map"])
        if not own or not backend_specs:
            self.skipTest("bundles resolved empty (web assets unavailable)")
        discovered, _ext = secondary._bridges._discover_bridge_specifiers(
            own, set(IrQweb._external_libs())
        )
        backend_only = (set(discovered) & backend_specs) - own
        scoped = IrQweb._get_secondary_shared_specs(
            self.BUNDLE, params, ("web.assets_web",)
        )
        self.assertEqual(
            backend_only - set(scoped),
            set(),
            "a module the backend page already carries was left to esbuild, "
            "which inlines a second instance of it",
        )

    def test_a_provider_rendering_after_the_tests_bundle_is_reported(self):
        IrQweb = self.env["ir.qweb"]
        params = self.env["ir.asset"]._prepare_assets_params()
        declared = IrQweb._get_secondary_provider_specs(self.BUNDLE, params, ())
        if not declared:
            self.skipTest("no declared parents resolved (web assets unavailable)")
        # ``web.assets_frontend_minimal`` carries 11 modules; a layout that
        # renders the tests bundle straight after it (room booking did until
        # this was fixed) leaves every other provider too late to externalise.
        with self.assertLogs("odoo.assets.esm", level="WARNING") as logs:
            IrQweb._get_secondary_shared_specs(
                self.BUNDLE, params, ("web.assets_frontend_minimal",)
            )
        self.assertTrue(
            any("secondary_provider_renders_late" in line for line in logs.output),
            logs.output,
        )


class TestEsmRegistryInstallationScope(TransactionCase):
    def _declarations(self):
        from odoo.modules import Manifest

        for manifest in Manifest.all_addon_manifests():
            esm = manifest.get("esm")
            if esm:
                yield manifest.name, esm

    def _claims_a_live_foreign_namespace(self, module, bundle):
        from odoo.modules import Manifest

        namespace = bundle.partition(".")[0]
        if namespace == module:
            return False
        return Manifest.for_addon(namespace, display_warning=False) is not None

    def test_a_module_only_registers_bundles_it_owns(self):
        stolen = [
            (module, bundle)
            for module, esm in self._declarations()
            for bundle in esm.get("bundles", ())
            if self._claims_a_live_foreign_namespace(module, bundle)
        ]

        self.assertFalse(stolen, f"modules registering foreign bundles: {stolen}")

    def test_child_declarations_stay_in_their_namespace(self):
        misplaced = [
            (module, key, child)
            for module, esm in self._declarations()
            for key in ("dynamic_children", "import_map_includes")
            for children in (esm.get(key) or {}).values()
            for child in children
            if self._claims_a_live_foreign_namespace(module, child)
        ]

        self.assertFalse(
            misplaced, f"modules contributing foreign children: {misplaced}"
        )

    def test_absent_modules_contribute_empty_children_not_wrong_ones(self):
        registry = esm_registry()
        installed = self.env["ir.asset"]._get_addons_installed()
        absent = {
            child
            for children in registry.dynamic_children.values()
            for child in children
            if child.partition(".")[0] not in installed
        }
        if not absent:
            self.skipTest("every module declaring a dynamic child is installed")

        children = self.env["ir.qweb"]._get_dynamic_child_bundles(
            "web.assets_web",
            self.env["ir.asset"]._prepare_assets_params(),
            debug_assets=True,
        )
        built = {child.name: child for child in children}

        self.assertTrue(
            absent & set(built),
            "no absent child was built -- the registry became installation-aware",
        )
        for name in sorted(absent & set(built)):
            child = built[name]
            self.assertFalse(
                child.native_modules or child.javascripts,
                f"{name} is not installed yet contributed files to the import map",
            )


class TestSecondarySingletonSurface(TransactionCase):
    BUNDLE = "web.assets_tests"
    PARENT = "web.assets_web"

    def _specs(self, bundle):
        return set(
            self.env["ir.qweb"]
            ._get_asset_bundle(bundle, js=True, css=False, assets_params={})
            .get_native_module_data(with_bridges=False)["import_map"]
        )

    def test_every_stubbed_specifier_is_owned_by_the_parent(self):
        shared = self.env["ir.qweb"]._get_secondary_shared_specs(self.BUNDLE, {})
        if not shared:
            self.skipTest("no shared specifiers on this database")

        self.assertLessEqual(set(shared), self._specs(self.PARENT))

    def test_the_guarantee_stops_at_direct_imports(self):
        shared = set(self.env["ir.qweb"]._get_secondary_shared_specs(self.BUNDLE, {}))
        if not shared:
            self.skipTest("no shared specifiers on this database")
        parent_specs = self._specs(self.PARENT)
        own_specs = self._specs(self.BUNDLE)

        reachable_unstubbed = (parent_specs - shared) - own_specs

        self.assertTrue(
            reachable_unstubbed,
            "the singleton guarantee now covers the whole parent surface -- "
            "drop this test and the shortfall paragraph in "
            "_get_secondary_shared_specs",
        )
