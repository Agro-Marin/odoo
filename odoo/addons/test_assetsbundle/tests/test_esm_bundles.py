from types import SimpleNamespace

from odoo.tests.common import BaseCase, TransactionCase
from odoo.tools.assets.esm_registry import esm_registry
from odoo.tools.json import scriptsafe as json
from odoo.tools.misc import file_path

from .common import _Mod
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


class TestHootOwnership(TransactionCase):
    TOUR_BUNDLE = "web.assets_tests"
    RUNNER_BUNDLE = "web.assets_unit_tests_setup"

    def test_the_tour_bundle_owns_none_of_its_specifiers(self):
        IrQweb = self.env["ir.qweb"]
        specs = set(
            IrQweb._get_asset_bundle(
                self.TOUR_BUNDLE, js=True, css=False, assets_params={}
            ).get_native_module_data(with_bridges=False)["import_map"]
        )
        self.assertTrue(specs, "the tour bundle must resolve to something")

        owned = IrQweb._get_hoot_specifiers(self.TOUR_BUNDLE, specs)

        self.assertFalse(owned, f"Hoot does not own tour-bundle specifiers: {owned}")

    def test_a_suite_is_recognised_by_name_in_any_bundle(self):
        suite = "@im_livechat/../tests/embed/thread.test"

        self.assertEqual(
            self.env["ir.qweb"]._get_hoot_specifiers("some.standalone_bundle", [suite]),
            [suite],
        )

    def test_an_import_map_parent_owns_none_of_its_helpers(self):
        """`RUNNER_BUNDLE` is a parent of an import-map pair, and a parent owns
        no tests: its job is to PROVIDE, the child's is to run.  Hoot
        specifiers are withheld from `registerNativeModules` and handed to
        `loadAndStart` instead, so classifying a parent's helpers as hoot does
        two wrong things at once -- it starts a runner from the setup bundle,
        and it withholds exactly the modules the child has to bridge onto,
        leaving the child with `loadAndStart is not a function`.

        This asserted the opposite until the guard that fixed that hang landed
        in `_get_hoot_specifiers`, and then kept asserting it.
        """
        helper = "@web/../tests/_framework/mock_server/mock_server"
        self.assertIn(self.RUNNER_BUNDLE, esm_registry().import_map_includes)
        self.assertEqual(
            self.env["ir.qweb"]._get_hoot_specifiers(self.RUNNER_BUNDLE, [helper]),
            [],
        )

    def test_the_child_of_that_pair_owns_its_unnamed_helpers(self):
        """The other half of the same rule: the bundle that runs the tests
        classifies everything under a `tests/` tree, helpers included, because
        that is what it hands to `loadAndStart`."""
        helper = "@web/../tests/_framework/mock_server/mock_server"
        child = esm_registry().import_map_includes[self.RUNNER_BUNDLE][0]
        self.assertIn(child, esm_registry().import_map_included_bundles)
        self.assertEqual(
            self.env["ir.qweb"]._get_hoot_specifiers(child, [helper]),
            [helper],
        )

    def test_a_tour_is_never_owned_wherever_it_lives(self):
        tour = "@web/../tests/tours/some_tour"

        self.assertFalse(
            self.env["ir.qweb"]._get_hoot_specifiers(self.RUNNER_BUNDLE, [tour])
        )


class TestEsmSpecifierResolution(BaseCase):
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
    def _resolver(self):
        from odoo.tools.assets.esm_graph import _BridgeExportResolver

        return _BridgeExportResolver({}, {}, "test")

    def test_a_real_module_yields_its_real_exports(self):
        names, _has_default = self._resolver().source_exports(
            "@test_assetsbundle/../tests/native_esm/registry"
        )
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


class TestEscapingRelativeImports(BaseCase):
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
