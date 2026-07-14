import logging
from typing import Any

import odoo.tools
from odoo import http
from odoo.http import Response, request
from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.modules import Manifest
from odoo.tools.assets.esm_registry import esm_registry
from odoo.tools.misc import file_path

from .utils import _local_web_translations

_logger = logging.getLogger(__name__)
_http_log = get_asset_logger("http")


class WebClient(http.Controller):
    @http.route("/web/webclient/bootstrap_translations", type="jsonrpc", auth="none")
    def bootstrap_translations(self, mods: list[str] | None = None) -> dict[str, Any]:
        """Load translations directly from *.po files, before a session exists.
        Used only for the login page and db management chrome, in the browser's
        language."""
        # Load a single translation for performance: sub-languages (only partially
        # translated) fall back to the main language PO, which suffices for the
        # login screen.
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
        Load the translations for the specified language and modules.

        :param hash: hash of the previously loaded translations; if it still
            matches the current hash, translations/modules are omitted from
            the response
        :param mods: the modules, a comma separated list
        :param lang: the language of the user
        :return: dict with ``lang`` and ``hash``, plus ``lang_parameters``,
            ``modules`` and ``multi_lang`` when the hash changed
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
                # ormcache miss: _get_web_translations_hash already computed
                # and stashed translation_data as a side effect.
                body.update(request.env.cr.cache.pop("translation_data"))
            else:
                # ormcache hit: translation_data was not stashed, so fetch
                # the translations directly.
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

        # Route type is declared "http" (not "jsonrpc"): the client fetches it
        # with a plain GET but still expects a JSON body.
        return request.make_json_response(
            body,
            [
                ("Cache-Control", f"public, max-age={http.STATIC_CACHE_LONG}"),
            ],
        )

    @http.route("/web/webclient/version_info", type="jsonrpc", auth="none")
    def version_info(self) -> dict[str, Any]:
        return odoo.service.common.exp_version()

    @http.route("/web/tests", type="http", auth="user", readonly=False)
    def unit_tests_suite(self, mod: str | None = None, **kwargs: Any) -> Response:
        return request.render(
            "web.unit_tests_suite",
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

        use_esm = bundle_name in esm_registry().dynamic_bundle_names
        log_event(
            _http_log,
            logging.DEBUG,
            "bundle_request",
            bundle=bundle_name,
            debug=bool(debug),
            is_esm=use_esm,
            params=sorted(bundle_params),
        )

        files = request.env["ir.qweb"]._get_asset_nodes(
            bundle_name, debug=debug, js=True, css=True
        )
        data = [
            {
                "type": tag,
                "src": attrs.get("src") or attrs.get("data-src") or attrs.get("href"),
            }
            for tag, attrs in files
            # Only stylesheet <link>s are loadable resources for the lazy-load
            # client. ``<link rel="modulepreload">`` hints (emitted per native
            # module when esbuild declines, e.g. on a read-only test cursor)
            # must not be forwarded: the client would inject them as
            # stylesheets, and the failing .js-as-CSS load rejects the whole
            # loadBundle() call. The ESM payload below already carries those
            # modules as import() specifiers.
            if tag != "link" or attrs.get("rel") == "stylesheet"
        ]

        if use_esm:
            # ESM dynamic bundle: return specifiers for import().  The
            # payload (import map incl. bridge entries for cross-bundle
            # legacy imports, template attachment URL) is computed once and
            # ormcached by ir.qweb — previously every runtime loadBundle()
            # re-ran bridge discovery and the XML template parse here.
            # Cached values are shared by reference: read-only below.
            payload = request.env["ir.qweb"]._get_esm_bundle_payload(
                bundle_name,
                debug_assets=bool(debug) and "assets" in debug,
            )
            specifiers = payload["specifiers"]
            import_map = payload["import_map"]
            tpl_url = payload["template_url"]

            data = {
                "is_esm": True,
                "specifiers": specifiers,
                "import_map": import_map,
                "files": data,
                "template_url": tpl_url,
            }
            # URL-vs-data-URI breakdown lets ops correlate a lazy
            # bundle response with any ``[asset.js] loadESMBundle``
            # logs on the browser side (which now emit fresh/dup/total
            # counts) without cross-referencing the full JSON payload.
            _n_data_uri = sum(1 for v in import_map.values() if v.startswith("data:"))
            _n_real_url = len(import_map) - _n_data_uri
            log_event(
                _http_log,
                logging.INFO,
                "served_esm",
                bundle=bundle_name,
                specs=len(specifiers),
                imports=len(import_map),
                url=_n_real_url,
                data=_n_data_uri,
                files=len(data["files"]),
                tpl=bool(tpl_url),
            )
        else:
            log_event(
                _http_log,
                logging.INFO,
                "served_legacy",
                bundle=bundle_name,
                files=len(data) if isinstance(data, list) else 0,
            )

        return request.make_json_response(data)
