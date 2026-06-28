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

import logging
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from odoo import SUPERUSER_ID, api
from odoo.db import db_connect
from odoo.modules.registry import Registry
from odoo.tests.common import BaseCase, TransactionCase, get_db_name
from odoo.tools.assets.esbuild import _find_esbuild
from odoo.tools.assets.esm_bridges import BridgeShimManager
from odoo.tools.assets.esm_graph import _MODULE_SYNTAX_RE
from odoo.tools.assets.esm_registry import esm_registry, validate_esm_config
from odoo.tools.json import scriptsafe as json
from odoo.tools.misc import file_path

from odoo.addons.base.models.assetsbundle import (
    ANY_UNIQUE,
    AssetAttachmentStore,
    AssetError,
    AssetNotFoundError,
    AssetsBundle,
    CompileError,
    CssPipeline,
    JavascriptAsset,
    PreprocessedCSS,
    ScssStylesheetAsset,
    StylesheetAsset,
    WebAsset,
    XMLAsset,
    XMLAssetError,
    _cached_module_classification,
    _check_rtlcss,
    is_odoo_module,
)
from odoo.addons.base.models.ir_attachment import IrAttachment

_logger = logging.getLogger(__name__)

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

    def test_attachment_values_pins_the_write_side_identity(self):
        """``_attachment_values`` is the single create payload for both
        ``save_attachment`` and the cross-params fallback copy. Its identity
        columns must match what ``get_attachments`` / ``_clean_attachments``
        filter on (``res_model='ir.ui.view'``, ``res_id`` -> 0, ``public``),
        so the read and write halves cannot drift."""
        values = self._store([])._attachment_values(
            name="web.assets_web.min.css",
            mimetype="text/css",
            raw=b"x{}",
            url="/web/assets/abc1234/web.assets_web.min.css",
        )
        self.assertEqual(
            values,
            {
                "name": "web.assets_web.min.css",
                "mimetype": "text/css",
                "res_model": "ir.ui.view",
                "res_id": False,
                "type": "binary",
                "public": True,
                "raw": b"x{}",
                "url": "/web/assets/abc1234/web.assets_web.min.css",
            },
        )


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
            bundle._store._unlink_attachments(attachments)
        marked = {call.args[-1] for call in file_delete.call_args_list}
        self.assertEqual(marked, expected_fnames)
        self.assertFalse(
            self.env["ir.attachment"].search(
                [("url", "like", "/web/assets/hardeningtest/%")]
            )
        )


class TestCleanAttachmentsIdentityFilter(TransactionCase):
    """``_clean_attachments`` GCs only rows the serving read would surface.

    Regression (2026-06-18): the delete filtered on ``url`` + ``public`` only,
    while ``get_attachments`` also filters ``res_model`` / ``res_id`` /
    ``create_uid``. So a public row that merely shares the bundle's URL pattern
    but is not a served bundle artifact (different ``res_model``) could be
    deleted despite being invisible to the serving path. The two halves now
    cover the same set.
    """

    def test_rogue_same_url_row_survives_clean(self):
        bundle = AssetsBundle("test_assetsbundle.c2filter", [], env=self.env)
        store = bundle._store
        real = store.save_attachment("min.css", "body{color:red}")
        rogue = self.env["ir.attachment"].create(
            {
                "name": "rogue",
                "type": "binary",
                "raw": b"x",
                "res_model": "ir.attachment",  # NOT ir.ui.view
                "res_id": 0,
                "public": True,
                "url": real.url,  # same URL the bundle artifact uses
            }
        )
        # Clean with a keep_url that excludes neither row by the ``!=`` clause,
        # so only the identity columns decide what is deleted.
        store._clean_attachments("min.css", keep_url="/web/assets/nomatch/x.min.css")
        self.assertFalse(real.exists(), "the real outdated artifact is GC'd")
        self.assertTrue(rogue.exists(), "the rogue non-ir.ui.view row is left alone")


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
        """minify_js returning None degrades to the raw source, never an error.

        Uses a NESTED template literal so the gate actually routes to esbuild: a
        ``${``-free backtick file now stays on rjsmin (see TestBacktickMinifyGate
        in test_review_followup), where minify_js is never called and this
        fallback would not be exercised.
        """
        src = "window.testRaw = `outer ${`in  ner`} end`;\nvar    spaced = 1;\n"
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
    """The advertised css version is independent of preprocess_css.

    preprocess_css no longer mutates ``stylesheets`` (the Sass-hoisted @at-rules
    go to the pipeline's ``_rendered_assets``), so the version is trivially
    stable across it — and the source list it reads is left pristine.
    """

    def test_source_list_untouched_by_preprocess(self):
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
            # The source list is NOT mutated (was grown to 2 by the old insert)...
            self.assertEqual(len(bundle.stylesheets), 1)
            # ...the hoisted @at-rules fragment lives in the render list instead.
            self.assertEqual(len(bundle._css._rendered_assets), 2)
            # ...and the advertised URL stays stable.
            self.assertEqual(bundle.get_version("css"), version_before)

    def test_version_independent_of_call_order(self):
        """The version does not depend on whether get_version runs before or
        after preprocess_css — it reads the __init__ snapshot, and preprocess
        does not touch the live ``stylesheets`` list at all.
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

            # Bundle B (identical): preprocess FIRST, THEN read the version.
            # Pre-fix this returned a different hash (the at-rules insert moved
            # the live list); now the list is untouched.
            bundle_b = AssetsBundle(
                "test_assetsbundle.cssorder", files, env=self.env, js=False
            )
            bundle_b.preprocess_css()
            self.assertEqual(
                len(bundle_b.stylesheets), 1, "source list not mutated"
            )
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
            urls = bundle._bridges._persist_bridge_shims({"@web/test_hash": "export default 1;"})
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
            urls = bundle._bridges._persist_bridge_shims({"@web/ro_test": "export default 1;"})
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
            urls = bundle._bridges._persist_bridge_shims({"@web/ro_test2": "export default 2;"})
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


class TestDebugCssMinifySkipsRegex(BaseCase):
    """Plain-CSS ``minify`` skips the regex passes in debug mode.

    In debug, ``css_with_sourcemap`` rebuilds the served bundle from each
    asset's ``content`` and the minified join ``preprocess`` produces is
    consumed only for @import extraction — so running ``_minify_css_body`` per
    render is wasted work. The guard mirrors ``ScssStylesheetAsset.minify``;
    the served debug CSS is unminified either way, so output stays
    byte-identical. Production must still minify (there the join IS the
    ``.min.css`` body). The minify reads only ``bundle.is_debug_assets`` and
    ``content``, so a fake bundle exercises the guard without a DB.
    """

    def _minify(self, *, debug):
        bundle = SimpleNamespace(is_debug_assets=debug)
        return StylesheetAsset(bundle, inline="body {  color:   red ; }").minify()

    def test_debug_leaves_content_unminified(self):
        # The collapsed whitespace surviving proves _minify_css_body was skipped:
        # had it run, the double space would be gone.
        self.assertIn("  color", self._minify(debug=True))

    def test_production_minifies(self):
        out = self._minify(debug=False)
        self.assertNotIn("  color", out)
        self.assertIn("body{", out)


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
            urls = bundle._bridges._persist_bridge_shims({"@web/decoupled": "export const decoupled = 1;"})
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
            urls = bundle._bridges._persist_bridge_shims({"@web/degraded": "export const degraded = 2;"})
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
        # A passthrough compiler exercises only the @import sanitization with no
        # Sass subprocess; compile_css touches ``CssPipeline.rx_preprocess_imports``
        # (a class attr) and the bundle's ``css_errors`` before the compiler
        # call, so a tiny fake bundle suffices.
        bundle = SimpleNamespace(css_errors=[])
        out = CssPipeline(bundle).compile_css(lambda s: s, source)
        return out, bundle.css_errors

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

    def test_repeated_forbidden_import_reported_once(self):
        # Regression (2026-06-17): the forbidden-import check used to run BEFORE
        # the dedup check and return without recording the statement as seen, so
        # the same forbidden import repeated across concatenated files appended
        # one ``css_errors`` entry (and emitted one server warning) per
        # occurrence. ``css_errors`` is joined verbatim into the degraded-CSS
        # banner, so N copies stacked into N identical banner lines. Deduping
        # first collapses them to one.
        with self.assertLogs("odoo.addons.base.models.assetsbundle", "WARNING") as cm:
            out, errs = self._sanitize(
                '@import "./a.scss";\n@import "./a.scss";\n@import "./a.scss";'
            )
        self.assertEqual(out, "")
        self.assertEqual(len(errs), 1, "one forbidden statement => one error")
        self.assertEqual(
            sum("forbidden" in m for m in cm.output), 1, "and one server warning"
        )

    def test_distinct_forbidden_imports_each_reported(self):
        # Dedup keys on the full statement, so two DIFFERENT forbidden imports
        # are still each reported — the collapse is per-statement, not blanket.
        with self.assertLogs("odoo.addons.base.models.assetsbundle", "WARNING"):
            _out, errs = self._sanitize('@import "./a.scss";\n@import "./b.scss";')
        self.assertEqual(len(errs), 2)

    # ── comment / string awareness (regression 2026-06-18) ──
    # The sanitizer scanned raw text, so an @import inside a comment or string
    # was treated as a directive: it could poison the dedup set (dropping a real
    # later import) or trip the security check (degrading the whole bundle).

    @staticmethod
    def _code_imports(out):
        """@import statements surviving in actual code (not commented out)."""
        return [ln for ln in out.splitlines() if ln.strip().startswith("@import")]

    def test_line_commented_import_does_not_poison_dedup(self):
        # ``// @import "mixins";`` in an earlier file must NOT suppress the real
        # ``@import "mixins";`` later — the previously-silent data-loss bug.
        out, errs = self._sanitize(
            '// @import "mixins";\n.a{}\n@import "mixins";\n.b{}'
        )
        self.assertEqual(self._code_imports(out), ['@import "mixins";'])
        self.assertFalse(errs)

    def test_forbidden_import_in_line_comment_ignored(self):
        # A commented-out local import must not raise the security error that
        # would replace the whole bundle with the red error banner.
        out, errs = self._sanitize('// @import "theme/foo.scss";\n.a{}')
        self.assertFalse(errs)
        self.assertIn('// @import "theme/foo.scss";', out)

    def test_forbidden_import_in_block_comment_ignored(self):
        out, errs = self._sanitize('/* @import "theme/foo.scss"; */\n.a{}')
        self.assertFalse(errs)
        self.assertIn('/* @import "theme/foo.scss"; */', out)

    def test_import_inside_string_value_left_intact(self):
        out, errs = self._sanitize('.c::before{content:"@import bad"}\n@import "ok";')
        self.assertIn('content:"@import bad"', out)
        self.assertEqual(self._code_imports(out), ['@import "ok";'])
        self.assertFalse(errs)

    def test_real_forbidden_import_still_caught(self):
        # Comment-awareness must NOT weaken the security check for real code.
        with self.assertLogs("odoo.addons.base.models.assetsbundle", "WARNING"):
            out, errs = self._sanitize('@import "./evil.scss";\n.a{}')
        self.assertTrue(errs)
        self.assertNotIn("evil", out)


class TestEmbeddedSassFallbackWarning(BaseCase):
    """The embedded-Sass → CLI fallback is surfaced once at WARNING.

    Regression (2026-06-18): a broken sass-embedded install logged the
    degrade-to-CLI only at DEBUG, so every bundle silently paid the slower
    per-compile subprocess with no operator-visible signal.
    """

    def test_warns_once_then_debug(self):
        with patch.object(ScssStylesheetAsset, "_embedded_fallback_warned", False):
            with self.assertLogs(
                "odoo.addons.base.models.assetsbundle", "WARNING"
            ) as cm:
                ScssStylesheetAsset._warn_embedded_fallback(RuntimeError("boom"))
            self.assertEqual(sum("markedly slower" in m for m in cm.output), 1)
            # A second fallback must NOT emit another WARNING (only DEBUG).
            with self.assertLogs(
                "odoo.addons.base.models.assetsbundle", "DEBUG"
            ) as cm2:
                ScssStylesheetAsset._warn_embedded_fallback(RuntimeError("boom"))
            self.assertEqual(sum("markedly slower" in m for m in cm2.output), 0)


class _NativeStubBundle:
    """Minimal bundle exposing only what ``get_native_module_data`` reads."""

    name = "web.assets_test"

    def __init__(self, modules):
        self.native_modules = modules
        self.bridge_input = None

    # ``get_native_module_data`` builds bridges through the ``_bridges``
    # collaborator (see AssetsBundle); the stub is its own bridge layer, so
    # ``self._bridges._build_native_to_legacy_bridge`` lands on the method below.
    @property
    def _bridges(self):
        return self

    def _build_native_to_legacy_bridge(self, specifiers, modules=None):
        self.bridge_input = set(specifiers)
        return {"@legacy/shim": "data:text/javascript,"}


class TestNativeModuleDataSpecifiers(BaseCase):
    """``get_native_module_data`` derives bridge specifiers from import-map keys.

    The 2026-06 audit-follow-up dropped the parallel ``native_specifiers``
    accumulator: every key written to ``import_map`` (module path, ``/index``
    long form, declared alias) is one of the bundle's own specifiers, so the
    import-map keys ARE the "owned by this bundle" set handed to the bridge
    builder. These lock that equivalence, the ``/index`` long form that must
    survive the simplification, and the ``with_bridges=False`` short-circuit.
    """

    def _asset(self, url):
        # Inline source + url: module_path (from url) and parsed_header (from
        # content) both resolve without an env or a live attachment.
        return JavascriptAsset(
            _NativeStubBundle([]), inline="export const x = 1;\n", url=url
        )

    def _data(self, urls, **kw):
        bundle = _NativeStubBundle([self._asset(u) for u in urls])
        return bundle, AssetsBundle.get_native_module_data(bundle, **kw)

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
        # The builder never ran, so no specifier set was captured.
        self.assertIsNone(bundle.bridge_input)


class TestAssetErrorTaxonomy(BaseCase):
    """Content/parse failures share the ``AssetError`` base; compile errors don't."""

    def test_asset_error_is_the_common_base(self):
        self.assertTrue(issubclass(AssetNotFoundError, AssetError))
        self.assertTrue(issubclass(XMLAssetError, AssetError))

    def test_compile_error_is_a_separate_family(self):
        # CompileError is caught explicitly alongside SassCompileError, never
        # via an ``except AssetError`` net — so it must stay outside that tree.
        self.assertFalse(issubclass(CompileError, AssetError))
        self.assertTrue(issubclass(CompileError, RuntimeError))


class TestEsmGraphCanonicalHome(BaseCase):
    """ESM-graph predicates live in ``odoo.tools.assets.esm_graph``, not as re-exports."""

    def test_predicates_resolve_from_esm_graph(self):
        from odoo.tools.assets import esm_graph

        self.assertTrue(callable(esm_graph.is_native_module))
        self.assertTrue(callable(esm_graph._parse_odoo_module_header))

    def test_dead_reexport_not_resurrected(self):
        import odoo.addons.base.models.assetsbundle as ab

        # ``_parse_odoo_module_header`` stays (used internally by
        # JavascriptAsset.parsed_header); the unused ``is_native_module``
        # re-export was removed and must not creep back as "historical surface".
        self.assertTrue(hasattr(ab, "_parse_odoo_module_header"))
        self.assertFalse(hasattr(ab, "is_native_module"))


class TestStylesheetErrorInversion(BaseCase):
    """StylesheetAsset records fetch errors on itself; the bundle harvests them.

    The 2026-06 audit-follow-up inverted a leaf-into-parent coupling:
    ``StylesheetAsset._fetch_content`` used to append to
    ``self.bundle.css_errors`` directly. It now records onto ``self.errors``,
    and ``AssetsBundle.preprocess_css`` collects from each asset — so the asset
    can be exercised without a live bundle that owns a ``css_errors`` list.
    """

    class _StubBundle(AssetsBundle):
        # Skip the env / esm_registry-heavy __init__; inherit the class-level
        # regexes and the real ``preprocess_css`` harvest path.
        def __init__(self):
            self.stylesheets = []
            self.css_errors = []
            self.rtl = False
            self.autoprefix = False

    def test_asset_records_error_without_touching_bundle(self):
        class BareBundle:  # deliberately has no css_errors attribute
            pass

        asset = StylesheetAsset(BareBundle(), url="/web/static/src/css/missing.css")
        with patch.object(WebAsset, "_fetch_content", side_effect=AssetError("boom")):
            out = asset._fetch_content()
        self.assertEqual(out, "")
        self.assertEqual(asset.errors, ["boom"])
        # The old design appended to self.bundle.css_errors here and would have
        # raised AttributeError on a bundle that has no such list.
        self.assertFalse(hasattr(asset.bundle, "css_errors"))

    def test_bundle_harvests_asset_errors(self):
        bundle = self._StubBundle()
        good = StylesheetAsset(bundle, inline=".ok{color:red}")  # inline -> no fetch
        bad1 = StylesheetAsset(bundle, url="/web/static/src/css/x1.css")
        bad2 = StylesheetAsset(bundle, url="/web/static/src/css/x2.css")
        bundle.stylesheets = [good, bad1, bad2]

        def fake_fetch(self):
            raise AssetError(f"missing {self.url}")

        with patch.object(WebAsset, "_fetch_content", fake_fetch):
            result = bundle.preprocess_css()

        self.assertIn(".ok{color:red}", result)  # the good asset still ships
        self.assertEqual(good.errors, [])
        self.assertEqual(
            bundle.css_errors,
            [
                "missing /web/static/src/css/x1.css",
                "missing /web/static/src/css/x2.css",
            ],
        )

    def test_preprocess_css_does_not_double_report_on_rerun(self):
        # preprocess_css rebuilds css_errors from scratch each call, so running
        # it twice must not accumulate duplicates (the harvest is idempotent).
        bundle = self._StubBundle()
        bad = StylesheetAsset(bundle, url="/web/static/src/css/x.css")
        bundle.stylesheets = [bad]

        def fake_fetch(self):
            raise AssetError("missing x.css")

        with patch.object(WebAsset, "_fetch_content", fake_fetch):
            bundle.preprocess_css()
            bundle.preprocess_css()

        self.assertEqual(bundle.css_errors, ["missing x.css"])


class TestPlainCssMinifyStringHandling(BaseCase):
    """The plain-CSS regex minifier is string- and comment-aware.

    ``StylesheetAsset.minify`` minifies the CSS *between* string literals and
    comments only: it whitespace/brace-collapses ordinary CSS, keeps string
    literals byte-for-byte (so ``content:`` values survive), drops ordinary
    comments, and keeps ``/*! … */`` legal comments verbatim. The old four-
    ``re.sub`` pipeline did all of this string-unaware and corrupted multi-space
    or brace/comment-bearing ``content:`` literals; these tests pin the fix.

    The SCSS path is unaffected (``ScssStylesheetAsset.minify`` returns the Dart
    Sass output untouched — see ``TestScssMinifySkipsRegex``).

    No DB / env: ``_minify_css_body`` is a pure classmethod, so it is called
    directly; ``minify()`` only wraps it in the per-file header.
    """

    @staticmethod
    def _min(css):
        return StylesheetAsset._minify_css_body(css)

    def test_double_space_inside_string_is_preserved(self):
        self.assertEqual(self._min('x { content: "a  b"; }'), 'x{content: "a  b";}')

    def test_braces_inside_string_are_preserved(self):
        self.assertEqual(self._min('x { content: "{ }"; }'), 'x{content: "{ }";}')

    def test_comment_sequence_inside_string_is_preserved(self):
        # The old comment-strip reached into strings; the new tokenizer treats a
        # ``/* */`` opened inside a string as string text.
        out = self._min('x { content: "/* not a comment */"; }')
        self.assertIn('"/* not a comment */"', out)

    def test_single_quoted_string_is_preserved(self):
        self.assertEqual(self._min("x { content: '  y  '; }"), "x{content: '  y  ';}")

    def test_escaped_quote_does_not_end_the_string(self):
        # ``\\"`` is string content, not a terminator — the whole literal survives.
        out = self._min(r'x { content: "a\"  b"; }')
        self.assertIn(r'"a\"  b"', out)

    def test_ordinary_comment_is_still_stripped(self):
        out = self._min("a { color: red; } /* drop me */ b { color: blue; }")
        self.assertNotIn("drop me", out)
        # whitespace flanking the dropped comment collapses across it, exactly
        # as the legacy pipeline did (the rules abut: ``}b``).
        self.assertEqual(out, "a{color: red;}b{color: blue;}")

    def test_legal_comment_is_kept_verbatim(self):
        out = self._min("/*!  License  */\n.a {\n  color: red;\n}")
        self.assertIn("/*!  License  */", out)  # whitespace inside it untouched
        self.assertIn(".a{color: red;}", out)  # surrounding CSS still minified

    def test_minification_still_applies_outside_strings(self):
        out = self._min("a   {\n  color :  red ;\n}\n\n  b{}")
        self.assertNotIn("  ", out)  # no double spaces in ordinary CSS
        self.assertEqual(out, "a{color : red ;}b{}")
        # (SCSS-path string safety is covered by TestScssMinifySkipsRegex.)


class TestEsmAttachmentSidecars(TransactionCase):
    """``_save_esm_attachment`` writes meta/sourcemap sidecars from its params.

    The esbuild metafile and source map used to travel from
    ``esbuild_native_bundle`` to ``_save_esm_attachment`` via a
    ``AssetsBundle._last_metafile`` / ``_last_sourcemap`` side-channel — hidden
    mutable state on the bundle, read across the module boundary. They are now
    passed as explicit parameters: only the main-bundle save supplies them; the
    ``.templates.esm.js`` saves pass nothing. This pins both halves of that
    contract (which previously had no end-to-end test at all).
    """

    def _att(self, url):
        return (
            self.env["ir.attachment"]
            .sudo()
            .search([("url", "=", url), ("public", "=", True)])
        )

    def test_main_bundle_save_writes_both_sidecars(self):
        url = self.env["ir.qweb"]._save_esm_attachment(
            "test_assetsbundle.sidecar_main",
            "export const main = 1;\n//# sourceMappingURL=x.map",
            metafile='{"inputs":{}}',
            sourcemap='{"version":3}',
        )
        self.assertTrue(url.endswith(".esm.js"))
        self.assertTrue(self._att(url), "the main bundle attachment must exist")
        meta_url = url[: -len(".esm.js")] + ".meta.json"
        self.assertTrue(self._att(meta_url), "metafile sidecar must be persisted")
        self.assertTrue(self._att(url + ".map"), "sourcemap sidecar must be persisted")

    def test_template_save_writes_no_sidecars(self):
        # No metafile/sourcemap (the ``.templates.esm.js`` path) -> no sidecars.
        url = self.env["ir.qweb"]._save_esm_attachment(
            "test_assetsbundle.sidecar_tpl.templates",
            "export const tpl = 2;",
        )
        self.assertTrue(self._att(url), "the templates attachment must exist")
        meta_url = url[: -len(".esm.js")] + ".meta.json"
        self.assertFalse(self._att(meta_url), "no metafile sidecar without a metafile")
        self.assertFalse(self._att(url + ".map"), "no sourcemap sidecar without one")


class TestCssErrorBanner(BaseCase):
    """The degraded-CSS banner builder is pure and idempotent.

    ``AssetsBundle._render_css_error_banner`` was extracted from ``css()`` so
    its escaping and (crucially) its no-stacking behavior are unit-testable —
    previously this logic was reachable only through a slow ``HttpCase`` browser
    tour (``css_error_tour``), which never asserted either property.
    """

    H = CssPipeline._CSS_ERROR_HEADER

    def test_message_is_escaped_for_a_css_string_literal(self):
        out = AssetsBundle._render_css_error_banner(['boom "x" *\n y'], "")
        self.assertIn(r"\"x\"", out)  # quotes can't close the content: value
        self.assertIn(r"\A", out)  # newline -> CSS escaped newline
        self.assertIn(r"\*", out)  # star can't open a comment
        self.assertIn("A css error occurred", out)

    def test_previous_good_css_is_carried_over(self):
        out = AssetsBundle._render_css_error_banner(["e"], ".keep{color:red}")
        self.assertTrue(out.startswith(".keep{color:red}"))
        self.assertIn(self.H, out)

    def test_banner_does_not_stack_across_repeated_errors(self):
        # The whole point of the split-on-header: re-rendering over an output
        # that already carries a banner must replace it, not append a second.
        first = AssetsBundle._render_css_error_banner(["err_one"], ".keep{}")
        second = AssetsBundle._render_css_error_banner(["err_two"], first)
        self.assertEqual(second.count(self.H), 1, "exactly one banner survives")
        self.assertIn(".keep{}", second)
        self.assertIn("err_two", second)
        self.assertNotIn("err_one", second)

    def test_multiple_errors_are_joined_into_one_message(self):
        out = AssetsBundle._render_css_error_banner(["a", "b"], "")
        self.assertIn(r"a\Ab", out)  # newline-joined, then escaped


class TestVendoredCssMinifyCorpus(BaseCase):
    """The string-aware minifier is a semantic no-op on every shipped .css file.

    Safety net for the string/comment-awareness fix: run the new minifier and a
    faithful copy of the legacy four-``re.sub`` pipeline over EVERY plain ``.css``
    file in the loaded addons (FontAwesome, Bootstrap dist, every vendored lib),
    and assert their outputs are identical once string literals and legal
    comments are masked. In other words, the only differences the fix introduces
    versus the battle-tested old code live strictly inside strings (which the old
    code corrupted) and legal-comment interiors (which it reflowed) — both
    semantically inert. A real structural drift on any shipped file fails here
    with the offending path.

    No DB: minification is pure text; the corpus is read straight off disk.
    """

    @staticmethod
    def _legacy_minify(content):
        # Verbatim reproduction of the pre-fix StylesheetAsset.minify pipeline.
        content = re.sub(r"/\*# sourceMappingURL=.*", "", content)
        content = re.sub(r"/\*(?!!).*?\*/", "", content, flags=re.DOTALL)
        content = re.sub(r"\s+", " ", content)
        return re.sub(r" *([{}]) *", r"\1", content)

    @staticmethod
    def _mask(css):
        # Blank out the two spans the fix is allowed to differ on, so what
        # remains is the structural CSS that must match the legacy output.
        css = re.sub(r"/\*!.*?\*/", "<C>", css, flags=re.DOTALL)
        css = re.sub(r'"(?:[^"\\]|\\.)*"', "<S>", css)
        return re.sub(r"'(?:[^'\\]|\\.)*'", "<S>", css)

    def _shipped_css_files(self):
        import odoo.addons

        seen = set()
        for root in odoo.addons.__path__:
            for path in Path(root).rglob("*.css"):
                if path.name.endswith(".min.css") or path in seen:
                    continue
                seen.add(path)
                yield path

    def test_minify_is_semantically_identical_to_legacy_on_shipped_css(self):
        checked = differed = 0
        for path in self._shipped_css_files():
            try:
                src = path.read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue
            new = StylesheetAsset._minify_css_body(src)
            legacy = self._legacy_minify(src)
            self.assertEqual(
                self._mask(new),
                self._mask(legacy),
                f"string-aware minify drifted structurally on {path}",
            )
            checked += 1
            differed += new != legacy
        self.assertGreater(checked, 0, "no shipped .css files were found to check")
        # Surfaced so the corpus size and how many files the fix actually changes
        # (string/legal-comment differences) are visible in the test log.
        _logger.info(
            "vendored-css minify corpus: %d files checked, %d changed (string/"
            "legal-comment only)",
            checked,
            differed,
        )


# ── coverage-gap batch (2026-06-17 audit follow-up) ────────────────────────
# Three behaviours that were present but only happy-path asserted: the JS
# source-map line mapping (only the header-offset constant was pinned), the RTL
# *transform* output (only URL naming / the flag were checked, never the flip),
# and ``_unlink_attachments`` under a genuinely concurrent lock (only the
# all-rows-deleted path, where ``deleted_ids`` trivially equals every id).

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _vlq_decode_mappings(mappings):
    """Decode a source-map v3 ``mappings`` string to ``[(gen_line, src_idx, orig_line)]``.

    The inverse of ``SourceMapGenerator._serialize_mappings`` (which has only an
    encoder), so the test reads back what the generator wrote. Generated lines
    are 1-based (one per ``;``); ``src_idx`` / ``orig_line`` are cumulative VLQ
    deltas, and ``orig_line`` is returned 1-based (the wire format stores it
    0-based, matching the generator's ``original_line - 1``).
    """
    out = []
    gen_line = 0
    src_idx = 0
    orig_line0 = 0  # 0-based cumulative original line
    for field in mappings.split(";"):
        gen_line += 1
        for seg in field.split(","):
            if not seg:
                continue
            vals = []
            shift = acc = 0
            for ch in seg:
                d = _B64.index(ch)
                acc += (d & 31) << shift
                if d & 32:
                    shift += 5
                else:
                    vals.append((acc >> 1) * (-1 if acc & 1 else 1))
                    acc = shift = 0
            if len(vals) >= 4:  # [genCol, srcIdxΔ, srcLineΔ, srcColΔ]
                src_idx += vals[1]
                orig_line0 += vals[2]
                out.append((gen_line, src_idx, orig_line0 + 1))
    return out


class TestJsSourceMapAccuracy(TransactionCase):
    """The debug JS source map maps bundle lines back to the right source line.

    Gap: ``test_js_header_line_count`` pins only the header-offset constant; the
    emitted ``mappings`` (the actual line correspondence ``JsPipeline.sourcemap_bundle``
    feeds the generator) were never decoded and checked. This builds a real debug
    bundle, reads the ``js.map`` attachment, decodes its VLQ mappings, and asserts
    the round trip: for every content-line mapping, the text at the mapped bundle
    line equals the text at the source line it claims to come from.
    """

    def test_map_round_trips_to_source_lines(self):
        a = "const a1 = 1;\nconst a2 = 2;\nconst a3 = 3;\n"
        b = "const b1 = 10;\nconst b2 = 20;\n"
        files = [
            {"url": "/test/a.js", "filename": None, "content": a, "last_modified": 1.0},
            {"url": "/test/b.js", "filename": None, "content": b, "last_modified": 1.0},
        ]
        bundle = AssetsBundle(
            "test_assetsbundle.srcmap",
            files,
            env=self.env,
            css=False,
            js=True,
            debug_assets=True,
        )
        js_attachment = bundle.js()
        body_lines = js_attachment.raw.decode().split("\n")

        smap = bundle.get_attachments("js.map")
        self.assertTrue(smap, "a js.map sibling must be produced in debug mode")
        raw = smap.raw.decode()
        # get_content() prefixes the XSSI guard ")]}'\n" before the JSON.
        data = json.loads(raw.split("\n", 1)[1] if raw.startswith(")]}'") else raw)

        self.assertEqual(data["sources"], ["/test/a.js", "/test/b.js"])
        self.assertTrue(data["mappings"], "mappings must not be empty")

        src_lines = {0: a.split("\n"), 1: b.split("\n")}
        checked = 0
        for gen_line, src_idx, orig_line in _vlq_decode_mappings(data["mappings"]):
            # Skip line 1 of each source: the verbose header region is also
            # mapped to original line 1, so line 1 is ambiguous by design.
            lines = src_lines[src_idx]
            if orig_line < 2 or orig_line > len(lines):
                continue
            expected = lines[orig_line - 1]
            if not expected.strip():
                continue
            self.assertEqual(
                body_lines[gen_line - 1],
                expected,
                f"map claims bundle line {gen_line} == "
                f"{data['sources'][src_idx]}:{orig_line}",
            )
            checked += 1
        self.assertGreaterEqual(checked, 3, "expected several content-line mappings")


@unittest.skipUnless(_check_rtlcss(), "rtlcss binary not available")
class TestRtlTransformOutput(TransactionCase):
    """RTL bundles actually flip directional properties (not just the URL).

    Gap: the RTL suite asserted URL naming (``…rtl…min.css``) and the ``rtl``
    flag, but never that rtlcss transformed the content. This builds an RTL CSS
    bundle with directional declarations and asserts left/right are swapped in
    the served ``min.css`` — the one thing rtlcss exists to do.
    """

    def test_directional_properties_are_flipped(self):
        files = [
            {
                "url": "/test/dir.css",
                "filename": None,
                "content": ".box { padding-left: 10px; margin-right: 5px; }",
                "last_modified": 1.0,
            }
        ]
        bundle = AssetsBundle(
            "test_assetsbundle.rtltransform",
            files,
            env=self.env,
            css=True,
            js=False,
            rtl=True,
        )
        out = bundle.css().raw.decode()
        self.assertFalse(bundle.css_errors, f"unexpected css_errors: {bundle.css_errors}")
        self.assertIn("padding-right", out, "padding-left must flip to padding-right")
        self.assertNotIn("padding-left", out)
        self.assertIn("margin-left", out, "margin-right must flip to margin-left")
        self.assertNotIn("margin-right", out)


class TestUnlinkAttachmentsSkipLockedPartial(BaseCase):
    """A row a concurrent txn holds locked is skipped, and NOT filestore-marked.

    Gap: ``test_deleted_rows_drive_file_marks`` covers only the all-deleted path,
    where ``deleted_ids`` (from ``RETURNING``) trivially equals every id — so the
    very reason the SQL filters marks by ``RETURNING`` (a ``SKIP LOCKED`` row that
    was NOT deleted) is unexercised. Real cross-transaction locking needs
    committed rows the test transaction can't provide, so this BaseCase manages
    its own real cursors: a committed two-row fixture, a second connection holding
    one row locked, then the actual ``_unlink_attachments`` on a third cursor.
    """

    def test_locked_row_survives_and_is_not_marked(self):
        db = get_db_name()
        reg = Registry(db)
        ids = []
        locker = None
        try:
            # committed fixture: two filestore-backed attachments
            with reg.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                atts = env["ir.attachment"].create(
                    [
                        {
                            "name": f"skiplock_{i}.js",
                            "type": "binary",
                            "raw": (f"// skip locked {i} " + "x" * 200).encode(),
                            "res_model": "ir.ui.view",
                            "res_id": 0,
                            "public": True,
                            "url": f"/web/assets/skiplocktest/{i}.js",
                        }
                        for i in range(2)
                    ]
                )
                env.flush_all()
                ids = atts.ids
                fname_by_id = {a.id: a.store_fname for a in atts}
                cr.commit()
            self.assertTrue(
                all(fname_by_id.values()), "fixture rows must use the filestore"
            )
            locked_id, free_id = ids[0], ids[1]

            # hold a lock on the first row from an independent connection
            locker = db_connect(db).cursor()
            locker.execute("SET lock_timeout = '2000ms'")
            locker.execute(
                "SELECT id FROM ir_attachment WHERE id = %s FOR NO KEY UPDATE",
                (locked_id,),
            )

            # run the REAL method on a third cursor; SKIP LOCKED must skip the row
            with reg.cursor() as cr:
                cr.execute("SET lock_timeout = '3000ms'")
                env = api.Environment(cr, SUPERUSER_ID, {})
                store = AssetsBundle(
                    "test_assetsbundle.skiplock", [], env=env
                )._store
                attachments = env["ir.attachment"].browse(ids)
                with patch.object(IrAttachment, "_file_delete") as file_delete:
                    store._unlink_attachments(attachments)
                marked = {call.args[-1] for call in file_delete.call_args_list}
                cr.commit()

            # only the deleted (unlocked) row's fname is marked; the locked one isn't
            self.assertEqual(
                marked,
                {fname_by_id[free_id]},
                "only the row SKIP LOCKED actually deleted may be filestore-marked",
            )
            with reg.cursor() as cr:
                cr.execute(
                    "SELECT id FROM ir_attachment WHERE id = ANY(%s)", (ids,)
                )
                survivors = {r[0] for r in cr.fetchall()}
            self.assertEqual(
                survivors, {locked_id}, "the locked row must survive SKIP LOCKED"
            )
        finally:
            if locker is not None:
                locker.connection.rollback()
                locker.close()
            if ids:
                with reg.cursor() as cr:
                    cr.execute("DELETE FROM ir_attachment WHERE id = ANY(%s)", (ids,))
                    cr.commit()
