"""Tests for the 2026-06 assetsbundle hardening batch.

Covers the module-syntax guard for non-ESM bundles, the process-level
classification cache, preprocessor subprocess timeouts, the external-asset
extension probe, bridge-shim string literals, and the ``RETURNING``-based
filestore bookkeeping of ``_unlink_attachments``.

Second batch (2026-06-10 audit follow-up): esbuild minification of
backtick files, ``SECONDARY_IMPORT_MAP_INCLUDES`` validation, the
``last_modified`` stat fallback, inline-XML error paths, css version
stability across ``preprocess_css``, bridge hash width, the
``save_attachment`` extension guard, and the readonly→read-write
bridge-persistence escalation.
"""

import unittest
from unittest.mock import patch

from odoo.libs.esbuild import _find_esbuild
from odoo.libs.esm_bridges import BridgeShimManager
from odoo.libs.esm_graph import _MODULE_SYNTAX_RE
from odoo.libs.esm_registry import esm_registry, validate_esm_config
from odoo.tests.common import BaseCase, TransactionCase
from odoo.tools.json import scriptsafe as json
from odoo.tools.misc import file_path

from odoo.addons.base.models.assetsbundle import (
    ANY_UNIQUE,
    AssetAttachmentStore,
    AssetNotFoundError,
    AssetsBundle,
    CompileError,
    JavascriptAsset,
    PreprocessedCSS,
    ScssStylesheetAsset,
    StylesheetAsset,
    WebAsset,
    XMLAsset,
    XMLAssetError,
    _cached_module_classification,
    is_odoo_module,
)
from odoo.addons.base.models.ir_attachment import IrAttachment

MODULE_JS = 'import { x } from "@web/core/registry";\nexport const y = x;\n'
PLAIN_JS = "(function () {\n    var x = 1;\n    window.testX = x;\n})();\n"


def _file(url, content, last_modified=1.0):
    """Build the files-dict entry shape produced by ir_qweb._get_asset_content."""
    return {
        "url": url,
        "filename": None,
        "content": content,
        "last_modified": last_modified,
    }


class _FakeIrAsset:
    """Stand-in for the ``ir.asset`` model; records URL-build calls."""

    def __init__(self, calls):
        self.calls = calls

    def _get_asset_bundle_url(self, bundle_name, unique, assets_params, ignore_params):
        self.calls.append((bundle_name, unique, assets_params, ignore_params))
        return f"/web/assets/{unique}/{bundle_name}"


class _FakeEnv:
    """Minimal env exposing only ``env['ir.asset']`` — no registry, no cursor."""

    def __init__(self, calls):
        self._asset = _FakeIrAsset(calls)

    def __getitem__(self, model):
        assert model == "ir.asset", model
        return self._asset


class TestAssetAttachmentStoreUnit(BaseCase):
    """Unit-test the extracted attachment store in isolation — no DB, no bundle.

    The 2026-06 extraction split persistence out of ``AssetsBundle`` precisely so
    this URL/identity logic could be exercised without a live bundle and cursor.
    The store takes its env and version source as constructor args, so a fake env
    and a stub ``version_provider`` suffice. (The DB-backed methods —
    get/save/clean/unlink_attachments — stay covered by the integration suite;
    this guards the seam that the extraction was for.)
    """

    def _store(self, calls, *, rtl=False, autoprefix=False, params=None):
        return AssetAttachmentStore(
            _FakeEnv(calls),
            "web.assets_web",
            assets_params=params or {},
            rtl=rtl,
            autoprefix=autoprefix,
            version_provider=lambda asset_type: "abc1234",
        )

    def test_pure_helpers_need_no_env(self):
        """``is_css`` / ``_like_escape`` are pure; the store holds no bundle ref."""
        store = self._store([])
        self.assertTrue(store.is_css("min.css"))
        self.assertTrue(store.is_css("css.map"))
        self.assertFalse(store.is_css("min.js"))
        self.assertEqual(store._like_escape("web.assets_web"), r"web.assets\_web")
        # Decoupled by design: the store never back-references its bundle.
        self.assertFalse(hasattr(store, "bundle"))

    def test_get_asset_url_uses_plain_name(self):
        """The served URL is built from the unescaped bundle name."""
        calls = []
        url = self._store(calls).get_asset_url("abc1234", "min.js")
        bundle_name, unique, _params, ignore_params = calls[-1]
        self.assertEqual(bundle_name, "web.assets_web.min.js")
        self.assertEqual(unique, "abc1234")
        self.assertFalse(ignore_params)
        self.assertEqual(url, "/web/assets/abc1234/web.assets_web.min.js")

    def test_pattern_like_escapes_bundle_name(self):
        """The SQL ``=like`` pattern escapes ``_`` so siblings can't match."""
        calls = []
        self._store(calls).get_asset_url_pattern(extension="min.js")
        bundle_name, unique, _params, _ignore = calls[-1]
        self.assertEqual(bundle_name, r"web.assets\_web.min.js")
        self.assertEqual(unique, ANY_UNIQUE)

    def test_url_encodes_rtl_and_autoprefix_for_css_only(self):
        """``.rtl`` / ``.autoprefixed`` segments apply to CSS artifacts, not JS."""
        calls = []
        store = self._store(calls, rtl=True, autoprefix=True)
        store.get_asset_url("v", "min.css")
        self.assertEqual(calls[-1][0], "web.assets_web.rtl.autoprefixed.min.css")
        store.get_asset_url("v", "min.js")
        self.assertEqual(calls[-1][0], "web.assets_web.min.js")


class TestModuleSyntaxGuard(TransactionCase):
    """Module-syntax JS in a non-ESM bundle is stubbed out, loudly."""

    BUNDLE = "test_assetsbundle.legacy_guard"

    def test_module_file_is_stubbed_and_excluded(self):
        """The offending file becomes a console.error; the rest survives."""
        bundle = AssetsBundle(
            self.BUNDLE,
            [
                _file("/test_assetsbundle/static/src/mod.js", MODULE_JS),
                _file("/test_assetsbundle/static/src/plain.js", PLAIN_JS),
            ],
            env=self.env,
        )
        self.assertNotIn(self.BUNDLE, esm_registry().bundles)
        self.assertEqual(len(bundle.javascripts), 2)
        with self.assertLogs("odoo.assets.bundle", level="ERROR") as cm:
            attachment = bundle.js()
        self.assertIn("module_syntax_in_legacy_bundle", "\n".join(cm.output))
        content = attachment.raw.decode()
        self.assertIn("console.error(", content)
        self.assertNotIn("import { x }", content)
        self.assertIn("window.testX", content)

    def test_plain_src_file_is_not_stubbed(self):
        """Plain JS under /static/src must NOT trip the syntax-based guard."""
        bundle = AssetsBundle(
            f"{self.BUNDLE}_plain",
            [_file("/test_assetsbundle/static/src/plain.js", PLAIN_JS)],
            env=self.env,
        )
        content = bundle.js().raw.decode()
        self.assertIn("window.testX", content)
        self.assertNotIn("console.error(", content)

    def test_ignore_header_opts_out(self):
        """``@odoo-module ignore`` asserts classic-safety; no stub."""
        ignored = "// @odoo-module ignore\n" + PLAIN_JS
        bundle = AssetsBundle(
            f"{self.BUNDLE}_ignore",
            [_file("/test_assetsbundle/static/src/ignored.js", ignored)],
            env=self.env,
        )
        content = bundle.js().raw.decode()
        self.assertIn("window.testX", content)
        self.assertNotIn("console.error(", content)

    def test_esm_bundle_routes_module_to_native(self):
        """In an ESM bundle the same file lands in native_modules, untouched."""
        bundle = AssetsBundle(
            "web.assets_web",
            [_file("/web/static/src/fake_mod.js", MODULE_JS)],
            env=self.env,
        )
        self.assertEqual(len(bundle.native_modules), 1)
        self.assertEqual(len(bundle.javascripts), 0)

    def test_syntax_regex_ignores_dynamic_import(self):
        """``import(...)`` is legal in classic scripts and must not match."""
        self.assertFalse(_MODULE_SYNTAX_RE.search('import("/web/x.js").then();'))
        self.assertTrue(_MODULE_SYNTAX_RE.search('import { a } from "@web/x";'))
        self.assertTrue(_MODULE_SYNTAX_RE.search('import "side-effect";'))
        self.assertTrue(_MODULE_SYNTAX_RE.search("export default class {}"))

    def test_is_odoo_module_empty_url(self):
        """Inline assets (no url) must not crash the routing heuristic."""
        self.assertFalse(is_odoo_module("", PLAIN_JS))
        self.assertTrue(is_odoo_module("", "// @odoo-module\n" + MODULE_JS))

    def test_block_comment_export_is_not_stubbed(self):
        """Line-anchored ``export`` inside a block comment is not module syntax."""
        commented = "/*\nexport const x = 1;\nimport { a } from 'b';\n*/\n" + PLAIN_JS
        bundle = AssetsBundle(
            f"{self.BUNDLE}_blockcomment",
            [_file("/test_assetsbundle/static/src/commented.js", commented)],
            env=self.env,
        )
        content = bundle.js().raw.decode()
        self.assertIn("window.testX", content)
        self.assertNotIn("console.error(", content)

    def test_template_literal_export_is_not_stubbed(self):
        """Line-anchored ``export`` inside a template literal is data, not syntax."""
        templated = "var s = `\nexport default thing\n`;\n" + PLAIN_JS
        bundle = AssetsBundle(
            f"{self.BUNDLE}_template",
            [_file("/test_assetsbundle/static/src/templated.js", templated)],
            env=self.env,
        )
        content = bundle.js().raw.decode()
        self.assertIn("window.testX", content)
        self.assertNotIn("console.error(", content)

    def test_module_syntax_outside_comment_still_stubbed(self):
        """Real module syntax next to an innocent comment still trips the guard."""
        mixed = "/*\nexport const decoy = 1;\n*/\n" + MODULE_JS
        bundle = AssetsBundle(
            f"{self.BUNDLE}_mixed",
            [_file("/test_assetsbundle/static/src/mixed.js", mixed)],
            env=self.env,
        )
        with self.assertLogs("odoo.assets.bundle", level="ERROR"):
            content = bundle.js().raw.decode()
        self.assertIn("console.error(", content)


class TestClassificationCache(TransactionCase):
    """File-backed ESM classification is memoized per (url, filename, mtime)."""

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


class _SleepyCSS(PreprocessedCSS):
    """Compiler stand-in that hangs longer than its timeout budget."""

    _COMPILE_TIMEOUT_S = 1

    def get_command(self):
        return ["sleep", "30"]


class TestPreprocessorTimeout(TransactionCase):
    """A hung stylesheet compiler raises CompileError instead of pinning the worker."""

    def test_compile_times_out(self):
        bundle = AssetsBundle("test_assetsbundle.timeout", [], env=self.env)
        asset = _SleepyCSS(bundle, url="/test_assetsbundle/static/src/x.scss")
        with self.assertRaises(CompileError) as cm:
            asset.compile("a { color: red; }")
        self.assertIn("timed out", str(cm.exception))


class TestExternalAssetFilter(TransactionCase):
    """External URLs keep their query string; unknown extensions warn."""

    def test_query_string_and_fragment_survive(self):
        bundle = AssetsBundle(
            "test_assetsbundle.ext",
            [],
            external_assets=[
                "https://cdn.example.com/lib.css?v=2",
                "https://cdn.example.com/lib.js#frag",
            ],
            env=self.env,
        )
        self.assertEqual(len(bundle.external_assets), 2)

    def test_unknown_extension_warns(self):
        with self.assertLogs("odoo.assets.bundle", level="WARNING") as cm:
            bundle = AssetsBundle(
                "test_assetsbundle.ext_bad",
                [],
                external_assets=["https://cdn.example.com/font.woff2"],
                env=self.env,
            )
        self.assertEqual(bundle.external_assets, [])
        self.assertIn("external_asset_skipped", "\n".join(cm.output))


class TestBridgeShimLiterals(TransactionCase):
    """Shim codegen uses script-safe JSON strings, not Python repr."""

    def test_shim_specifier_is_json_quoted(self):
        shim, is_fallback = AssetsBundle._bridge_shim_source(
            "@web/core/x", set(), {"alpha"}, True
        )
        self.assertIn('odoo.loader.modules.get("@web/core/x");', shim)
        self.assertNotIn("get('@web/core/x')", shim)
        self.assertIn("export const alpha = _m?.alpha;", shim)
        self.assertFalse(is_fallback)


class TestUnlinkAttachmentsReturning(TransactionCase):
    """Filestore marks follow the rows actually deleted by SKIP LOCKED."""

    def test_deleted_rows_drive_file_marks(self):
        attachments = self.env["ir.attachment"].create(
            [
                {
                    "name": f"hardening_{i}.js",
                    "type": "binary",
                    "raw": f"// hardening test {i}".encode(),
                    "res_model": "ir.ui.view",
                    "res_id": 0,
                    "public": True,
                    "url": f"/web/assets/hardeningtest/{i}.js",
                }
                for i in range(2)
            ]
        )
        expected_fnames = set(attachments.mapped("store_fname")) - {False}
        bundle = AssetsBundle("test_assetsbundle.unlink", [], env=self.env)
        with patch.object(IrAttachment, "_file_delete") as file_delete:
            bundle._unlink_attachments(attachments)
        marked = {call.args[-1] for call in file_delete.call_args_list}
        self.assertEqual(marked, expected_fnames)
        self.assertFalse(
            self.env["ir.attachment"].search(
                [("url", "like", "/web/assets/hardeningtest/%")]
            )
        )


@unittest.skipUnless(_find_esbuild(), "esbuild binary not available")
class TestBacktickMinification(TransactionCase):
    """Backtick files are minified through esbuild; templates survive intact."""

    BUNDLE = "test_assetsbundle.backtick"

    def test_backtick_file_is_minified(self):
        """Code shrinks, but template-literal interiors are byte-identical."""
        src = (
            "(function () {\n"
            "    var name = 'x';\n"
            "    window.testTpl = `hello   ${name}`;\n"
            "})();\n"
        )
        bundle = AssetsBundle(
            self.BUNDLE,
            [_file("/test_assetsbundle/static/src/tpl.js", src)],
            env=self.env,
        )
        content = bundle.js().raw.decode()
        # esbuild may keep the template or constant-fold it; either way the
        # whitespace-significant interior must be byte-identical.
        self.assertIn("hello   ", content)
        self.assertIn("window.testTpl", content)
        self.assertNotIn("\n    var name", content)

    def test_nested_template_survives(self):
        """The rjsmin hazard case: nested templates keep inner whitespace."""
        src = "window.testNested = `outer ${`in  ner`} end`;\n"
        bundle = AssetsBundle(
            f"{self.BUNDLE}_nested",
            [_file("/test_assetsbundle/static/src/nested.js", src)],
            env=self.env,
        )
        content = bundle.js().raw.decode()
        self.assertIn("in  ner", content)

    def test_esbuild_failure_ships_unminified(self):
        """minify_js returning None degrades to the raw source, never an error."""
        src = "window.testRaw = `keep   me`;\nvar    spaced = 1;\n"
        with patch("odoo.addons.base.models.assetsbundle.minify_js", return_value=None):
            bundle = AssetsBundle(
                f"{self.BUNDLE}_fallback",
                [_file("/test_assetsbundle/static/src/fallback.js", src)],
                env=self.env,
            )
            content = bundle.js().raw.decode()
        self.assertIn("var    spaced = 1;", content)


class TestEsmConfigValidation(TransactionCase):
    """Manifest-aggregated ESM taxonomy is validated at registry build."""

    def test_live_registry_builds_and_validates(self):
        """The real manifests aggregate into a valid, populated registry."""
        reg = esm_registry()
        self.assertIn("web.assets_web", reg.bundles)
        self.assertIn("point_of_sale._assets_pos", reg.bundles)
        self.assertIn("web_tour.automatic", reg.dynamic_children["web.assets_web"])
        self.assertIn("web.assets_unit_tests", reg.import_map_included_bundles)
        # Re-running the validator on the live aggregate must not raise.
        validate_esm_config(
            reg.bundles,
            reg.dynamic_children,
            reg.import_map_includes,
            reg.secondary_import_map_includes,
        )

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
        """Two modules declaring the same child is a config error."""
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_esm_config({"p", "c"}, {"p": ["c", "c"]}, {}, {})

    def test_dynamic_and_include_overlap_rejected(self):
        with self.assertRaisesRegex(ValueError, "both"):
            validate_esm_config({"p", "c"}, {"p": ["c"]}, {"p": ["c"]}, {})


class TestLastModifiedFallback(TransactionCase):
    """File-backed assets without a supplied mtime stat the file, not -1."""

    def test_missing_mtime_stats_file(self):
        bundle = AssetsBundle("test_assetsbundle.mtime", [], env=self.env)
        asset = JavascriptAsset(
            bundle,
            url="/web/static/src/module_loader.js",
            filename=file_path("web/static/src/module_loader.js"),
        )
        self.assertGreater(asset.last_modified, 0)

    def test_missing_file_keeps_sentinel(self):
        bundle = AssetsBundle("test_assetsbundle.mtime2", [], env=self.env)
        asset = JavascriptAsset(
            bundle,
            url="/web/static/src/gone.js",
            filename="/nonexistent/definitely_gone.js",
        )
        self.assertEqual(asset.last_modified, -1)


class TestXmlInlineErrorPath(TransactionCase):
    """Inline XML assets raise XMLAssetError, not AttributeError, on bad input."""

    def test_invalid_inherit_mode_inline(self):
        bundle = AssetsBundle("test_assetsbundle.xmlerr", [], env=self.env)
        bundle.templates.append(
            XMLAsset(
                bundle,
                inline='<templates><t t-name="x" t-inherit="p" t-inherit-mode="bogus"/></templates>',
            )
        )
        with (
            self.assertLogs("odoo.addons.base.models.assetsbundle", level="ERROR"),
            self.assertRaisesRegex(XMLAssetError, "Invalid inherit mode"),
        ):
            bundle.xml()


class TestCssVersionStability(TransactionCase):
    """The advertised css version survives preprocess_css's at-rules mutation."""

    def test_version_pinned_before_preprocess(self):
        files = [_file("/test_assetsbundle/static/src/x.scss", "h1 { color: red; }")]
        with patch.object(
            ScssStylesheetAsset,
            "compile",
            lambda self, source: '@charset "UTF-8";\n' + source,
        ):
            bundle = AssetsBundle(
                "test_assetsbundle.cssver", files, env=self.env, js=False
            )
            version_before = bundle.get_version("css")
            bundle.preprocess_css()
            # The at-rules fragment was inserted (the mutation is real)...
            self.assertEqual(len(bundle.stylesheets), 2)
            # ...but the cached checksum keeps the advertised URL stable.
            self.assertEqual(bundle.get_version("css"), version_before)

    def test_version_independent_of_call_order(self):
        """The version no longer depends on whether get_version runs before
        or after preprocess_css — it reads the __init__ snapshot, not the
        live list the at-rules fragment is inserted into.
        """
        files = [_file("/test_assetsbundle/static/src/x.scss", "h1 { color: red; }")]
        with patch.object(
            ScssStylesheetAsset,
            "compile",
            lambda self, source: '@charset "UTF-8";\n' + source,
        ):
            # Bundle A: version computed FIRST (the historically-required order).
            bundle_a = AssetsBundle(
                "test_assetsbundle.cssorder", files, env=self.env, js=False
            )
            version_first = bundle_a.get_version("css")

            # Bundle B (identical): preprocess FIRST, mutating the live list,
            # THEN read the version. Pre-fix this returned a different hash.
            bundle_b = AssetsBundle(
                "test_assetsbundle.cssorder", files, env=self.env, js=False
            )
            bundle_b.preprocess_css()
            self.assertEqual(len(bundle_b.stylesheets), 2, "at-rules fragment inserted")
            self.assertEqual(
                bundle_b.get_version("css"),
                version_first,
                "preprocess_css must not change the advertised version",
            )


class TestBridgeHashWidth(TransactionCase):
    """Bridge attachment URLs use a 128-bit content hash."""

    def test_bridge_url_hash_is_32_hex(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        # Mock the persistence seam: this test only checks URL shape, and an
        # unmocked persist now commits a real (content-addressed) row through
        # the independent rw cursor — which would pollute sibling tests that
        # share content. See TestBridgePersistenceDecoupled.
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=True
        ):
            urls = bundle._persist_bridge_shims({"@web/test_hash": "export default 1;"})
        basename = urls["@web/test_hash"].rsplit("/", 1)[-1]
        self.assertRegex(basename, r"^[0-9a-f]{32}\.js$")


class TestBridgeReadonlyEscalation(TransactionCase):
    """On a read-only cursor, bridge persistence escalates to a rw cursor."""

    def _make_cursor_readonly(self):
        """Flip the request-cursor flag the production branch keys on."""
        cr = self.env.cr
        original = cr._readonly
        cr._readonly = True
        self.addCleanup(setattr, cr, "_readonly", original)

    def test_escalation_success_returns_canonical_urls(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        self._make_cursor_readonly()
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=True
        ) as escalate:
            urls = bundle._persist_bridge_shims({"@web/ro_test": "export default 1;"})
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
            urls = bundle._persist_bridge_shims({"@web/ro_test2": "export default 2;"})
        escalate.assert_called_once()
        self.assertTrue(urls["@web/ro_test2"].startswith("data:text/javascript"))


class TestSaveAttachmentGuard(TransactionCase):
    """The extension whitelist and mimetype lookup share one mapping."""

    def test_invalid_extension_rejected(self):
        bundle = AssetsBundle("test_assetsbundle.extguard", [], env=self.env)
        with self.assertRaisesRegex(ValueError, "Invalid asset extension"):
            bundle.save_attachment("exe", "content")

    def test_mimetypes_match_extension(self):
        bundle = AssetsBundle("test_assetsbundle.extguard2", [], env=self.env)
        self.assertEqual(bundle.save_attachment("min.xml", "<t/>").mimetype, "text/xml")
        self.assertEqual(
            bundle.save_attachment("js.map", "{}").mimetype, "application/json"
        )


class TestScssMinifySkipsRegex(TransactionCase):
    """Dart Sass output is never regex-minified, debug mode included."""

    def test_debug_scss_content_untouched(self):
        bundle = AssetsBundle(
            "test_assetsbundle.scssmin", [], env=self.env, debug_assets=True
        )
        asset = ScssStylesheetAsset(bundle, inline='x { content: "a  b"; }')
        self.assertIn('"a  b"', asset.minify())


class TestBridgePersistenceDecoupled(TransactionCase):
    """Bridge attachments persist out-of-band, on a writable cursor too.

    Cache-coherence fix: ``_persist_bridge_shims`` used to ``create`` on the
    request cursor whenever it was writable, so a request-cursor rollback
    could strand the assets ormcache pointing at bridge URLs whose rows never
    committed — a hard 404 with no rebuild path. Persistence now always routes
    through the independent read-write cursor. The cross-transaction
    durability itself is a production property (``registry.cursor(readonly=
    False)`` really commits — a ``TestCursor`` releases its savepoint into the
    shared transaction), so these tests mock that seam and assert which path
    is taken — on a writable cursor, not only a read-only one — plus the
    data:-URI boundary.

    Content is unique per test on purpose: bridge URLs are content-addressed,
    so shared content plus any unmocked persist elsewhere in the suite would
    make these order-dependent.
    """

    def test_writable_cursor_routes_through_rw_cursor(self):
        bundle = AssetsBundle("web.assets_web", [], env=self.env)
        self.assertFalse(
            self.env.cr.readonly, "precondition: the request cursor is writable"
        )
        with patch.object(
            BridgeShimManager, "_persist_bridges_via_rw_cursor", return_value=True
        ) as escalate:
            urls = bundle._persist_bridge_shims(
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
            urls = bundle._persist_bridge_shims(
                {"@web/degraded": "export const degraded = 2;"}
            )
        self.assertTrue(
            urls["@web/degraded"].startswith("data:text/javascript"),
            "data: URIs are reserved for a genuinely unwritable primary",
        )


class TestXmlBundleUrlEscaping(TransactionCase):
    """generate_xml_bundle escapes the asset URL, not only the template body."""

    def test_url_with_backtick_cannot_break_the_template_literal(self):
        files = [
            {
                "url": "/test/evil`${1 + 1}.xml",
                "filename": None,
                "content": (
                    "<templates>"
                    "<t t-name='probe.tpl'><div>${body}</div></t>"
                    "</templates>"
                ),
                "last_modified": 1.0,
            }
        ]
        bundle = AssetsBundle(
            "test_assetsbundle.urlesc", files, env=self.env, css=False, js=True
        )
        js = bundle.generate_xml_bundle()
        # The template body stays a backtick literal and is escaped...
        self.assertIn(r"\${body}", js)
        # ...and the URL is now a JSON-quoted string argument: its backtick
        # and ``${`` are escaped/quoted, so the raw sequence cannot appear
        # inside an unescaped backtick literal.
        self.assertNotIn("`/test/evil`", js)
        self.assertIn(json.dumps("/test/evil`${1 + 1}.xml"), js)


class TestAuditRegressionFixes(TransactionCase):
    """Regressions pinned by the 2026-06-11 assetsbundle audit."""

    def _bundle(self, name="test_assetsbundle.audit_fix"):
        return AssetsBundle(name, [], env=self.env)

    def test_template_elements_skip_processing_instructions(self):
        """A PI inside ``<templates>`` is dropped instead of aborting xml().

        The XML parser strips comments (``remove_comments=True``) but keeps
        processing instructions; pre-fix the PI reached ``xml()`` first and
        raised a misleading "Template name is missing." for the whole bundle.
        """
        bundle = self._bundle()
        asset = XMLAsset(
            bundle,
            inline=(
                '<templates><?xml-stylesheet href="x"?>'
                '<t t-name="audit.pi"><div/></t></templates>'
            ),
        )
        elems = asset.template_elements
        self.assertEqual(len(elems), 1)
        self.assertEqual(elems[0].get("t-name"), "audit.pi")
        bundle.templates = [asset]
        blocks = bundle.xml()
        self.assertEqual(blocks[0]["type"], "templates")

    # Epoch-0 mtime preservation is pinned by
    # ``test_audit_challenge.TestAuditEpochMtime`` (updated with the fix).

    def test_fetch_content_preserves_not_found_subclass(self):
        """``AssetNotFoundError`` exits ``_fetch_content`` unwrapped.

        Pre-fix the trailing ``except (AssetError, ValueError)`` arm
        re-wrapped it into a plain ``AssetError``, erasing the not-found
        signal that ``_resolve_attachment`` raised.
        """
        asset = WebAsset(self._bundle(), url="/test_assetsbundle/missing.js")
        with self.assertRaises(AssetNotFoundError) as cm:
            asset._fetch_content()
        self.assertIs(type(cm.exception), AssetNotFoundError)

    def test_css_minify_preserves_legal_comments(self):
        """``/*! … */`` license headers survive regex minification.

        FontAwesome and Bootstrap dist ship their licenses as bang
        comments; both JS minification paths preserve them, the CSS
        path used to strip them.
        """
        asset = StylesheetAsset(
            self._bundle(),
            inline="/*! (c) Audit Corp */\n/* strip me */\nbody { color: red; }",
        )
        out = asset.minify()
        self.assertIn("/*! (c) Audit Corp */", out)
        self.assertNotIn("strip me", out)

    def test_validate_external_libs_follows_esbuild_pattern(self):
        """Validation derives pattern coverage from the esbuild constant.

        Any ``@odoo/*`` specifier is covered by the pattern-level
        ``--external`` flag (no hand-maintained allowlist to drift);
        an unaliased non-pattern specifier still fails fast.
        """
        AssetsBundle._validate_external_libs({"@odoo/owl", "@odoo/not-listed"})
        with self.assertRaises(ValueError):
            AssetsBundle._validate_external_libs({"left-pad"})


class TestCompileCssImportSanitizeUnit(BaseCase):
    """``compile_css`` @import sanitizer, exercised without a DB.

    Regression (2026-06-13): the dedup key was ``@import "url"`` with the
    trailing media query left OUT of the regex match, so a second import of
    the same url with a DIFFERENT media query collapsed to "" and orphaned
    the media tail (e.g. ``\\n print;``) — invalid SCSS that drops the whole
    bundle to the degraded-CSS banner. ``rx_preprocess_imports`` now captures
    the post-quote tail so the key is media-aware and a deduped removal takes
    its media query with it.
    """

    @staticmethod
    def _sanitize(source):
        # A passthrough compiler exercises only the @import sanitization with
        # no Sass subprocess; compile_css touches only ``rx_preprocess_imports``
        # and ``css_errors`` before the compiler call, so a tiny shim suffices.
        class _Shim:
            rx_preprocess_imports = AssetsBundle.rx_preprocess_imports

            def __init__(self):
                self.css_errors = []

        shim = _Shim()
        out = AssetsBundle.compile_css(shim, lambda s: s, source)
        return out, shim.css_errors

    def test_single_media_query_preserved(self):
        out, errs = self._sanitize('@import "foo" screen;')
        self.assertEqual(out, '@import "foo" screen;')
        self.assertFalse(errs)

    def test_complex_media_query_preserved(self):
        out, _ = self._sanitize('@import "foo" screen and (min-width: 600px);')
        self.assertEqual(out, '@import "foo" screen and (min-width: 600px);')

    def test_distinct_media_keeps_both(self):
        out, _ = self._sanitize('@import "foo" screen;\n@import "foo" print;')
        self.assertEqual(out, '@import "foo" screen;\n@import "foo" print;')

    def test_duplicate_with_media_removed_without_orphan(self):
        # Same url + same media => deduped; the media tail goes with it
        # (compile_css .strip()s the output, hence no trailing newline).
        out, _ = self._sanitize('@import "foo" screen;\n@import "foo" screen;')
        self.assertEqual(out, '@import "foo" screen;')

    def test_exact_duplicate_deduped(self):
        out, _ = self._sanitize('@import "foo";\n@import "foo";')
        self.assertEqual(out, '@import "foo";')

    def test_bare_legit_import_kept(self):
        out, errs = self._sanitize('@import "lib/partial";')
        self.assertEqual(out, '@import "lib/partial";')
        self.assertFalse(errs)

    def test_forbidden_local_import_with_media_leaves_no_orphan(self):
        with self.assertLogs("odoo.addons.base.models.assetsbundle", "WARNING"):
            out, errs = self._sanitize('@import "./x.scss" screen;')
        self.assertEqual(out, "")
        self.assertTrue(errs)
