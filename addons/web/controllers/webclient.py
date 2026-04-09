import logging
from typing import Any
from urllib.parse import quote as url_quote

import odoo.tools
from odoo import http
from odoo.http import Response, request
from odoo.modules import Manifest
from odoo.tools.misc import file_path

from .utils import _local_web_translations

_logger = logging.getLogger(__name__)


class WebClient(http.Controller):
    @http.route("/web/webclient/bootstrap_translations", type="jsonrpc", auth="none")
    def bootstrap_translations(self, mods: list[str] | None = None) -> dict[str, Any]:
        """Load local translations from *.po files, as a temporary solution
        until we have established a valid session. This is meant only
        for translating the login page and db management chrome, using
        the browser's language."""
        # For performance reasons we only load a single translation, so for
        # sub-languages (that should only be partially translated) we load the
        # main language PO instead - that should be enough for the login screen.
        lang = request.env.context["lang"].partition("_")[0]

        if mods is None:
            mods = odoo.tools.config["server_wide_modules"]
            if request.db:
                mods = request.env.registry._init_modules.union(mods)

        translations_per_module = {}
        for addon_name in mods:
            manifest = Manifest.for_addon(addon_name)
            if manifest and manifest["bootstrap"]:
                f_name = file_path(f"{addon_name}/i18n/{lang}.po")
                if not f_name:
                    continue
                translations_per_module[addon_name] = {
                    "messages": _local_web_translations(f_name)
                }

        return {"modules": translations_per_module, "lang_parameters": None}

    @http.route(
        "/web/webclient/translations",
        type="http",
        auth="public",
        cors="*",
        readonly=True,
    )
    def translations(
        self,
        hash: str | None = None,
        mods: str | None = None,
        lang: str | None = None,
    ) -> Response:
        """
        Load the translations for the specified language and modules

        :param hash: translations hash, which identifies a version of translations. This method only returns translations if their hash differs from the received one
        :param mods: the modules, a comma separated list
        :param lang: the language of the user
        :return:
        """
        if mods:
            mods = mods.split(",")
        else:
            mods = request.env.registry._init_modules.union(
                odoo.tools.config["server_wide_modules"]
            )

        if lang and lang not in {
            code for code, _ in request.env["res.lang"].sudo().get_installed()
        }:
            lang = None

        current_hash = (
            request.env["ir.http"]
            .with_context(cache_translation_data=True)
            ._get_web_translations_hash(mods, lang)
        )

        body = {
            "lang": lang,
            "hash": current_hash,
        }
        if current_hash != hash:
            if "translation_data" in request.env.cr.cache:
                # ormcache of _get_web_translations_hash was cold and fill the translation_data cache
                body.update(request.env.cr.cache.pop("translation_data"))
            else:
                # ormcache of _get_web_translations_hash was hot
                translations_per_module, lang_params = request.env[
                    "ir.http"
                ]._get_translations_for_webclient(mods, lang)
                body.update(
                    {
                        "lang_parameters": lang_params,
                        "modules": translations_per_module,
                        "multi_lang": len(
                            request.env["res.lang"].sudo().get_installed()
                        )
                        > 1,
                    }
                )

        # The type of the route is set to HTTP, but the rpc is made with a get and expects JSON
        return request.make_json_response(
            body,
            [
                ("Cache-Control", f"public, max-age={http.STATIC_CACHE_LONG}"),
            ],
        )

    @http.route("/web/webclient/version_info", type="jsonrpc", auth="none")
    def version_info(self) -> dict[str, Any]:
        return odoo.service.common.exp_version()

    @http.route("/web/tests", type="http", auth="user", readonly=True)
    def unit_tests_suite(self, mod: str | None = None, **kwargs: Any) -> Response:
        return request.render(
            "web.unit_tests_suite",
            {"session_info": {"view_info": request.env["ir.ui.view"].get_view_info()}},
        )

    @http.route("/web/tests/legacy", type="http", auth="user", readonly=True)
    def test_suite(self, mod: str | None = None, **kwargs: Any) -> Response:
        return request.render(
            "web.qunit_suite",
            {"session_info": {"view_info": request.env["ir.ui.view"].get_view_info()}},
        )

    @http.route(
        "/web/bundle/<string:bundle_name>",
        auth="public",
        methods=["GET"],
        readonly=True,
    )
    def bundle(self, bundle_name: str, **bundle_params: Any) -> Response:
        """
        Request the definition of a bundle, including its javascript and css bundled assets
        """
        if "lang" in bundle_params:
            request.update_context(
                lang=request.env["res.lang"]._get_code(bundle_params["lang"])
            )

        debug = bundle_params.get("debug", request.session.debug)
        debug_assets = debug and "assets" in debug

        # Lazy ESM bundles use native ESM in both production and debug.
        # In debug=assets, return individual specifiers for import().
        # In production, _get_asset_nodes() returns the esbuild bundle.
        from odoo.addons.base.models.assetsbundle import AssetsBundle
        is_lazy_esm = any(
            bundle_name in lazies
            for lazies in AssetsBundle.ESM_LAZY_BUNDLES.values()
        )
        use_esm = is_lazy_esm and debug_assets
        _logger.debug(
            "[BUNDLE-TRACE] /web/bundle/%s: debug=%s, is_lazy_esm=%s, "
            "use_esm=%s", bundle_name, debug, is_lazy_esm, use_esm,
        )

        files = request.env["ir.qweb"]._get_asset_nodes(
            bundle_name, debug=debug, js=True, css=True
        )

        # Separate ESM module scripts from legacy scripts/CSS.
        # _get_asset_nodes() returns <script type="module"> for ESM
        # bundles — these must be loaded via import(), not loadJS().
        esm_specifiers = []
        inline_esm_code = None
        data = []
        for tag, attrs in files:
            script_type = attrs.get("type", "")
            src = (
                attrs.get("src")
                or attrs.get("data-src")
                or attrs.get("href")
            )
            if tag == "script" and script_type == "module" and src:
                # ESM module — must be loaded via dynamic import()
                esm_specifiers.append(src)
            elif tag == "script" and script_type == "module" and not src:
                # Inline ESM (read-only transaction, e.g. test mode):
                # the esbuild code is inlined because ir.attachment
                # writes are unavailable.  Return it as inline_esm
                # for the client to load via Blob URL (data: URIs
                # don't inherit the page's import map).
                text = attrs.get("text", "")
                if text:
                    inline_esm_code = text
            elif tag == "script" and script_type in (
                "importmap", "text/plain",
            ):
                # Import maps and deferred placeholders are page-level
                # only; skip for dynamic bundle loading.
                continue
            elif tag == "script" and not src:
                # Inline scripts (native module names, etc.) — skip.
                continue
            elif src:
                data.append({"type": tag, "src": src})

        if use_esm:
            # ESM lazy bundle in debug=assets mode: return individual
            # specifiers for import() (unminified, no esbuild).
            assets_params = request.env["ir.asset"]._get_asset_params()
            asset_bundle = request.env["ir.qweb"]._get_asset_bundle(
                bundle_name, js=True, css=False, debug_assets=True,
                assets_params=assets_params,
            )
            native_data = asset_bundle.get_native_module_data()
            esm_specifiers = sorted(native_data["import_map"])
            _logger.debug(
                "[BUNDLE-TRACE] /web/bundle/%s: ESM debug mode → "
                "%d specifiers, %d files",
                bundle_name, len(esm_specifiers), len(data),
            )

        if esm_specifiers or inline_esm_code:
            response_data = {
                "is_esm": True,
                "specifiers": esm_specifiers,
                "files": data,
            }
            if inline_esm_code:
                # Inline ESM code for client-side Blob URL loading.
                response_data["inline_esm"] = inline_esm_code
            data = response_data

        return request.make_json_response(data)
