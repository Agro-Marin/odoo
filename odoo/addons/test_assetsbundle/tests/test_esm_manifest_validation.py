from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import BaseCase, TransactionCase
from odoo.tools.assets.esm_registry import (
    esm_registry,
    external_libs,
    validate_esm_config,
)

from odoo.addons.base.models.assetsbundle import AssetsBundle


class TestEsmConfigValidation(TransactionCase):
    def test_live_registry_builds_and_validates(self):
        # Smoke-tests validate_esm_config() against the whole live
        # registry. See TestExternalLibsValidator.test_the_live_tables_
        # satisfy_all_four below for the equivalent live-table smoke test
        # of _check_external_libs() -- the two together are "is the real
        # config internally consistent", kept adjacent on purpose.
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
        assets_params = self.env["ir.asset"]._prepare_assets_params()

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
        assets_params = self.env["ir.asset"]._prepare_assets_params()
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

    def test_check_external_libs_follows_esbuild_pattern(self):
        AssetsBundle._check_external_libs(
            {
                "@odoo/owl": "/web/static/lib/owl/owl.es.js",
                "@odoo/not-listed": "/web/static/lib/owl/owl.es.js",
            },
        )
        with self.assertRaises(ValueError):
            AssetsBundle._check_external_libs(
                {"left-pad": "/web/static/lib/owl/owl.es.js"},
            )


class TestExternalLibsValidator(BaseCase):
    REAL_URL = "/web/static/lib/owl/owl.es.js"

    def test_a_specifier_esbuild_cannot_resolve_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no resolution for them"):
            AssetsBundle._check_external_libs(
                {"left-pad": self.REAL_URL}, lib_candidates={}
            )

    def test_bare_externals_are_a_subset_of_the_declared_libs(self):
        from odoo.tools.assets.esm_registry import external_bare_specifiers

        registered = external_libs()
        # The subset assertion below is satisfied by two empty sets, so it
        # cannot tell "every bare specifier is declared" from "the registry
        # read nothing" -- ADR-0044's shape exactly. This guard is what makes
        # the next line mean something. It arrived here from a duplicate of
        # this class that `web` used to carry: the duplicate drifted (its
        # absent-addon test still asserted the behaviour d025c1bb062 inverted)
        # and was removed in favour of this one, which was a superset in every
        # assertion but this.
        self.assertTrue(registered, "no module declares an external lib")
        self.assertLessEqual(set(external_bare_specifiers()), set(registered))

    def test_an_import_map_url_pointing_nowhere_is_refused(self):
        with self.assertRaisesRegex(ValueError, "do not exist"):
            AssetsBundle._check_external_libs(
                {"@odoo/owl": "/web/static/lib/owl/does_not_exist.js"},
                lib_candidates={},
            )

    def test_a_lib_alias_pointing_nowhere_is_refused(self):
        with self.assertRaisesRegex(ValueError, "_LIB_CANDIDATES aliases"):
            AssetsBundle._check_external_libs(
                {},
                lib_candidates={"@odoo/nope": ("web", "static", "lib", "nope.js")},
            )

    def test_an_unknown_addon_in_the_url_is_refused_like_any_other_missing_file(self):
        with self.assertRaisesRegex(ValueError, "do not exist"):
            AssetsBundle._check_external_libs(
                {"@odoo/owl": "/no_such_addon_here/static/lib/x.js"},
                lib_candidates={},
            )

    def test_a_lib_candidate_in_an_absent_addon_is_skipped(self):
        """The asymmetry with the import map above, pinned.

        _LIB_CANDIDATES is a static table naming addons a given deployment may
        not carry, and _get_esbuild_addon_flags already skips a candidate whose
        file is absent, so nothing imports the alias. Dropping the
        _addon_is_present guard from that loop -- to match the import map, which
        deliberately has none -- would make every deployment without the addon
        raise on a lib it never uses.
        """
        AssetsBundle._check_external_libs(
            {},
            lib_candidates={"@odoo/nope": ("no_such_addon_here", "static", "x.js")},
        )

    def test_every_declared_lib_is_served_by_its_own_addon(self):
        from odoo.modules import Manifest
        from odoo.tools.assets.esbuild import EsbuildCompiler

        cross_addon = []
        for manifest in Manifest.all_addon_manifests():
            declared = (manifest.get("esm") or {}).get("external_libs") or {}
            for spec, url in declared.items():
                if url.lstrip("/").split("/")[0] != manifest.name:
                    cross_addon.append(f"{spec}: {manifest.name} declares {url}")
        self.assertFalse(
            cross_addon,
            "a lib is declared by one addon and served by another; the strict "
            "addon check in `_addon_relative_path_exists` assumes this does not "
            "happen, so decide which of the two changes:\n  "
            + "\n  ".join(cross_addon),
        )
        for alias, parts in EsbuildCompiler._LIB_CANDIDATES.items():
            self.assertTrue(
                AssetsBundle._addon_relative_path_exists("/".join(parts)),
                f"{alias} points at {'/'.join(parts)}, which this checkout cannot "
                f"serve; a lib alias must live in a bundled addon",
            )

    def test_the_live_tables_satisfy_all_four(self):
        # Companion to TestEsmConfigValidation.test_live_registry_builds_
        # and_validates above: that one smoke-tests validate_esm_config()
        # against the live registry, this one smoke-tests
        # _check_external_libs() against the live external-libs table.
        AssetsBundle._check_external_libs(external_libs())


class TestSpecifierResolutionHasOneOwner(BaseCase):
    def _tables(self):
        from odoo.tools.assets.esbuild import EsbuildCompiler
        from odoo.tools.assets.esm_registry import external_libs

        return external_libs(), EsbuildCompiler._LIB_CANDIDATES

    def test_every_lib_candidate_resolves(self):
        from odoo.tools.assets.esm_graph import resolve_specifier_url

        ext, libs = self._tables()
        for spec in libs:
            self.assertIsNotNone(
                resolve_specifier_url(spec, ext, libs),
                f"{spec} is aliased for esbuild but the page could not resolve it",
            )

    def test_the_resolver_and_the_qweb_call_site_agree(self):
        from odoo.tools.assets.esm_graph import (
            _BridgeExportResolver,
            resolve_specifier_url,
        )

        ext, libs = self._tables()
        resolver = _BridgeExportResolver(ext, libs, "test")
        for spec in [*ext, *libs, "@web/core/registry", "@web/../lib/luxon/luxon"]:
            self.assertEqual(
                resolver.resolve_url(spec),
                resolve_specifier_url(spec, ext, libs),
                f"{spec} resolves differently through the two entry points",
            )

    def test_declared_tables_beat_the_naming_convention(self):
        from odoo.tools.assets.esm_graph import (
            addon_specifier_to_url,
            resolve_specifier_url,
        )

        self.assertEqual(
            resolve_specifier_url("@odoo/x", {}, {"@odoo/x": ("a", "b", "c.js")}),
            "/a/b/c.js",
        )
        self.assertIsNone(resolve_specifier_url("@odoo/x", {}, {}))
        self.assertIsNone(addon_specifier_to_url("@odoo/x"))


class TestBrokenManifestDoesNotTakeThePageDown(BaseCase):
    def _check_with(self, bad_table, fails_closed):
        from odoo.addons.base.models.assetsbundle import bundle as bundle_mod

        bundle_mod._check_external_libs_once.cache_clear()
        self.addCleanup(bundle_mod._check_external_libs_once.cache_clear)
        with (
            patch.object(bundle_mod, "external_libs", lambda: bad_table),
            patch.object(
                bundle_mod.JsPipeline,
                "_fails_closed",
                staticmethod(lambda: fails_closed),
            ),
        ):
            bundle_mod._check_external_libs_once()

    def test_production_logs_instead_of_raising(self):
        with self.assertLogs("odoo.assets.bundle", level="ERROR") as logs:
            self._check_with({"@odoo/owl": "/web/static/lib/owl/NOPE.js"}, False)
        self.assertTrue(
            any("external_libs_invalid" in line for line in logs.output), logs.output
        )

    def test_a_session_with_a_reader_still_raises(self):
        with self.assertRaises(ValueError):
            self._check_with({"@odoo/owl": "/web/static/lib/owl/NOPE.js"}, True)

    def test_the_validator_itself_still_raises_when_called_directly(self):
        with self.assertRaisesRegex(ValueError, "do not exist"):
            AssetsBundle._check_external_libs(
                {"@odoo/owl": "/web/static/lib/owl/NOPE.js"}, lib_candidates={}
            )


class TestEsmManifestShapeGuards(BaseCase):
    def _build_with(self, esm):
        from odoo.modules import Manifest
        from odoo.tools.assets import esm_registry as reg

        fake = SimpleNamespace(name="probe_addon", get=lambda key: esm)
        with patch.object(
            Manifest, "all_addon_manifests", staticmethod(lambda: [fake])
        ):
            return reg._build()

    def test_a_non_mapping_esm_key_is_refused(self):
        with self.assertRaisesRegex(TypeError, "manifest 'esm' must be a dict"):
            self._build_with(["web.assets_web"])

    def test_an_unknown_esm_key_is_refused(self):
        with self.assertRaisesRegex(ValueError, "unknown 'esm' manifest keys"):
            self._build_with({"bundels": ["a.b"]})

    def test_bundles_as_a_bare_string_is_refused(self):
        with self.assertRaisesRegex(TypeError, "'esm.bundles' must be a list"):
            self._build_with({"bundles": "web.assets_web"})

    def test_standalone_bundles_as_a_bare_string_is_refused(self):
        with self.assertRaisesRegex(TypeError, "must be\\s+a list"):
            self._build_with({"bundles": ["a.b"], "standalone_bundles": "a.b"})

    def test_a_relationship_mapping_must_be_a_mapping(self):
        with self.assertRaisesRegex(TypeError, "must be a dict"):
            self._build_with({"bundles": ["a.b"], "dynamic_children": ["a.b"]})

    def test_relationship_children_must_be_a_list(self):
        with self.assertRaisesRegex(TypeError, "must be a\\s+list of bundle names"):
            self._build_with({"bundles": ["a.b"], "dynamic_children": {"a.b": "a.c"}})

    def test_a_well_formed_declaration_builds(self):
        registry = self._build_with({"bundles": ["a.b"], "standalone_bundles": ["a.b"]})
        self.assertIn("a.b", registry.bundles)
        self.assertIn("a.b", registry.standalone_bundles)

    def test_runtime_bundles_as_a_bare_string_is_refused(self):
        with self.assertRaisesRegex(TypeError, "must be\\s+a list"):
            self._build_with({"bundles": ["a.b"], "runtime_bundles": "a.b"})

    def test_a_runtime_bundle_must_be_a_registered_bundle(self):
        with self.assertRaisesRegex(ValueError, "runtime_bundles entry 'a.c'"):
            self._build_with({"bundles": ["a.b"], "runtime_bundles": ["a.c"]})

    def test_runtime_bundles_needs_no_parent(self):
        registry = self._build_with({"bundles": ["a.b"], "runtime_bundles": ["a.b"]})
        self.assertIn("a.b", registry.runtime_bundle_names)
        self.assertEqual(registry.dynamic_children, {})
        self.assertEqual(registry.dynamic_bundle_names, frozenset())

    def test_a_dynamic_child_is_a_runtime_bundle_without_saying_so(self):
        registry = self._build_with(
            {"bundles": ["a.b", "a.c"], "dynamic_children": {"a.b": ["a.c"]}}
        )
        self.assertIn("a.c", registry.runtime_bundle_names)
        self.assertNotIn("a.b", registry.runtime_bundle_names)

    def test_a_standalone_bundle_may_not_be_in_a_relationship(self):
        with self.assertRaisesRegex(ValueError, "cannot participate"):
            self._build_with(
                {
                    "bundles": ["a.b", "a.c"],
                    "standalone_bundles": ["a.c"],
                    "dynamic_children": {"a.b": ["a.c"]},
                }
            )
