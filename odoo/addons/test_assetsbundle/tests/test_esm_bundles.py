"""Native ES modules: the registry, the import map, the bridges, esbuild.

This is the newest and least settled layer, and the one whose failures are
least legible at runtime -- a mis-registered bundle or a bridge that resolves
to undefined surfaces as an unrelated service going missing, far from the
cause. It is therefore the layer that most needs its invariants written down.
"""

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from odoo import tools
from odoo.tests.common import BaseCase, TransactionCase
from odoo.tools.assets.esbuild import EsbuildCompiler, _find_esbuild
from odoo.tools.assets.esm_bridges import BridgeShimManager
from odoo.tools.assets.esm_registry import esm_registry, validate_esm_config
from odoo.tools.json import scriptsafe as json
from odoo.tools.misc import file_path

from .common import asset_file, make_cursor_readonly
from odoo.addons.base.models.assetsbundle import (
    AssetsBundle,
    JavascriptAsset,
    _cached_module_classification,
)


class TestClassificationCache(TransactionCase):
    def test_second_construction_hits_cache(self):
        loader_path = file_path("web/static/src/module_loader.js")
        files = [
            {
                "url": "/web/static/src/module_loader.js",
                "filename": loader_path,
                "content": "",
                "last_modified": 111.0,
            }
        ]
        _cached_module_classification.cache_clear()
        AssetsBundle("web.assets_web", files, env=self.env)
        info = _cached_module_classification.cache_info()
        self.assertEqual((info.misses, info.hits), (1, 0))
        AssetsBundle("web.assets_web", files, env=self.env)
        info = _cached_module_classification.cache_info()
        self.assertEqual((info.misses, info.hits), (1, 1))

    def test_mtime_change_invalidates(self):
        loader_path = file_path("web/static/src/module_loader.js")

        def files(mtime):
            return [
                {
                    "url": "/web/static/src/module_loader.js",
                    "filename": loader_path,
                    "content": "",
                    "last_modified": mtime,
                }
            ]

        _cached_module_classification.cache_clear()
        AssetsBundle("web.assets_web", files(1.0), env=self.env)
        AssetsBundle("web.assets_web", files(2.0), env=self.env)
        self.assertEqual(_cached_module_classification.cache_info().misses, 2)


class TestEsmGraphCanonicalHome(BaseCase):
    def test_predicates_resolve_from_esm_graph(self):
        from odoo.tools.assets import esm_graph

        self.assertTrue(callable(esm_graph.is_native_module))
        self.assertTrue(callable(esm_graph._parse_odoo_module_header))

    def test_dead_reexport_not_resurrected(self):
        import odoo.addons.base.models.assetsbundle as ab

        self.assertTrue(hasattr(ab, "_parse_odoo_module_header"))
        self.assertFalse(hasattr(ab, "is_native_module"))


class _NativeStubBundle:
    name = "web.assets_test"

    def __init__(self, modules):
        self.native_modules = modules
        self.bridge_input = None

    @property
    def _bridges(self):
        return self

    def _build_native_to_legacy_bridge(self, specifiers, modules=None):
        self.bridge_input = set(specifiers)
        return {"@legacy/shim": "data:text/javascript,"}


class TestNativeModuleDataSpecifiers(BaseCase):
    def _asset(self, url):
        return JavascriptAsset(
            _NativeStubBundle([]), inline="export const x = 1;\n", url=url
        )

    def _data(self, urls, **kw):
        bundle = _NativeStubBundle([self._asset(u) for u in urls])
        return bundle, AssetsBundle._native_module_data(bundle, **kw)

    def test_index_js_keeps_both_specifier_forms(self):
        _, res = self._data(["/web/static/src/core/utils/index.js"], with_bridges=False)
        self.assertIn("@web/core/utils", res["import_map"])
        self.assertIn("@web/core/utils/index", res["import_map"])

    def test_bridge_receives_exactly_import_map_keys(self):
        bundle, res = self._data(
            [
                "/web/static/src/core/registry.js",
                "/web/static/src/core/utils/index.js",
            ],
            with_bridges=True,
        )
        self.assertEqual(bundle.bridge_input, set(res["import_map"]))
        self.assertTrue(res["bridge_import_map"])

    def test_with_bridges_false_skips_builder(self):
        bundle, res = self._data(
            ["/web/static/src/core/registry.js"], with_bridges=False
        )
        self.assertEqual(res["bridge_import_map"], {})
        self.assertIsNone(bundle.bridge_input)

    def test_bridge_resolver_memoizes_source_exports(self):
        from odoo.tools.assets.esm_graph import _BridgeExportResolver

        resolver = _BridgeExportResolver({}, {}, "test_bundle")
        resolver._cache["@x/y"] = "export const A = 1;\nexport default A;"
        first = resolver.source_exports("@x/y")
        second = resolver.source_exports("@x/y")
        self.assertEqual(first[0], {"A"})
        self.assertTrue(first[1])
        self.assertIs(first, second, "parsed exports must be memoized")


class TestImportMapSpecCollision(BaseCase):
    _LOG = "odoo.assets.bundle"

    @staticmethod
    def _mod(module_path, url, alias=None):
        header = {"alias": alias} if alias else None
        return SimpleNamespace(module_path=module_path, url=url, parsed_header=header)

    def _data(self, modules):
        fake = SimpleNamespace(native_modules=modules, name="my.bundle")
        return AssetsBundle._native_module_data(fake, with_bridges=False)

    def test_colliding_specs_warn_and_keep_last_wins(self):
        mods = [
            self._mod("@web/foo", "/web/static/src/foo.js"),
            self._mod("@web/foo", "/web/static/src/foo/index.js"),
        ]
        with self.assertLogs(self._LOG, level="WARNING") as cm:
            data = self._data(mods)
        self.assertIn("import_map_spec_collision", "\n".join(cm.output))
        self.assertEqual(data["import_map"]["@web/foo"], "/web/static/src/foo/index.js")

    def test_colliding_alias_warns(self):
        mods = [
            self._mod("@web/a", "/web/static/src/a.js", alias="shared"),
            self._mod("@web/b", "/web/static/src/b.js", alias="shared"),
        ]
        with self.assertLogs(self._LOG, level="WARNING") as cm:
            self._data(mods)
        self.assertIn("kind=alias", "\n".join(cm.output))

    def test_single_module_spec_and_index_longform_do_not_warn(self):
        mods = [self._mod("@web/foo", "/web/static/src/foo/index.js")]
        with self.assertNoLogs(self._LOG, level="WARNING"):
            data = self._data(mods)
        self.assertEqual(data["import_map"]["@web/foo"], "/web/static/src/foo/index.js")
        self.assertEqual(
            data["import_map"]["@web/foo/index"], "/web/static/src/foo/index.js"
        )


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


class TestDebugIncludeImportMap(TransactionCase):
    def test_debug_import_map_has_no_shim_entries(self):
        IrQweb = self.env["ir.qweb"]
        pre, _post = IrQweb._get_native_module_nodes(
            "web.assets_unit_tests_setup", debug="assets"
        )
        import_map = {}
        for _tag, attrs in pre:
            if attrs.get("type") == "importmap":
                import_map = json.loads(attrs["text"])["imports"]
        if not import_map:
            self.skipTest("bundle resolved empty (web assets unavailable)")
        shim_valued = {
            spec: url
            for spec, url in import_map.items()
            if url.startswith(("/web/assets/esm/bridges/", "data:"))
        }
        self.assertFalse(
            shim_valued,
            "debug import map routes specs through odoo.loader.modules shims "
            f"(non-functional in debug): {dict(list(shim_valued.items())[:5])}",
        )


class TestEsmConfigValidation(TransactionCase):
    def test_live_registry_builds_and_validates(self):
        reg = esm_registry()
        self.assertIn("web.assets_web", reg.bundles)
        self.assertIn("point_of_sale._assets_pos", reg.bundles)
        self.assertIn("web_tour.automatic", reg.dynamic_children["web.assets_web"])
        self.assertIn("web.assets_unit_tests", reg.import_map_included_bundles)
        validate_esm_config(
            reg.bundles,
            reg.dynamic_children,
            reg.import_map_includes,
            reg.secondary_import_map_includes,
        )

    def test_dynamic_children_follow_bundle_includes(self):
        reg = esm_registry()
        frontend_children = reg.dynamic_children["web.assets_frontend"]
        self.assertTrue(
            frontend_children,
            "web.assets_frontend must declare dynamic children for this to test anything",
        )

        IrQweb = self.env["ir.qweb"]
        assets_params = self.env["ir.asset"]._get_asset_params()

        parents = IrQweb._get_dynamic_parent_bundles(
            "web.assets_frontend_lazy", assets_params
        )
        self.assertEqual(parents[0], "web.assets_frontend_lazy")
        self.assertIn(
            "web.assets_frontend",
            parents,
            "the include graph of web.assets_frontend_lazy must reach web.assets_frontend",
        )

        resolved = {
            child.name
            for child in IrQweb._get_dynamic_child_bundles(
                "web.assets_frontend_lazy", assets_params, debug_assets=False
            )
        }
        self.assertLessEqual(
            set(frontend_children),
            resolved,
            "children of the included bundle must be built for the includer",
        )

    def test_dynamic_children_are_deduplicated(self):
        IrQweb = self.env["ir.qweb"]
        assets_params = self.env["ir.asset"]._get_asset_params()
        names = [
            child.name
            for child in IrQweb._get_dynamic_child_bundles(
                "web.assets_frontend_lazy", assets_params, debug_assets=False
            )
        ]
        self.assertEqual(len(names), len(set(names)), f"duplicate children: {names}")

    def test_unregistered_secondary_parent_rejected(self):
        with self.assertRaisesRegex(ValueError, "secondary_import_map_includes"):
            validate_esm_config(
                {"web.assets_tests"},
                {},
                {},
                {"not.an_esm_bundle": ["web.assets_tests"]},
            )

    def test_unregistered_secondary_child_rejected(self):
        with self.assertRaisesRegex(ValueError, "not.an_esm_child"):
            validate_esm_config(
                {"web.assets_web"},
                {},
                {},
                {"web.assets_web": ["not.an_esm_child"]},
            )

    def test_duplicate_children_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_esm_config({"p", "c"}, {"p": ["c", "c"]}, {}, {})

    def test_dynamic_and_include_overlap_rejected(self):
        with self.assertRaisesRegex(ValueError, "both"):
            validate_esm_config({"p", "c"}, {"p": ["c"]}, {"p": ["c"]}, {})

    def test_validate_external_libs_follows_esbuild_pattern(self):
        AssetsBundle._validate_external_libs(
            {
                "@odoo/owl": "/web/static/lib/owl/owl.es.js",
                "@odoo/not-listed": "/web/static/lib/owl/owl.es.js",
            },
            bare_specifiers=set(),
        )
        with self.assertRaises(ValueError):
            AssetsBundle._validate_external_libs(
                {"left-pad": "/web/static/lib/owl/owl.es.js"},
                bare_specifiers=set(),
            )


class TestEsmRegistryInstallationScope(TransactionCase):
    """What the registry gates, given that it is built from *disk*, not the DB.

    ``_build`` walks ``Manifest.all_addon_manifests()``, so every addon on the
    addons path contributes whether or not it is installed here. That is a
    deliberate choice, and the safe one *only* while two properties hold: a
    module may not claim a bundle it does not own, and a declaration from an
    absent module must resolve to nothing rather than to something wrong.
    Neither is enforced by ``validate_esm_config``; these pin them.
    """

    def _declarations(self):
        from odoo.modules import Manifest

        for manifest in Manifest.all_addon_manifests():
            esm = manifest.get("esm")
            if esm:
                yield manifest.name, esm

    def _claims_a_live_foreign_namespace(self, module, bundle):
        """Whether *module* registers *bundle* out of another addon's namespace.

        A namespace with no addon behind it is not foreign: ``pos_enterprise``
        registers and fills ``pos_preparation_display.*``, a bundle family whose
        module was folded into it upstream, and there is no other claimant a
        declaration could be stolen from. The rule worth enforcing is narrower
        than "prefix equals declaring module" -- it is that no manifest may
        register a bundle belonging to a *different addon that exists*.
        """
        from odoo.modules import Manifest

        namespace = bundle.partition(".")[0]
        if namespace == module:
            return False
        return Manifest.for_addon(namespace, display_warning=False) is not None

    def test_a_module_only_registers_bundles_it_owns(self):
        """The invariant that makes a disk-wide registry safe, unenforced.

        ``esm.bundles`` entries are merged into one flat set with no check on
        the namespace, so a single manifest anywhere on the addons path can
        register ``web.assets_web`` -- flipping a core bundle to esbuild on
        every database, whether or not either module is installed. Every
        manifest in this workspace is well-behaved today, which is exactly why
        the rule is worth pinning before one is not.
        """
        stolen = [
            (module, bundle)
            for module, esm in self._declarations()
            for bundle in esm.get("bundles", ())
            if self._claims_a_live_foreign_namespace(module, bundle)
        ]

        self.assertFalse(stolen, f"modules registering foreign bundles: {stolen}")

    def test_child_declarations_stay_in_their_namespace(self):
        """Same rule for the relationship mappings' *children*.

        A parent may legitimately be another module's bundle -- that is the
        whole point of ``dynamic_children``, where the child's module declares
        itself against ``web.assets_web``. The child, though, is the thing being
        contributed, and contributing another addon's bundle is the same theft
        as registering it.
        """
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
        """Why a disk-wide registry is survivable, and what it actually costs.

        ``esm_registry.py`` states that membership checks for unavailable
        modules "are simply never asked". They are: ``_get_dynamic_child_bundles``
        builds an ``AssetsBundle`` for every declared child of the rendered
        bundle, including children whose module is not installed here. What
        saves it is one layer down -- ``_get_asset_paths`` resolves those
        bundles against the *installed* addon list, so each yields no files and
        contributes nothing to the import map.

        So the guarantee is real but indirect, and it is the empty result, not
        the absent question, that has to hold.
        """
        registry = esm_registry()
        installed = self.env["ir.asset"]._get_installed_addons_list()
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
            self.env["ir.asset"]._get_asset_params(),
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
    """How far the singleton guarantee of a secondary bundle actually reaches.

    A secondary bundle is esbuild-compiled self-contained, so every module it
    imports transitively is INLINED — a second copy, distinct from the one the
    parent app bundle registered. ``_secondary_shared_specs`` stubs some of
    them back to ``odoo.loader.modules`` so identity survives, which is what
    makes ``patchWithCleanup(browser, …)`` from a tour reach the running app.

    It stubs only what the bundle imports DIRECTLY, so the guarantee stops one
    hop in. These pin the part that holds and measure the part that does not,
    rather than leaving the shortfall to a docstring.
    """

    BUNDLE = "web.assets_tests"
    PARENT = "web.assets_web"

    def _specs(self, bundle):
        return set(
            self.env["ir.qweb"]
            ._get_asset_bundle(bundle, js=True, css=False, assets_params={})
            .get_native_module_data(with_bridges=False)["import_map"]
        )

    def test_every_stubbed_specifier_is_owned_by_the_parent(self):
        """The shim reads the parent's registration, so the parent must have one.

        A stub for a specifier no parent registers would resolve to
        ``undefined`` at eval time and take the importing module down with it.
        """
        shared = self.env["ir.qweb"]._secondary_shared_specs(self.BUNDLE, {})
        if not shared:
            self.skipTest("no shared specifiers on this database")

        self.assertLessEqual(set(shared), self._specs(self.PARENT))

    def test_the_guarantee_stops_at_direct_imports(self):
        """DOCUMENTED SHORTFALL, not an accident of this database.

        Everything the parent owns and this bundle does not stub is inlined a
        second time. Asserted as a property — some parent-owned specifier is
        neither stubbed nor absent — because the count moves with whatever is
        installed; it was 274 against 24 stubs when this was written.

        Tightening ``discovered`` to a transitive walk should make this test
        fail, and that is the signal to delete it.
        """
        shared = set(self.env["ir.qweb"]._secondary_shared_specs(self.BUNDLE, {}))
        if not shared:
            self.skipTest("no shared specifiers on this database")
        parent_specs = self._specs(self.PARENT)
        own_specs = self._specs(self.BUNDLE)

        reachable_unstubbed = (parent_specs - shared) - own_specs

        self.assertTrue(
            reachable_unstubbed,
            "the singleton guarantee now covers the whole parent surface -- "
            "drop this test and the shortfall paragraph in "
            "_secondary_shared_specs",
        )


class TestHootOwnership(TransactionCase):
    """Which bundle owns a specifier decides whether Hoot loads it, not its path.

    Anything Hoot owns is left out of the eager import so ``loadAndStart`` can
    apply the page's ``&id=`` filter first. Anything else has to be imported
    eagerly or it never runs — and a tour that never runs is invisible: the
    registry simply lacks it and the runner reports the ready code as "always
    falsy", naming nothing.
    """

    TOUR_BUNDLE = "web.assets_tests"
    RUNNER_BUNDLE = "web.assets_unit_tests_setup"

    def test_the_tour_bundle_owns_none_of_its_specifiers(self):
        """The regression: a tour outside a ``tours/`` directory.

        ``test_assetsbundle``'s own tour sits directly in ``static/tests``, as
        do ``auth_passkey``'s and a dozen more. Read by directory they all
        looked like Hoot's, so the frontend skipped them.
        """
        IrQweb = self.env["ir.qweb"]
        specs = set(
            IrQweb._get_asset_bundle(
                self.TOUR_BUNDLE, js=True, css=False, assets_params={}
            ).get_native_module_data(with_bridges=False)["import_map"]
        )
        self.assertTrue(specs, "the tour bundle must resolve to something")

        owned = IrQweb._hoot_specifiers(self.TOUR_BUNDLE, specs)

        self.assertFalse(owned, f"Hoot does not own tour-bundle specifiers: {owned}")

    def test_a_suite_is_recognised_by_name_in_any_bundle(self):
        """Name recognition is what keeps a self-contained runner bundle lazy.

        ``im_livechat.embed_assets_unit_tests`` carries suites without
        declaring an import-map relationship, so nothing but the file kind
        identifies them.
        """
        suite = "@im_livechat/../tests/embed/thread.test"

        self.assertEqual(
            self.env["ir.qweb"]._hoot_specifiers("some.standalone_bundle", [suite]),
            [suite],
        )

    def test_a_runner_bundle_still_owns_its_unnamed_helpers(self):
        """The directory reading survives exactly where it is true.

        A runner bundle's helpers (``_framework/*.js``, ``mock_*.hoot.js``) are
        neither suites nor named like them, and eagerly importing them would
        fetch most of the bundle before the ``&id=`` filter is read.
        """
        helper = "@web/../tests/_framework/mock_server/mock_server"

        self.assertEqual(
            self.env["ir.qweb"]._hoot_specifiers(self.RUNNER_BUNDLE, [helper]),
            [helper],
        )

    def test_a_tour_is_never_owned_wherever_it_lives(self):
        tour = "@web/../tests/tours/some_tour"

        self.assertFalse(
            self.env["ir.qweb"]._hoot_specifiers(self.RUNNER_BUNDLE, [tour])
        )


class BridgeRequestBoundCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch("odoo.http.request", new=SimpleNamespace()))


class TestBridgeShimLiterals(TransactionCase):
    NAMES = {"alpha", "class", "default", "a-b"}

    def test_shim_specifier_is_json_quoted(self):
        shim, is_fallback = AssetsBundle._bridge_shim_source(
            "@web/core/x", set(), {"alpha"}, True
        )
        self.assertIn('odoo.loader.modules.get("@web/core/x");', shim)
        self.assertNotIn("get('@web/core/x')", shim)
        self.assertIn("const _e0 = _m?.alpha;", shim)
        self.assertIn("export { _e0 as alpha };", shim)
        self.assertFalse(is_fallback)

    def test_a_reserved_word_survives_as_an_alias(self):
        """``export const class = ...`` is a SyntaxError; the alias form is not.

        An export name only has to be an IdentifierName, so a module really can
        export ``class`` and the bridge really does meet it. Emitted as a
        declaration it would take down the whole shim -- every other name it
        carries included -- which is why the generators bind to a local and
        re-export under an alias.
        """
        shim, _ = AssetsBundle._bridge_shim_source(
            "@web/core/x", set(), self.NAMES, False
        )

        self.assertIn(" as class }", shim)
        self.assertNotIn("const class", shim)
        self.assertNotIn("a-b", shim)
        self.assertNotIn("_m?.default;", shim)

    @unittest.skipUnless(shutil.which("node"), "node binary not available")
    def test_the_two_generators_agree(self):
        """The Python and JS shim generators must emit the same text.

        ``_bridge_shim_source`` builds the server's bridge attachment and
        ``@web/core/module_bridge.buildBridgeModuleSource`` builds the client's
        ``data:`` bridge for the same specifier; the two are interchangeable
        only while they agree, and that contract lived in a docstring. It had
        already drifted once -- this file asserted the pre-alias
        ``export const <name> = ...`` shape that only one side still produced.
        Comparing them directly is what keeps a change to either from being
        silently one-sided.
        """
        bridge_js = file_path("web/static/src/core/module_bridge.js")
        names = sorted(self.NAMES)
        script = (
            f"import {{ buildBridgeModuleSource }} from {json.dumps(bridge_js)};\n"
            f"process.stdout.write("
            f"buildBridgeModuleSource({json.dumps('@web/core/x')}, "
            f"{json.dumps(names)}));\n"
        )

        proc = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        python_shim, _ = AssetsBundle._bridge_shim_source(
            "@web/core/x", set(), self.NAMES, False
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, python_shim)


class TestBridgeHashWidth(BridgeRequestBoundCase):
    def test_bridge_url_hash_is_32_hex(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=True
        ):
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/test_hash": "export default 1;"}
            )
        basename = urls["@web/test_hash"].rsplit("/", 1)[-1]
        self.assertRegex(basename, r"^[0-9a-f]{32}\.js$")


class TestBridgeReadonlyEscalation(BridgeRequestBoundCase):
    def _make_cursor_readonly(self):
        make_cursor_readonly(self)

    def test_escalation_success_returns_canonical_urls(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        self._make_cursor_readonly()
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=True
        ) as escalate:
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/ro_test": "export default 1;"}
            )
        escalate.assert_called_once()
        (to_create,) = escalate.call_args.args
        self.assertEqual(len(to_create), 1)
        self.assertTrue(urls["@web/ro_test"].startswith("/web/assets/esm/bridges/"))

    def test_escalation_failure_falls_back_to_data_uris(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        self._make_cursor_readonly()
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=False
        ) as escalate:
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/ro_test2": "export default 2;"}
            )
        escalate.assert_called_once()
        self.assertTrue(urls["@web/ro_test2"].startswith("data:text/javascript"))


class TestBridgePersistenceDecoupled(BridgeRequestBoundCase):
    def test_writable_cursor_routes_through_rw_cursor(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        self.assertFalse(
            self.env.cr.readonly, "precondition: the request cursor is writable"
        )
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=True
        ) as escalate:
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/decoupled": "export const decoupled = 1;"}
            )
        escalate.assert_called_once()
        url = urls["@web/decoupled"]
        self.assertTrue(
            url.startswith("/web/assets/esm/bridges/"),
            "a successful out-of-band persist yields a canonical URL",
        )
        self.assertFalse(
            url.startswith("data:"), "the writable path must not inline data: URIs"
        )

    def test_unwritable_primary_falls_back_to_data_uris(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=False
        ):
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/degraded": "export const degraded = 2;"}
            )
        self.assertTrue(
            urls["@web/degraded"].startswith("data:text/javascript"),
            "data: URIs are reserved for a genuinely unwritable primary",
        )


class TestBridgeNoRequestPersistence(TransactionCase):
    def test_no_request_persists_on_current_cursor(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor"
        ) as escalate:
            urls = bundle._bridges._persist_bridge_shims(
                {"@web/no_request": "export const no_request = 3;"}
            )
        escalate.assert_not_called()
        url = urls["@web/no_request"]
        self.assertTrue(
            url.startswith("/web/assets/esm/bridges/"),
            "current-cursor persistence still yields canonical URLs",
        )
        attachment = self.env["ir.attachment"].sudo().search([("url", "=", url)])
        self.assertTrue(
            attachment,
            "the bridge row must be visible on the current cursor",
        )


class TestEsbuildCompilerAddonFlagsSeam(BaseCase):
    def test_provider_is_threaded_into_compiler(self):
        def sentinel(root):
            return (["--alias:x=y"], [])

        fake = SimpleNamespace(
            name="some.bundle",
            native_modules=[],
            javascripts=[],
            _get_esbuild_addon_flags=sentinel,
        )
        compiler = AssetsBundle._make_esbuild_compiler(fake)
        self.assertIs(compiler._addon_flags_provider, sentinel)


class TestSecondaryStubMirror(BaseCase):
    """A stubbed specifier must not swallow the submodules beneath it.

    ``--alias`` is a prefix rewrite, so aliasing ``@web/core/network`` straight
    at a shim file remapped ``@web/core/network/model_mutation`` to
    ``<shim>.js/model_mutation`` and esbuild refused the bundle outright. A
    module face sitting beside its own directory is the normal shape in this
    codebase, so the mirror has to keep the prefix meaningful.
    """

    FACE = "@probe/core/network"
    NESTED = "@probe/core/network/rpc"
    SIBLING = "@probe/core/network/model_mutation"

    def _build_mirror(self, tmp):
        odoo_root = Path(tmp)
        real = odoo_root / "addons" / "probe" / "static" / "src" / "core"
        (real / "network").mkdir(parents=True)
        (real / "network.js").write_text("export const face = 'REAL_FACE';")
        (real / "network" / "rpc.js").write_text("export const rpc = 'REAL_RPC';")
        (real / "network" / "model_mutation.js").write_text(
            "export const sub = 'REAL_SUB';"
        )
        stub_root = odoo_root / "stubs"
        flags = EsbuildCompiler._write_stub_mirror(
            stub_root,
            {
                self.FACE: "export const face = 'SHIM_FACE';",
                self.NESTED: "export const rpc = 'SHIM_RPC';",
            },
            ["--alias:@probe=./addons/probe/static/src"],
            odoo_root,
        )
        return stub_root, real, {f.split("=")[0]: f.split("=", 1)[1] for f in flags}

    def test_the_alias_target_leaves_room_for_submodules(self):
        """Extensionless, so the sibling directory can answer the prefix.

        Resolution prefers ``network.js`` over the ``network/`` directory, so
        the face still gets the shim while ``network/...`` stays a real path.
        """
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, _real, targets = self._build_mirror(tmp)

            target = targets[f"--alias:{self.FACE}"]
            self.assertEqual(target, str(stub_root / "probe" / "core" / "network"))
            self.assertFalse(target.endswith(".js"))
            self.assertEqual(
                (stub_root / "probe/core/network.js").read_text(),
                "export const face = 'SHIM_FACE';",
            )

    def test_an_unstubbed_submodule_still_reaches_the_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, _real, _targets = self._build_mirror(tmp)

            mirrored = stub_root / "probe/core/network/model_mutation.js"

            self.assertTrue(mirrored.exists())
            self.assertEqual(mirrored.read_text(), "export const sub = 'REAL_SUB';")

    def test_a_nested_stub_shadows_without_writing_through(self):
        """The failure mode a whole-directory symlink would have caused.

        With ``network/`` symlinked to the source tree, writing the nested
        shim at ``network/rpc.js`` would follow the link and overwrite the real
        module on disk. The directory is rebuilt entry by entry instead, so the
        shim lands only in the mirror.
        """
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, real, _targets = self._build_mirror(tmp)

            self.assertEqual(
                (stub_root / "probe/core/network/rpc.js").read_text(),
                "export const rpc = 'SHIM_RPC';",
            )
            self.assertEqual(
                (real / "network" / "rpc.js").read_text(),
                "export const rpc = 'REAL_RPC';",
            )

    @unittest.skipUnless(_find_esbuild(), "esbuild binary not available")
    def test_esbuild_resolves_face_and_submodule_together(self):
        """The end the whole mirror exists for, driven through esbuild itself.

        Asserting the layout is not the same as asserting esbuild agrees with
        it -- the original bug was precisely a wrong belief about what esbuild
        does with an alias.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _stub_root, _real, targets = self._build_mirror(tmp)
            entry = Path(tmp) / "entry.js"
            entry.write_text(
                f"import {{ face }} from '{self.FACE}';\n"
                f"import {{ sub }} from '{self.SIBLING}';\n"
                f"import {{ rpc }} from '{self.NESTED}';\n"
                "console.log(face, sub, rpc);\n"
            )

            proc = subprocess.run(
                [
                    _find_esbuild(),
                    str(entry),
                    "--bundle",
                    "--format=esm",
                    "--alias:@probe=./addons/probe/static/src",
                    *(f"{spec}={target}" for spec, target in targets.items()),
                ],
                capture_output=True,
                text=True,
                cwd=tmp,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("SHIM_FACE", proc.stdout)
            self.assertIn("REAL_SUB", proc.stdout)
            self.assertIn("SHIM_RPC", proc.stdout)


class TestDeepStubMirror(BaseCase):
    """A stub more than one level below another must not reach the source tree.

    `TestSecondaryStubMirror` pins the one-level case, and shadowing by
    immediate parent passed it while protecting nothing deeper: a stub at
    ``<face>/<dir>/<name>`` is not a child of the face, so the face's sibling
    directory was symlinked whole and the shim write followed that link out of
    the mirror. That overwrote 42 modules under
    ``addons/spreadsheet/static/src`` and 39 under
    ``spreadsheet_edition/static/src/bundle`` with their own shims, from a
    plain secondary-bundle compile. The shape is ordinary rather than exotic --
    a plugin directory beside a module face -- so it is pinned at depth.
    """

    FACE = "@probe/core/network"
    DEEP = "@probe/core/network/plugins/core"

    def _build_mirror(self, tmp):
        odoo_root = Path(tmp)
        real = odoo_root / "addons" / "probe" / "static" / "src" / "core"
        (real / "network" / "plugins").mkdir(parents=True)
        (real / "network.js").write_text("export const face = 'REAL_FACE';")
        (real / "network" / "rpc.js").write_text("export const rpc = 'REAL_RPC';")
        (real / "network" / "plugins" / "core.js").write_text(
            "export const core = 'REAL_DEEP';"
        )
        (real / "network" / "plugins" / "other.js").write_text(
            "export const other = 'REAL_OTHER';"
        )
        stub_root = odoo_root / "stubs"
        EsbuildCompiler._write_stub_mirror(
            stub_root,
            {
                self.FACE: "export const face = 'SHIM_FACE';",
                self.DEEP: "export const core = 'SHIM_DEEP';",
            },
            ["--alias:@probe=./addons/probe/static/src"],
            odoo_root,
        )
        return stub_root, real

    def test_a_deeply_nested_stub_does_not_overwrite_the_real_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            _stub_root, real = self._build_mirror(tmp)

            self.assertEqual(
                (real / "network" / "plugins" / "core.js").read_text(),
                "export const core = 'REAL_DEEP';",
                "the shim was written through a symlink into the source tree",
            )

    def test_the_deeply_nested_shim_still_lands_in_the_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, _real = self._build_mirror(tmp)

            self.assertEqual(
                (stub_root / "probe/core/network/plugins/core.js").read_text(),
                "export const core = 'SHIM_DEEP';",
            )

    def test_unstubbed_neighbours_at_every_depth_reach_the_real_files(self):
        """The rebuild has to stay transparent, or it trades one bug for another.

        Rebuilding a directory entry by entry is only correct while every entry
        no shim claims still resolves -- at the rebuilt level and at the one
        below it, which the recursion newly rebuilds too.
        """
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, _real = self._build_mirror(tmp)

            for rel, expected in (
                ("probe/core/network/rpc.js", "export const rpc = 'REAL_RPC';"),
                (
                    "probe/core/network/plugins/other.js",
                    "export const other = 'REAL_OTHER';",
                ),
            ):
                with self.subTest(rel=rel):
                    self.assertEqual((stub_root / rel).read_text(), expected)

    def test_a_write_that_escapes_the_mirror_raises(self):
        """The backstop, exercised directly rather than through a live escape.

        Every escape this guard exists for is a layout bug that has not been
        thought of yet, so the test cannot reproduce one; it can only pin that
        a path resolving outside the mirror is refused instead of written.
        """
        with tempfile.TemporaryDirectory() as tmp:
            stub_root = Path(tmp) / "stubs"
            outside = Path(tmp) / "source"
            outside.mkdir()
            stub_root.mkdir()
            (stub_root / "leaked").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(RuntimeError) as caught:
                EsbuildCompiler._ensure_inside_mirror(
                    stub_root / "leaked" / "module.js", stub_root
                )
            self.assertIn("outside the stub mirror", str(caught.exception))


class TestEsbuildFailClosed(TransactionCase):
    """An esbuild failure degrades for users and raises for developers.

    Serving an empty bundle keeps a production page alive, and hides the cause
    everywhere else: the response is still 200, the only trace is a WARNING,
    and the symptom surfaces as unrelated failures (a missing service, absent
    translations) far from the broken import that caused them.
    """

    def _run(self, **config):
        """Drive the failure branch with `config` patched over tools.config."""
        from odoo.addons.base.models.ir_qweb_assets import EsbuildBundleError

        qweb = self.env["ir.qweb"]
        patched = dict(tools.config._runtime_options)
        patched.update(config)
        with patch.dict(tools.config._runtime_options, patched, clear=False):
            return qweb._esbuild_fail_closed(), EsbuildBundleError

    def test_test_enable_fails_closed(self):
        """`--test-enable`: somebody is watching, so do not degrade."""
        fail_closed, _ = self._run(test_enable=True, dev_mode=[])
        self.assertTrue(fail_closed)

    def test_dev_assets_fails_closed(self):
        """`--dev=assets`: likewise."""
        fail_closed, _ = self._run(test_enable=False, dev_mode=["assets"])
        self.assertTrue(fail_closed)

    def test_production_still_degrades(self):
        """Plain server: a degraded page beats a 500 for a user."""
        fail_closed, _ = self._run(test_enable=False, dev_mode=[])
        self.assertFalse(fail_closed)

    def test_unrelated_dev_mode_still_degrades(self):
        """`--dev=xml` says nothing about assets."""
        fail_closed, _ = self._run(test_enable=False, dev_mode=["xml", "reload"])
        self.assertFalse(fail_closed)

    def test_config_parameter_overrides_both_ways(self):
        """`web.esbuild.fail_closed` wins over the inferred default.

        The escape hatch matters in both directions: a test run that has to
        survive a known-broken bundle can opt out, and a staging server can opt
        in without pretending to be a test.
        """
        param = self.env["ir.config_parameter"].sudo()
        param.set_param("web.esbuild.fail_closed", "0")
        fail_closed, _ = self._run(test_enable=True, dev_mode=["assets"])
        self.assertFalse(fail_closed, "explicit 0 must disable it under --test-enable")

        param.set_param("web.esbuild.fail_closed", "1")
        fail_closed, _ = self._run(test_enable=False, dev_mode=[])
        self.assertTrue(fail_closed, "explicit 1 must enable it on a plain server")


NATIVE_BUNDLE = "test_assetsbundle.native_esm"
NATIVE_DEP = "@test_assetsbundle/../tests/native_esm/dep"
NATIVE_ENTRY = "@test_assetsbundle/../tests/native_esm/entry"
NATIVE_REEXPORT = "@test_assetsbundle/../tests/native_esm/reexport"


@unittest.skipUnless(_find_esbuild(), "esbuild binary not available")
class TestEsbuildEndToEnd(TransactionCase):
    """esbuild driven for real, over files that exist on disk.

    Everything else in this file tests the plumbing AROUND the compiler -- the
    import map it feeds, the stub mirror it reads, the flags it is handed --
    by asserting on inputs or by shelling out to the binary directly. None of
    it enters `EsbuildCompiler.compile`, which was measurable: instrumenting
    that method showed zero calls across the whole at_install phase, and the
    only ones in a full run came from the framework pregenerating bundles and
    from a browser fetching a page. The compiler is the single most
    consequential thing in this layer and nothing here exercised it.

    `test_assetsbundle.native_esm` exists for this: three real modules under
    static/tests/native_esm/, registered as an esbuild bundle in the manifest,
    so the compiler resolves genuine imports off genuine paths.
    """

    def _bundle(self):
        return self.env["ir.qweb"]._get_asset_bundle(
            NATIVE_BUNDLE, css=False, assets_params={}
        )

    def test_the_fixture_bundle_routes_to_native_modules(self):
        """Precondition: without esm registration these would be legacy JS."""
        bundle = self._bundle()
        self.assertEqual(
            sorted(a.module_path for a in bundle.native_modules),
            [NATIVE_DEP, NATIVE_ENTRY, NATIVE_REEXPORT],
        )
        self.assertFalse(bundle.javascripts)

    def test_a_registered_bundle_compiles_and_resolves_its_imports(self):
        result = self._bundle().esbuild_native_bundle()

        self.assertTrue(result.code, "esbuild produced no output")
        self.assertNotRegex(
            result.code,
            r'(^|[;\s])import\s*[{"\']',
            "a bare import survived bundling, so a specifier went unresolved",
        )
        self.assertIn("41", result.code, "the imported constant must be inlined")

    def test_the_metafile_accounts_for_every_member(self):
        result = self._bundle().esbuild_native_bundle()

        self.assertTrue(result.metafile, "no metafile: the GC sidecar has no input")
        inputs = json.loads(result.metafile)["inputs"]
        for name in ("dep.js", "entry.js", "reexport.js"):
            self.assertTrue(
                any(name in path for path in inputs),
                f"{name} is a bundle member but absent from the metafile",
            )

    def test_two_compiles_of_the_same_sources_agree(self):
        """Byte-stability is what lets the content hash address the bundle."""
        first = self._bundle().esbuild_native_bundle()
        second = self._bundle().esbuild_native_bundle()
        self.assertEqual(first.code, second.code)


class TestEsbuildFailurePath(TransactionCase):
    """What happens when the compiler raises -- the branch, not the predicate.

    TestEsbuildFailClosed covers `_esbuild_fail_closed()` as a function. This
    covers the caller: that a raising compile really does become an
    EsbuildBundleError when the flag says so, and really does degrade to an
    empty result when it does not.

    Steered through the `web.esbuild.fail_closed` config parameter rather than
    tools.config, deliberately: config.options is a ChainMap, and patching it
    is a trap (see test_css_pipeline's dev-mode memo test).
    """

    def setUp(self):
        super().setUp()
        # The breaker is class-level state on ir.qweb and survives the
        # transaction rollback, so one test recording a failure would put the
        # next one down the `circuit_blocked` branch, where the compiler is
        # never called and nothing can raise.
        IrQweb = type(self.env["ir.qweb"])
        cooldowns = IrQweb._esbuild_cooldowns
        self.addCleanup(cooldowns.update, dict(cooldowns))
        self.addCleanup(cooldowns.clear)
        cooldowns.clear()

    def _run_with_broken_compiler(self, fail_closed):
        self.env["ir.config_parameter"].sudo().set_param(
            "web.esbuild.fail_closed", "1" if fail_closed else "0"
        )
        asset_bundle = self.env["ir.qweb"]._get_asset_bundle(
            NATIVE_BUNDLE, css=False, assets_params={}
        )
        with patch.object(
            type(asset_bundle),
            "esbuild_native_bundle",
            side_effect=RuntimeError("esbuild exploded"),
        ):
            return self.env["ir.qweb"]._esm_run_esbuild(NATIVE_BUNDLE, asset_bundle, {})

    def test_a_compile_failure_raises_when_fail_closed(self):
        from odoo.addons.base.models.ir_qweb_assets import EsbuildBundleError

        with self.assertLogs("odoo.assets.fallback", level="WARNING"):
            with self.assertRaises(EsbuildBundleError) as caught:
                self._run_with_broken_compiler(fail_closed=True)
        self.assertIn(NATIVE_BUNDLE, str(caught.exception))
        self.assertIn("esbuild exploded", str(caught.exception))

    def test_a_compile_failure_degrades_when_not_fail_closed(self):
        with self.assertLogs("odoo.assets.fallback", level="WARNING"):
            result, _children = self._run_with_broken_compiler(fail_closed=False)
        self.assertEqual(result.code, "")
        self.assertIsNone(result.metafile)


class TestEsmSpecifierResolution(BaseCase):
    """`@addon/path` <-> `/addon/static/...`, and relative imports between them.

    Every bridge, stub and import-map entry is keyed on a specifier, so a
    resolution that is merely plausible produces a shim for a module nobody
    imports and no shim for the one that needed it.
    """

    def _resolver(self, ext_libs=None, lib_candidates=None):
        from odoo.tools.assets.esm_graph import _BridgeExportResolver

        return _BridgeExportResolver(ext_libs or {}, lib_candidates or {}, "test")

    def test_a_bare_specifier_only_loses_its_extension(self):
        from odoo.tools.assets.esm_graph import _resolve_export_specifier

        self.assertEqual(
            _resolve_export_specifier("@web/core/a", "@web/other/b.js"),
            "@web/other/b",
        )

    def test_relative_specifiers_resolve_against_the_importer(self):
        from odoo.tools.assets.esm_graph import _resolve_export_specifier

        self.assertEqual(
            _resolve_export_specifier("@web/core/a/b", "./c.js"), "@web/core/a/c"
        )
        self.assertEqual(
            _resolve_export_specifier("@web/core/a/b", "../c"), "@web/core/c"
        )

    def test_a_relative_import_with_no_importer_is_unresolvable(self):
        from odoo.tools.assets.esm_graph import _resolve_export_specifier

        self.assertIsNone(_resolve_export_specifier(None, "./c"))
        self.assertIsNone(_resolve_export_specifier("toplevel", "./c"))

    def test_the_three_static_roots_each_have_their_own_shape(self):
        resolve = self._resolver().resolve_url
        self.assertEqual(
            resolve("@web/core/registry"), "/web/static/src/core/registry.js"
        )
        self.assertEqual(resolve("@web/../lib/y"), "/web/static/lib/y.js")
        self.assertEqual(resolve("@web/../tests/x"), "/web/static/tests/x.js")

    def test_declared_libraries_win_over_the_addon_layout(self):
        resolve = self._resolver(
            ext_libs={"@odoo/owl": "/web/static/lib/owl/owl.es.js"},
            lib_candidates={"@odoo/hoot": ("web", "static", "lib", "hoot", "hoot.js")},
        ).resolve_url
        self.assertEqual(resolve("@odoo/owl"), "/web/static/lib/owl/owl.es.js")
        self.assertEqual(resolve("@odoo/hoot"), "/web/static/lib/hoot/hoot.js")

    def test_a_non_addon_specifier_resolves_to_nothing(self):
        resolve = self._resolver().resolve_url
        self.assertIsNone(resolve("left-pad"))
        self.assertIsNone(resolve("@"))


class TestEsmExportExtraction(BaseCase):
    """`export * from` has to be followed, or the bridge under-reports names.

    A shim only re-exports what extraction found; a name it misses is not a
    degraded import but `undefined` at the call site.
    """

    @staticmethod
    def _extract(src, source_map=None, importer="@w/leaf"):
        from odoo.tools.assets.esm_graph import _extract_esm_exports

        return _extract_esm_exports(
            src, source_map=source_map, importing_specifier=importer
        )

    def test_star_reexports_are_expanded_through_the_source_map(self):
        names, _ = self._extract(
            "export * from './base';\nexport const C = 3;\n",
            source_map={"@w/base": "export const A = 1;\nexport const B = 2;\n"},
        )
        self.assertEqual(names, {"A", "B", "C"})

    def test_a_star_target_absent_from_the_map_is_skipped_not_fatal(self):
        names, _ = self._extract(
            "export * from './missing';\nexport const C = 3;\n", source_map={}
        )
        self.assertEqual(names, {"C"})

    def test_a_cycle_of_star_reexports_terminates(self):
        source_map = {
            "@w/a": "export * from './b';\nexport const A = 1;\n",
            "@w/b": "export * from './a';\nexport const B = 2;\n",
        }
        names, _ = self._extract(source_map["@w/a"], source_map, importer="@w/a")
        self.assertEqual(names, {"A", "B"})

    def test_a_default_export_is_reported_apart_from_the_names(self):
        names, has_default = self._extract("export default 1;\nexport const A = 2;\n")
        self.assertEqual(names, {"A"})
        self.assertTrue(has_default)
        _names, has_default = self._extract("export const A = 2;\n")
        self.assertFalse(has_default)


class TestBridgeExportResolverReadsDisk(BaseCase):
    """The resolver's other half: actually reading the module it resolved.

    The memoisation of this was already pinned by seeding the cache by hand,
    which tested the memo and skipped the read. These drive the read.
    """

    def _resolver(self):
        from odoo.tools.assets.esm_graph import _BridgeExportResolver

        return _BridgeExportResolver({}, {}, "test")

    def test_a_real_module_yields_its_real_exports(self):
        names, _has_default = self._resolver().source_exports("@web/core/registry")
        self.assertIn("registry", names)
        self.assertIn("Registry", names)

    def test_a_directory_specifier_falls_back_to_its_index(self):
        source = self._resolver().read_source(
            "@test_assetsbundle/../tests/native_esm/faced"
        )
        self.assertIsNotNone(
            source, "a face with no .js must fall back to <spec>/index.js"
        )
        self.assertIn("FACED", source)

    def test_an_unresolvable_specifier_degrades_to_no_exports(self):
        resolver = self._resolver()
        with self.assertLogs("odoo.assets.bridge", level="WARNING"):
            names, has_default = resolver.source_exports("@web/definitely/not/here")
        self.assertEqual(names, set())
        self.assertFalse(has_default)

    def test_the_read_is_memoised_including_the_miss(self):
        resolver = self._resolver()
        with self.assertLogs("odoo.assets.bridge", level="WARNING") as logged:
            for _ in range(3):
                resolver.read_source("@web/definitely/not/here")
        self.assertEqual(len(logged.output), 1, "a miss must be cached, not re-read")


class _Mod:
    """Minimal stand-in for a native module asset."""

    def __init__(self, module_path, raw_content, url=""):
        self.module_path = module_path
        self.raw_content = raw_content
        self.url = url


class TestEscapingRelativeImports(BaseCase):
    """A relative import that leaves the bundle is a singleton split.

    Per-file delivery resolves relative imports against the member's URL, with
    no import map in the way, so an import that lands outside the bundle
    fetches raw source instead of the parent's registered instance.
    """

    def _escapes(self, modules):
        from odoo.tools.assets.esm_graph import find_escaping_relative_imports

        return find_escaping_relative_imports(modules)

    def test_an_import_that_stays_inside_the_bundle_is_not_an_escape(self):
        modules = [
            _Mod("@a/one", "import { x } from './two';\n"),
            _Mod("@a/two", "export const x = 1;\n"),
        ]
        self.assertEqual(self._escapes(modules), [])

    def test_an_import_that_leaves_the_bundle_is_reported(self):
        modules = [_Mod("@a/deep/one", "import { x } from '../../outside/thing';\n")]
        self.assertEqual(
            self._escapes(modules),
            [("@a/deep/one", "../../outside/thing", "@a/outside/thing")],
        )

    def test_a_bare_specifier_is_never_an_escape(self):
        modules = [_Mod("@a/one", "import { x } from '@web/core/registry';\n")]
        self.assertEqual(self._escapes(modules), [])

    def test_an_index_member_answers_its_long_form_too(self):
        modules = [
            _Mod("@a/one", "import { x } from './two';\n"),
            _Mod("@a/two", "export const x = 1;\n", url="/a/static/src/two/index.js"),
        ]
        self.assertEqual(self._escapes(modules), [])


class TestTransitiveSpecifierDiscovery(BaseCase):
    """Bridge discovery has to follow imports, not just read the top level.

    A specifier reachable only through another module still needs a shim; the
    first one missed fails at runtime with "Failed to resolve module
    specifier" and names nothing useful.
    """

    def _discover(self, seeds, known=()):
        from odoo.tools.assets.esm_graph import discover_transitive_import_specifiers

        return discover_transitive_import_specifiers(seeds, set(known), {}, {}, "test")

    def test_a_specifier_reached_through_another_module_is_found(self):
        found = self._discover(["@web/core/registry"])
        self.assertTrue(
            found, "registry imports other @web modules; none were discovered"
        )
        self.assertTrue(all(spec.startswith("@") for spec in found))

    def test_already_known_specifiers_are_not_reported_again(self):
        first = self._discover(["@web/core/registry"])
        self.assertNotIn(
            "@web/core/registry",
            first,
            "a seed is scanned, not discovered",
        )
        again = self._discover(["@web/core/registry"], known=first)
        self.assertEqual(again, set())

    def test_an_unreadable_seed_yields_nothing_instead_of_raising(self):
        with self.assertLogs("odoo.assets.bridge", level="WARNING"):
            self.assertEqual(self._discover(["@web/nope/nope"]), set())


class TestBridgeShimSources(TransactionCase):
    """`build_shim_sources` is what a secondary bundle stubs its parent with."""

    def _manager(self):
        return AssetsBundle("web.assets_web", [], env=self.env)._bridges

    def test_a_shim_re_exports_the_real_module_names(self):
        shims = self._manager().build_shim_sources({"@web/core/registry"})
        shim = shims["@web/core/registry"]
        self.assertIn('odoo.loader.modules.get("@web/core/registry")', shim)
        self.assertRegex(
            shim,
            r"const (_e\d+) = _m\?\.registry;",
            "the shim must bind each name to a local before re-exporting it",
        )
        self.assertRegex(shim, r"_e\d+ as registry\b")

    def test_no_specifiers_means_no_work(self):
        self.assertEqual(self._manager().build_shim_sources(set()), {})

    def test_discovery_reads_the_import_kind_not_just_the_specifier(self):
        modules = [
            _Mod("@a/one", 'import def from "@web/core/a";\n'),
            _Mod("@a/two", 'import * as ns from "@web/core/b";\n'),
            _Mod("@a/three", 'import { named } from "@web/core/c";\n'),
        ]
        discovered, ext_seen = self._manager()._discover_bridge_specifiers(
            set(), set(), modules=modules
        )
        self.assertEqual(discovered["@web/core/a"], {"__default__"})
        self.assertEqual(discovered["@web/core/b"], {"__star__"})
        self.assertEqual(discovered["@web/core/c"], set())
        self.assertEqual(ext_seen, set())

    def test_a_bundle_member_is_not_bridged_to_itself(self):
        modules = [_Mod("@a/one", 'import { x } from "@a/two";\n')]
        discovered, _ext = self._manager()._discover_bridge_specifiers(
            {"@a/two"}, set(), modules=modules
        )
        self.assertNotIn("@a/two", discovered)

    def test_an_external_library_is_recorded_but_not_bridged(self):
        modules = [_Mod("@a/one", 'import { App } from "@odoo/owl";\n')]
        discovered, ext_seen = self._manager()._discover_bridge_specifiers(
            set(), {"@odoo/owl"}, modules=modules
        )
        self.assertNotIn("@odoo/owl", discovered)
        self.assertEqual(ext_seen, {"@odoo/owl"})


class TestLexerWorkerDegradation(BaseCase):
    """How the es-module-lexer worker gives up, and how quietly.

    `lex_module` returning None is not an error: callers fall back to the
    regex extractor, which is not comment-proof. So every path that disables
    the worker trades correctness for availability silently, and the only
    thing standing between "node is missing" and "an `export` inside a comment
    is treated as a real export" is that this degradation is deliberate and
    bounded. These pin the state machine that bounds it.

    A private instance is used throughout: the module-level `_worker` is
    process-global, and flipping its `_disabled` flag would leave every later
    suite on the regex path.
    """

    def _worker(self):
        from odoo.tools.assets.esm_lexer import _LexerWorker

        return _LexerWorker()

    def test_a_worker_that_cannot_spawn_disables_itself_once(self):
        from odoo.tools.assets import esm_lexer

        worker = self._worker()
        with patch.object(esm_lexer._LexerWorker, "_spawn", return_value=None):
            with self.assertLogs("odoo.assets.lexer", level="INFO") as logged:
                self.assertIsNone(worker.request("export const a = 1;"))
            self.assertIsNone(worker.request("export const a = 1;"))
        self.assertIn("worker_unavailable", "\n".join(logged.output))
        self.assertEqual(len(logged.output), 1, "the notice must not repeat per call")
        self.assertTrue(worker._disabled)

    def test_a_desynchronised_reply_is_retried_then_gives_up(self):
        from odoo.tools.assets import esm_lexer

        worker = self._worker()
        alive = SimpleNamespace(poll=lambda: None)
        with (
            patch.object(esm_lexer._LexerWorker, "_spawn", return_value=alive),
            patch.object(esm_lexer._LexerWorker, "_write_all"),
            patch.object(esm_lexer._LexerWorker, "_kill"),
            patch.object(
                esm_lexer._LexerWorker,
                "_read_line",
                return_value=json.dumps({"id": -1, "ok": True}),
            ),
            self.assertLogs("odoo.assets.lexer", level="DEBUG") as logged,
        ):
            self.assertIsNone(worker.request("export const a = 1;"))

        attempts = [ln for ln in logged.output if "worker_request_failed" in ln]
        self.assertEqual(len(attempts), 2, "one retry, then disabled")
        self.assertTrue(worker._disabled)
        self.assertIn("disabled=True", attempts[-1])

    def test_a_transient_failure_does_not_disable_the_worker(self):
        from odoo.tools.assets import esm_lexer

        worker = self._worker()
        alive = SimpleNamespace(poll=lambda: None)
        replies = [
            json.dumps({"id": -1, "ok": True}),
            json.dumps(
                {"id": 2, "ok": True, "imports": [], "names": [], "starFrom": []}
            ),
        ]
        with (
            patch.object(esm_lexer._LexerWorker, "_spawn", return_value=alive),
            patch.object(esm_lexer._LexerWorker, "_write_all"),
            patch.object(esm_lexer._LexerWorker, "_kill"),
            patch.object(esm_lexer._LexerWorker, "_read_line", side_effect=replies),
            self.assertLogs("odoo.assets.lexer", level="DEBUG"),
        ):
            response = worker.request("export const a = 1;")

        self.assertIsNotNone(response, "the retry must be allowed to succeed")
        self.assertFalse(worker._disabled)
        self.assertEqual(worker._consec_failures, 0, "the counter must reset")

    def test_source_the_worker_cannot_lex_is_not_a_worker_failure(self):
        from odoo.tools.assets import esm_lexer

        worker = self._worker()
        alive = SimpleNamespace(poll=lambda: None)
        with (
            patch.object(esm_lexer._LexerWorker, "_spawn", return_value=alive),
            patch.object(esm_lexer._LexerWorker, "_write_all"),
            patch.object(
                esm_lexer._LexerWorker,
                "_read_line",
                return_value=json.dumps({"id": 1, "ok": False, "error": "bad syntax"}),
            ),
            self.assertLogs("odoo.assets.lexer", level="DEBUG") as logged,
        ):
            self.assertIsNone(worker.request("this is not javascript {"))

        self.assertIn("source_unlexable", "\n".join(logged.output))
        self.assertFalse(
            worker._disabled, "one unparseable file must not blind the whole run"
        )

    @unittest.skipUnless(shutil.which("node"), "node binary not available")
    def test_the_real_worker_lexes_a_module(self):
        """The other side of the contract: when it works, it really works.

        `imports` and `starFrom` are DISJOINT -- a re-export is reported only
        under starFrom, never as an import. Every caller that wants "what does
        this file depend on" therefore has to union the two, and one that reads
        `imports` alone silently misses every `export * from`.
        """
        response = self._worker().request(
            "import { a } from '@x/y';\nexport const b = 1;\nexport * from '@x/z';\n"
        )
        if response is None:
            self.skipTest("es-module-lexer worker unavailable (npm install?)")
        self.assertEqual([imp["n"] for imp in response["imports"]], ["@x/y"])
        self.assertEqual(response["starFrom"], ["@x/z"])
        self.assertIn("b", response["names"])

    @unittest.skipUnless(shutil.which("node"), "node binary not available")
    def test_the_union_of_both_lists_is_what_discovery_uses(self):
        """Guards the disjointness above against a caller that forgets it."""
        from odoo.tools.assets.esm_graph import _scan_import_specifiers

        specs = _scan_import_specifiers(
            "import { a } from '@x/y';\nexport * from '@x/z';\n"
        )
        self.assertEqual(specs, {"@x/y", "@x/z"})


class TestParentSelfBridge(TransactionCase):
    """A bundle bridging its OWN modules, for the sake of everyone else's.

    A secondary bundle stubs the parent's specifiers so that
    `patchWithCleanup(browser, …)` from a tour reaches the same instance the
    running app holds. That only works if the parent has published a shim per
    specifier it owns, which is what this builds -- one shim per native module,
    keyed on the module's own path.

    It differs from the native-to-legacy bridge in what it reads: exports come
    from the bundle's own sources rather than from disk, so `export * from` a
    sibling has to be resolved through the in-memory source map.
    """

    def _manager(self, *modules):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        manager = bundle._bridges
        manager.native_modules = list(modules)
        return manager

    def test_every_owned_specifier_gets_a_shim(self):
        manager = self._manager(
            _Mod("@a/one", "export const ONE = 1;\n"),
            _Mod("@a/two", "export const TWO = 2;\n"),
        )
        with self.assertLogs("odoo.assets.bridge", level="DEBUG"):
            bridges = manager._build_parent_self_bridge()

        self.assertEqual(sorted(bridges), ["@a/one", "@a/two"])
        self.assertTrue(
            all(
                url.startswith(("data:", "/web/assets/esm/bridges/"))
                for url in bridges.values()
            )
        )

    def test_a_star_reexport_is_resolved_from_the_bundle_not_from_disk(self):
        """The sibling exists only in this bundle, so disk cannot answer."""
        manager = self._manager(
            _Mod("@a/base", "export const A = 1;\nexport const B = 2;\n"),
            _Mod("@a/face", "export * from './base';\nexport const C = 3;\n"),
        )
        captured = {}
        with (
            patch.object(
                type(manager),
                "_persist_bridge_shims",
                lambda _self, shims: captured.update(shims) or {},
            ),
            self.assertLogs("odoo.assets.bridge", level="DEBUG"),
        ):
            manager._build_parent_self_bridge()

        shim = captured["@a/face"]
        for name in ("A", "B", "C"):
            self.assertRegex(shim, rf"_e\d+ as {name}\b", f"{name} missing")

    def test_a_relative_specifier_is_not_bridged(self):
        """Only bare `@…` specifiers are addressable through the loader."""
        manager = self._manager(
            _Mod("@a/one", "export const ONE = 1;\n"),
            _Mod("../legacy/thing", "export const X = 1;\n"),
        )
        with self.assertLogs("odoo.assets.bridge", level="DEBUG"):
            bridges = manager._build_parent_self_bridge()

        self.assertEqual(list(bridges), ["@a/one"])

    def test_no_native_modules_means_no_bridges(self):
        manager = self._manager()
        self.assertEqual(manager._build_parent_self_bridge(), {})


class TestBridgeDiscoveryWithoutTheLexer(BaseCase):
    """Discovery must survive the es-module-lexer being unavailable.

    `lex_module` returns None whenever node is missing or the worker has
    disabled itself, and discovery then falls back to `_IMPORT_ANY_RE`. That
    fallback decides which specifiers get a bridge, so a shape it fails to
    recognise is a module that resolves to nothing at runtime -- and until now
    only the lexer path was exercised, because this checkout has node.
    """

    def _discover(self, source, native=(), ext=()):
        from odoo.tools.assets import esm_bridges

        manager = BridgeShimManager.__new__(BridgeShimManager)
        manager.bundle_name = "test.nolexer"
        manager.native_modules = [_Mod("@a/one", source)]
        with patch.object(esm_bridges, "lex_module", return_value=None):
            return manager._discover_bridge_specifiers(set(native), set(ext))

    def test_the_regex_fallback_reads_the_same_kinds(self):
        discovered, _ext = self._discover(
            'import def from "@web/core/a";\n'
            'import * as ns from "@web/core/b";\n'
            'import { named } from "@web/core/c";\n'
            'import "@web/core/d";\n'
        )
        self.assertEqual(discovered["@web/core/a"], {"__default__"})
        self.assertEqual(discovered["@web/core/b"], {"__star__"})
        self.assertEqual(discovered["@web/core/c"], set())
        self.assertEqual(discovered["@web/core/d"], set())

    def test_the_fallback_still_honours_the_ignore_sets(self):
        discovered, ext_seen = self._discover(
            'import { a } from "@web/core/a";\nimport { o } from "@odoo/owl";\n',
            native={"@web/core/a"},
            ext={"@odoo/owl"},
        )
        self.assertEqual(discovered, {})
        self.assertEqual(ext_seen, {"@odoo/owl"})

    def test_the_two_paths_agree_on_the_same_source(self):
        """The fallback is only safe while it says what the lexer says."""
        source = (
            'import def from "@web/core/a";\n'
            'import * as ns from "@web/core/b";\n'
            'import { named } from "@web/core/c";\n'
        )
        manager = BridgeShimManager.__new__(BridgeShimManager)
        manager.bundle_name = "test.agree"
        manager.native_modules = [_Mod("@a/one", source)]

        lexed, _ = manager._discover_bridge_specifiers(set(), set())
        regexed, _ = self._discover(source)
        if not lexed:
            self.skipTest("es-module-lexer worker unavailable")
        self.assertEqual(lexed, regexed)


class TestMinifyJsFailureModes(BaseCase):
    """`minify_js` returns None rather than raising, on every failure.

    Its callers treat None as "ship the source unminified", which keeps a page
    alive when esbuild is missing or unhappy. That makes every failure path a
    silent one, so each needs to be reachable and to say something in the log:
    a bundle that quietly stops being minified is a performance regression
    nobody gets an exception for.
    """

    SOURCE = "const a = `A${`B  ${1}  C`}D`;\n"

    def test_no_binary_returns_none_and_says_so(self):
        from odoo.tools.assets import esbuild

        with (
            patch.object(esbuild, "_find_esbuild", return_value=None),
            self.assertLogs("odoo.assets.esbuild", level="WARNING") as logged,
        ):
            self.assertIsNone(esbuild.minify_js(self.SOURCE, label="probe.js"))
        self.assertIn("minify_no_binary", "\n".join(logged.output))

    def test_a_timeout_returns_none_and_says_so(self):
        import subprocess

        from odoo.tools.assets import esbuild

        with (
            patch.object(esbuild, "_find_esbuild", return_value="/bin/true"),
            patch.object(
                esbuild.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("esbuild", 60),
            ),
            self.assertLogs("odoo.assets.esbuild", level="WARNING") as logged,
        ):
            self.assertIsNone(esbuild.minify_js(self.SOURCE, label="probe.js"))
        self.assertIn("minify_timeout", "\n".join(logged.output))

    def test_a_nonzero_exit_returns_none_and_surfaces_stderr(self):
        from odoo.tools.assets import esbuild

        with (
            patch.object(esbuild, "_find_esbuild", return_value="/bin/false"),
            self.assertLogs("odoo.assets.esbuild", level="WARNING") as logged,
        ):
            self.assertIsNone(esbuild.minify_js("this is not js {", label="bad.js"))
        joined = "\n".join(logged.output)
        self.assertIn("minify_failed", joined)
        self.assertIn("esbuild minify stderr for bad.js", joined)

    @unittest.skipUnless(_find_esbuild(), "esbuild binary not available")
    def test_the_success_path_really_minifies(self):
        from odoo.tools.assets import esbuild

        out = esbuild.minify_js("const a  =  1;\nconst b  =  2;\n", label="ok.js")
        self.assertIsNotNone(out)
        self.assertNotIn("  ", out)
        self.assertIn("const", out)


class TestRunEsbuildFailureReporting(BaseCase):
    """What a failed compile leaves behind for whoever has to diagnose it.

    esbuild reads its entry point from stdin, so when it rejects one there is
    no file to look at -- the input that failed exists only in the process
    that died. `_run_esbuild` therefore dumps the entry text to a temp file
    and names it in the log. That dump is the only artefact of the failure,
    and nothing exercised the code that writes it.
    """

    def _compiler(self, name="test.failrep"):
        return EsbuildCompiler(name, [], [])

    def test_a_nonzero_exit_dumps_the_entry_and_names_the_file(self):
        compiler = self._compiler()
        self.addCleanup(compiler._purge_stale_fail_dumps, compiler.name)

        with self.assertLogs("odoo.assets.esbuild", level="WARNING") as logged:
            with self.assertRaises(RuntimeError) as caught:
                compiler._run_esbuild(
                    ["sh", "-c", "echo 'boom' >&2; exit 3"],
                    30,
                    "// the entry that failed\n",
                    0.0,
                )

        self.assertIn("exit 3", str(caught.exception))
        self.assertIn("boom", str(caught.exception))
        joined = "\n".join(logged.output)
        self.assertIn("event=failed", joined)

        dump = re.search(r"entry=(\S+\.js)", joined)
        self.assertIsNotNone(dump, f"the entry dump was not named: {joined}")
        self.assertEqual(
            Path(dump.group(1)).read_text(encoding="utf-8"),
            "// the entry that failed\n",
        )

    def test_each_failure_purges_the_previous_dump_for_that_bundle(self):
        """Otherwise a bundle failing on every render fills /tmp."""
        compiler = self._compiler("test.purge")
        self.addCleanup(compiler._purge_stale_fail_dumps, compiler.name)

        def fail_once(text):
            with self.assertLogs("odoo.assets.esbuild", level="WARNING") as logged:
                with self.assertRaises(RuntimeError):
                    compiler._run_esbuild(["sh", "-c", "exit 1"], 30, text, 0.0)
            return re.search(r"entry=(\S+\.js)", "\n".join(logged.output)).group(1)

        first = fail_once("// first\n")
        second = fail_once("// second\n")

        self.assertNotEqual(first, second)
        self.assertFalse(Path(first).exists(), "the previous dump must be purged")
        self.assertTrue(Path(second).exists())

    def test_a_timeout_is_reported_as_a_timeout(self):
        compiler = self._compiler()
        with self.assertLogs("odoo.assets.esbuild", level="ERROR") as logged:
            with self.assertRaises(RuntimeError) as caught:
                compiler._run_esbuild(["sleep", "5"], 1, "// slow\n", 0.0)
        self.assertIn("timed out after 1s", str(caught.exception))
        self.assertIn("event=timeout", "\n".join(logged.output))

    def test_a_clean_exit_says_nothing_and_writes_nothing(self):
        compiler = self._compiler("test.quiet")
        compiler._purge_stale_fail_dumps(compiler.name)
        with self.assertNoLogs("odoo.assets.esbuild", level="WARNING"):
            compiler._run_esbuild(["true"], 30, "// fine\n", 0.0)
        self.assertEqual(
            list(Path(tempfile.gettempdir()).glob("esbuild_fail_test.quiet_*.js")), []
        )


class TestExportExtractionWithoutTheLexer(BaseCase):
    """The regex extractor, which decides what a bridge shim re-exports.

    `_extract_esm_exports` prefers es-module-lexer and falls back to a table of
    regexes when `lex_module` returns None -- node missing, or the worker
    having disabled itself. This checkout has node, so the fallback had never
    run, yet it is the thing standing between a module's real export list and
    a shim that binds `undefined` under a name the importer will happily use.

    The parsing that follows each match is where the risk sits: aliases,
    destructuring renames and defaults all have to be reduced to the name the
    module actually publishes.
    """

    @staticmethod
    def _names(src, source_map=None, importer="@w/leaf"):
        from odoo.tools.assets import esm_graph

        with patch.object(esm_graph, "lex_module", return_value=None):
            return esm_graph._extract_esm_exports(
                src, source_map=source_map, importing_specifier=importer
            )

    def test_every_declaration_form_is_found(self):
        names, _ = self._names(
            "export const a = 1;\n"
            "export let b = 2;\n"
            "export var c = 3;\n"
            "export function d() {}\n"
            "export function* e() {}\n"
            "export async function f() {}\n"
            "export class g {}\n"
        )
        self.assertEqual(names, set("abcdefg"))

    def test_an_export_list_publishes_the_alias_not_the_local(self):
        names, _ = self._names("const x = 1;\nexport { x as publicName, y };\n")
        self.assertEqual(names, {"publicName", "y"})

    def test_a_re_export_list_is_read_the_same_way(self):
        names, _ = self._names('export { a, b as c } from "./other";\n')
        self.assertEqual(names, {"a", "c"})

    def test_a_destructured_export_publishes_the_bound_names(self):
        names, _ = self._names("export const { a, b: renamed, c = 3 } = obj;\n")
        self.assertEqual(
            names,
            {"a", "renamed", "c"},
            "a rename publishes the new name and a default publishes the key",
        )

    def test_a_namespace_re_export_publishes_the_namespace(self):
        names, _ = self._names('export * as ns from "./other";\n')
        self.assertIn("ns", names)

    def test_default_is_reported_separately_and_never_as_a_name(self):
        for src in (
            "export default 1;\n",
            "export default function () {}\n",
            "export default function* gen() {}\n",
            "export default async function go() {}\n",
            "export default class Thing {}\n",
        ):
            names, has_default = self._names(src)
            self.assertTrue(has_default, src)
            self.assertNotIn("default", names, src)

    def test_export_star_is_followed_through_the_source_map(self):
        names, _ = self._names(
            'export * from "./base";\nexport const C = 3;\n',
            source_map={"@w/base": "export const A = 1;\nexport const B = 2;\n"},
        )
        self.assertEqual(names, {"A", "B", "C"})

    def test_block_comments_and_template_literals_are_opaque(self):
        names, has_default = self._names(
            "/* export const commented = 1; */\n"
            "const t = `export const templated = 2;`;\n"
            "export const real = 3;\n"
        )
        self.assertEqual(names, {"real"})
        self.assertFalse(has_default)

    def test_a_quoted_string_is_NOT_opaque__documented_divergence(self):
        """A known, bounded gap in the fallback -- not an oversight.

        _JS_OPAQUE_RE blanks block comments and template literals, not quoted
        strings, so an export-shaped string literal publishes a phantom name.
        The lexer does not do this, so the two extractors disagree here.

        It is left alone because the obvious fix is worse. Blanking quoted
        strings too would also blank the module specifier in
        `export * from "./base"`, and star_from needs that specifier to follow
        the re-export -- so the cure turns an over-report into an
        UNDER-report, which is the direction that actually breaks: a name the
        shim fails to publish is a broken import, whereas a name it publishes
        spuriously merely evaluates to undefined for an importer who was
        already asking for something that does not exist.

        Fixing it properly means telling specifier strings from ordinary ones,
        which is the lexer's job. Change this test only alongside that.
        """
        names, _ = self._names(
            'const s = "export const stringy = 2;";\nexport const real = 3;\n'
        )
        self.assertEqual(names, {"real", "stringy"})

    def test_the_divergence_never_costs_a_real_export(self):
        """The property that makes the gap above tolerable, stated directly."""
        src = 'const s = "export const stringy = 2;";\nexport const real = 3;\n'
        from odoo.tools.assets import esm_graph

        lexed, _ = esm_graph._extract_esm_exports(src)
        if not lexed:
            self.skipTest("es-module-lexer worker unavailable")
        fallback, _ = self._names(src)
        self.assertLessEqual(
            lexed, fallback, "the fallback must never publish FEWER names"
        )

    def test_the_two_extractors_agree_on_an_ordinary_module(self):
        """The fallback is only safe while it says what the lexer says."""
        src = (
            "export const a = 1;\n"
            "export function b() {}\n"
            "export class c {}\n"
            "const local = 4;\n"
            "export { local as d };\n"
            "export default 5;\n"
        )
        from odoo.tools.assets import esm_graph

        lexed = esm_graph._extract_esm_exports(src)
        if not lexed[0]:
            self.skipTest("es-module-lexer worker unavailable")
        self.assertEqual(lexed, self._names(src))


class _EntryMod:
    """A native module as `_esbuild_entry_lines` reads one."""

    def __init__(self, module_path, url="", filename=None):
        self.module_path = module_path
        self.url = url
        self._filename = filename


class TestEsbuildEntryLines(BaseCase):
    """The synthetic entry point esbuild is fed on stdin.

    esbuild bundles from an entry, and there is no file for one: the compiler
    writes it. That text is the whole specification of the build -- which
    modules are pulled in, under which specifier each is registered with the
    loader, and which aliases are wired afterwards. A module missing from it
    is simply not in the bundle, with no error anywhere, so the shape is worth
    pinning per bundle kind rather than only through a successful compile.
    """

    ROOT = Path("/odoo")

    def _compiler(self, modules, **kw):
        return EsbuildCompiler("test.entry", modules, [], **kw)

    def test_a_standalone_bundle_imports_for_side_effects_only(self):
        """No loader registration: nothing else shares its module instances."""
        lines = self._compiler(
            [_EntryMod("@a/one", url="/a/static/src/one.js")], standalone=True
        )._esbuild_entry_lines(self.ROOT)

        self.assertEqual(lines, ['import "./addons/a/static/src/one.js";'])
        self.assertFalse(any("registerNativeModules" in ln for ln in lines))

    def test_an_app_bundle_registers_every_member_with_the_loader(self):
        lines = self._compiler(
            [
                _EntryMod("@a/one", url="/a/static/src/one.js"),
                _EntryMod("@a/two", url="/a/static/src/two.js"),
            ]
        )._esbuild_entry_lines(self.ROOT)
        entry = "\n".join(lines)

        self.assertIn('import * as __owl from "@odoo/owl";', entry)
        self.assertIn("odoo.loader.registerNativeModules({", entry)
        self.assertIn('"@a/one": __m0', entry)
        self.assertIn('"@a/two": __m1', entry)
        self.assertIn('"@odoo/owl": __owl', entry)

    def test_a_real_file_is_addressed_by_its_path_on_disk(self):
        """`filename` wins over the url, and is made relative to the root."""
        lines = self._compiler(
            [
                _EntryMod(
                    "@a/one",
                    url="/a/static/src/one.js",
                    filename="/odoo/addons/a/static/src/one.js",
                )
            ]
        )._esbuild_entry_lines(self.ROOT)

        self.assertIn('import * as __m0 from "./addons/a/static/src/one.js";', lines)

    def test_a_test_member_is_skipped_where_the_import_map_supplies_it(self):
        """skip_legacy_test_imports: the parent already registers these, and
        importing them again would inline a second copy."""
        modules = [
            _EntryMod("@a/src", url="/a/static/src/src.js"),
            _EntryMod("@a/../tests/spec", url="/a/static/tests/spec.js"),
        ]
        entry = "\n".join(
            self._compiler(modules, skip_legacy_test_imports=True)._esbuild_entry_lines(
                self.ROOT
            )
        )

        self.assertIn('"@a/src"', entry)
        self.assertNotIn("tests/spec", entry)

    def test_the_same_member_is_kept_when_that_flag_is_off(self):
        modules = [_EntryMod("@a/../tests/spec", url="/a/static/tests/spec.js")]
        entry = "\n".join(self._compiler(modules)._esbuild_entry_lines(self.ROOT))
        self.assertIn("tests/spec", entry)

    def test_hoot_is_aliased_only_when_the_bundle_carries_it(self):
        """`@odoo/hoot` is the public name of a module that lives under
        `@web/../lib`; the alias is wired only if that module is present."""
        without = "\n".join(
            self._compiler(
                [_EntryMod("@a/one", url="/a/static/src/one.js")]
            )._esbuild_entry_lines(self.ROOT)
        )
        self.assertNotIn("@odoo/hoot", without)

        with_hoot = "\n".join(
            self._compiler(
                [_EntryMod("@web/../lib/hoot/hoot", url="/web/static/lib/hoot/hoot.js")]
            )._esbuild_entry_lines(self.ROOT)
        )
        self.assertIn(
            'odoo.loader.modules.set("@odoo/hoot",'
            'odoo.loader.modules.get("@web/../lib/hoot/hoot"));',
            with_hoot,
        )

    def test_an_empty_bundle_still_registers_owl(self):
        entry = "\n".join(self._compiler([])._esbuild_entry_lines(self.ROOT))
        self.assertIn('"@odoo/owl": __owl', entry)
