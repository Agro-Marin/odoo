import contextlib
import json as json_mod
import logging
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from lxml import etree
from psycopg.errors import ReadOnlySqlTransaction
from rjsmin import jsmin as _rjsmin

from odoo import SUPERUSER_ID, api, models, tools
from odoo.http import request
from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.libs.constants import (
    ODOO_EXTERNAL_LIBS,
    SCRIPT_EXTENSIONS,
    STYLE_EXTENSIONS,
    TEMPLATE_EXTENSIONS,
)
from odoo.libs.hashing import cache_hash
from odoo.modules import module as _module
from odoo.tools.assets.esbuild import EsbuildCompiler, EsbuildResult
from odoo.tools.assets.esm_graph import (
    discover_transitive_import_specifiers,
    find_escaping_relative_imports,
)
from odoo.tools.assets.esm_registry import esm_registry
from odoo.tools.misc import file_path, str2bool

from odoo.addons.base.models.assetsbundle import AssetsBundle, BundleFileSpec

_logger = logging.getLogger(__name__)

AssetNode = tuple[str, dict[str, Any]]
EsmNodePair = tuple[list[AssetNode], list[AssetNode]]

_esm_log = get_asset_logger("esm")
_attach_log = get_asset_logger("attach")
_fallback_log = get_asset_logger("fallback")
_loader_log = get_asset_logger("loader")
_lock_log = get_asset_logger("lock")


class _EsmFallbackError(Exception):
    pass


class EsbuildBundleError(RuntimeError):
    """An esbuild build failed where the failure must not be degraded away.

    Serving an empty bundle is the right answer for a user — a degraded page
    beats a 500 — and the wrong one for whoever caused it: the page comes back
    ``200`` with no JavaScript, and the only trace is a WARNING. That has cost
    this fork two silent outages, each found by a person clicking rather than
    by anything failing.

    So the pipeline fails closed exactly where somebody is positioned to act on
    it (``--test-enable``, ``--dev=assets``) and keeps degrading in production.
    See ``IrQweb._esbuild_fail_closed``.
    """


class IrQweb(models.AbstractModel):
    _inherit = "ir.qweb"

    def _get_asset_nodes(
        self,
        bundle: str,
        css: bool = True,
        js: bool = True,
        debug: str = "",
        defer_load: bool = False,
        lazy_load: bool = False,
        media: str | None = None,
        autoprefix: bool = False,
    ) -> list[AssetNode]:
        media = (css and media) or None
        links = self._get_asset_links(
            bundle, css=css, js=js, debug=debug, autoprefix=autoprefix
        )

        pre_nodes = []
        post_nodes = []
        has_native = False
        if js:
            pre_nodes, post_nodes = self._get_native_module_nodes(
                bundle,
                debug=debug,
            )
            has_native = bool(pre_nodes) or bool(post_nodes)

        nodes = self._links_to_nodes(
            links,
            defer_load=defer_load,
            lazy_load=lazy_load,
            media=media,
        )

        log_event(
            _esm_log,
            logging.DEBUG,
            "nodes",
            bundle=bundle,
            debug=bool(debug),
            css=css,
            js=js,
            links=len(nodes),
            pre=len(pre_nodes),
            post=len(post_nodes),
            native=has_native,
        )
        if has_native:
            return pre_nodes + nodes + post_nodes

        return nodes

    @staticmethod
    def _is_debug_assets(debug) -> bool:
        return isinstance(debug, str) and "assets" in debug

    def _get_asset_links(
        self,
        bundle: str,
        css: bool = True,
        js: bool = True,
        debug: str | None = None,
        autoprefix: bool = False,
    ) -> list[str]:
        rtl = (
            self.env["res.lang"]
            .sudo()
            ._get_data(code=(self.env.lang or self.env.user.lang))
            .direction
            == "rtl"
        )
        assets_params = self.env["ir.asset"]._get_asset_params()
        debug_assets = self._is_debug_assets(debug)

        if debug_assets:
            return self._generate_asset_links(
                bundle,
                css=css,
                js=js,
                debug_assets=True,
                assets_params=assets_params,
                rtl=rtl,
                autoprefix=autoprefix,
            )
        else:
            return self._generate_asset_links_cache(
                bundle,
                css=css,
                js=js,
                assets_params=assets_params,
                rtl=rtl,
                autoprefix=autoprefix,
            )

    @tools.conditional(
        "xml" not in tools.config["dev_mode"],
        tools.ormcache(
            "bundle",
            "css",
            "js",
            "tuple(sorted(assets_params.items()))",
            "rtl",
            "autoprefix",
            cache="assets.links",
        ),
    )
    def _generate_asset_links_cache(
        self,
        bundle: str,
        css: bool = True,
        js: bool = True,
        assets_params: dict[str, Any] | None = None,
        rtl: bool = False,
        autoprefix: bool = False,
    ) -> list[str]:
        return self._generate_asset_links(
            bundle, css, js, False, assets_params, rtl, autoprefix=autoprefix
        )

    def _get_asset_content(
        self, bundle: str, assets_params: dict[str, Any] | None = None
    ) -> tuple[list[BundleFileSpec], list[str]]:
        if assets_params is None:
            assets_params = self.env["ir.asset"]._get_asset_params()
        asset_paths = self.env["ir.asset"]._get_asset_paths(
            bundle=bundle, assets_params=assets_params
        )
        files = []
        external_asset = []
        for asset in asset_paths:
            if asset.is_external:
                external_asset.append(asset.path)
            else:
                files.append(
                    {
                        "url": asset.path,
                        "filename": asset.full_path,
                        "content": "",
                        "last_modified": asset.last_modified,
                    }
                )
        return (files, external_asset)

    def _get_asset_bundle(
        self,
        bundle_name: str,
        css: bool = True,
        js: bool = True,
        debug_assets: bool = False,
        rtl: bool = False,
        assets_params: dict[str, Any] | None = None,
        autoprefix: bool = False,
    ) -> AssetsBundle:
        if assets_params is None:
            assets_params = self.env["ir.asset"]._get_asset_params()
        files, external_assets = self._get_asset_content(bundle_name, assets_params)
        return AssetsBundle(
            bundle_name,
            files,
            external_assets,
            env=self.env,
            css=css,
            js=js,
            debug_assets=debug_assets,
            rtl=rtl,
            assets_params=assets_params,
            autoprefix=autoprefix,
        )

    def _links_to_nodes(
        self,
        paths: list[str],
        defer_load: bool = False,
        lazy_load: bool = False,
        media: str | None = None,
    ) -> list[AssetNode]:
        nodes = []
        for path in paths:
            node = self._link_to_node(
                path, defer_load=defer_load, lazy_load=lazy_load, media=media
            )
            if node is None:
                _logger.warning(
                    "Asset path %r has no renderable node (unrecognized extension); skipped.",
                    path,
                )
                continue
            nodes.append(node)
        return nodes

    def _link_to_node(
        self,
        path: str,
        defer_load: bool = False,
        lazy_load: bool = False,
        media: str | None = None,
    ) -> AssetNode | None:
        ext = path.rsplit(".", maxsplit=1)[-1] if path else "js"
        is_js = ext in SCRIPT_EXTENSIONS
        is_xml = ext in TEMPLATE_EXTENSIONS
        is_css = ext in STYLE_EXTENSIONS

        if is_js:
            attributes = {
                "type": "text/javascript",
            }

            if defer_load:
                attributes["defer"] = "defer"
            if path:
                if lazy_load:
                    attributes["data-src"] = path
                else:
                    attributes["src"] = path

            return ("script", attributes)

        if is_css:
            attributes = {
                "type": "text/css",
                "rel": "stylesheet",
                "href": path,
                "media": media,
            }
            return ("link", attributes)

        if is_xml:
            attributes = {
                "type": "text/xml",
                "async": "async",
                "rel": "prefetch",
                "data-src": path,
            }
            return ("script", attributes)

        return None

    def _generate_asset_links(
        self,
        bundle: str,
        css: bool = True,
        js: bool = True,
        debug_assets: bool = False,
        assets_params: dict[str, Any] | None = None,
        rtl: bool = False,
        autoprefix: bool = False,
    ) -> list[str]:
        asset_bundle = self._get_asset_bundle(
            bundle,
            css=css,
            js=js,
            debug_assets=debug_assets,
            rtl=rtl,
            assets_params=assets_params,
            autoprefix=autoprefix,
        )
        return asset_bundle.get_links()

    _OWL_ESM_URL = "/web/static/lib/owl/owl.es.js"
    _ODOO_EXTERNAL_LIBS = ODOO_EXTERNAL_LIBS

    @staticmethod
    def _specifier_to_static_url(spec: str) -> str | None:
        if not spec.startswith("@"):
            return None
        rest = spec[1:]
        slash = rest.find("/")
        if slash <= 0:
            return None
        addon = rest[:slash]
        if addon == "odoo":
            return None
        path = rest[slash + 1 :]
        if path.startswith("../lib/"):
            url = f"/{addon}/static/lib/{path[len('../lib/') :]}"
        elif path.startswith("../tests/"):
            url = f"/{addon}/static/tests/{path[len('../tests/') :]}"
        else:
            url = f"/{addon}/static/src/{path}"
        if not url.endswith(".js"):
            url += ".js"
        return url

    @staticmethod
    def _import_map_url_breakdown(import_map: dict[str, str]) -> tuple[int, int, int]:
        n_bridges = sum(
            1 for v in import_map.values() if v.startswith("/web/assets/esm/bridges/")
        )
        n_data = sum(1 for v in import_map.values() if v.startswith("data:"))
        n_real = len(import_map) - n_bridges - n_data
        return n_real, n_bridges, n_data

    @staticmethod
    def _combine_bundle_with_templates(esbuild_code: str, esm_tpl: str) -> str:
        if not esm_tpl:
            return esbuild_code
        esb_base = esbuild_code
        sm_directive = ""
        tail_idx = esbuild_code.rfind("//# sourceMappingURL=")
        if tail_idx != -1 and "\n" not in esbuild_code[tail_idx:].rstrip("\n"):
            sm_directive = esbuild_code[tail_idx:].rstrip("\n")
            esb_base = esbuild_code[:tail_idx].rstrip("\n") + "\n"
        return (
            esb_base
            + "/* ── Inlined templates registration ── */\n"
            + esm_tpl
            + ("\n" + sm_directive + "\n" if sm_directive else "")
        )

    @tools.conditional(
        "xml" not in tools.config["dev_mode"],
        tools.ormcache(
            "bundle",
            "tuple(sorted(assets_params.items()))",
            cache="assets",
        ),
    )
    def _get_native_module_data_cached(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None = None,
    ) -> dict:
        asset_bundle = self._get_asset_bundle(
            bundle,
            js=True,
            css=False,
            debug_assets=False,
            assets_params=assets_params,
        )
        return asset_bundle.get_native_module_data()

    def _get_esm_bundle_payload(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None = None,
        debug_assets: bool = False,
    ) -> dict:
        if assets_params is None:
            assets_params = self.env["ir.asset"]._get_asset_params()
        if debug_assets:
            return self._esm_bundle_payload_impl(bundle, assets_params)
        return self._get_esm_bundle_payload_cached(bundle, assets_params)

    @tools.conditional(
        "xml" not in tools.config["dev_mode"],
        tools.ormcache(
            "bundle",
            "tuple(sorted(assets_params.items()))",
            cache="assets",
        ),
    )
    def _get_esm_bundle_payload_cached(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None = None,
    ) -> dict:
        return self._esm_bundle_payload_impl(bundle, assets_params)

    def _esm_bundle_payload_impl(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
    ) -> dict:
        asset_bundle = self._get_asset_bundle(
            bundle,
            js=True,
            css=False,
            debug_assets=True,
            assets_params=assets_params,
        )
        self._validate_lazy_bundle_relative_imports(asset_bundle)
        native_data = asset_bundle.get_native_module_data()
        import_map = dict(native_data["import_map"])
        import_map.update(native_data.get("bridge_import_map", {}))
        template_url = None
        esm_tpl = asset_bundle.generate_esm_template_bundle(use_import=False)
        if esm_tpl:
            template_url = self._save_esm_attachment(f"{bundle}.templates", esm_tpl)
        return {
            "specifiers": sorted(native_data["import_map"]),
            "import_map": import_map,
            "template_url": template_url,
        }

    def _validate_lazy_bundle_relative_imports(
        self,
        asset_bundle: AssetsBundle,
    ) -> None:
        """Reject a per-file-served bundle whose members relatively import
        files OUTSIDE the bundle.

        Such an import resolves against the member's static URL, so the
        browser fetches the target's RAW source instead of the parent-bridge
        shim the import map holds for it — bridge discovery never sees the raw
        copy's own bare imports, and the first one that lives only inside the
        parent's compiled bundle fails at runtime with a bare
        "Failed to resolve module specifier" (see
        :func:`find_escaping_relative_imports`).  Failing the payload build
        with the file, the import, and the fix beats letting the browser
        throw a TypeError that names neither.

        Raised unconditionally (not ``_esbuild_fail_closed``-gated): there is
        no degraded serve for this class — per-file delivery is already the
        only mode a lazy bundle has, and it is broken exactly as long as the
        import is.
        """
        escapes = find_escaping_relative_imports(asset_bundle.native_modules)
        if not escapes:
            return
        details = "; ".join(
            f"{module_path} imports {spec!r} (-> {resolved})"
            for module_path, spec, resolved in escapes
        )
        raise EsbuildBundleError(
            f"ESM bundle {asset_bundle.name!r} is served per-file but has "
            f"relative imports escaping the bundle: {details}. Use the bare "
            f"'@addon/...' specifier instead, so the import resolves through "
            f"the import map (parent-bridge shim) rather than fetching the "
            f"raw source."
        )

    _loader_shim_cache: tuple[float, str] | None = None

    _esbuild_cooldowns: dict[tuple[str, str], tuple[float, str, int]] = {}
    _ESBUILD_COOLDOWN_S: float = 60.0
    _ESBUILD_EXTENDED_COOLDOWN_S: float = 600.0

    _ESBUILD_SETTING_KEYS: frozenset = frozenset(
        {
            "cooldown_s",
            "extended_cooldown_s",
            "lock_retries",
            "lock_retry_sleep_s",
            "timeout_s",
            "target",
            "source_maps",
            "fail_closed",
        }
    )

    def _get_esbuild_setting(self, name: str, default, cast=None):
        if name not in self._ESBUILD_SETTING_KEYS:
            raise ValueError(
                f"Unknown esbuild setting {name!r}; "
                f"expected one of {sorted(self._ESBUILD_SETTING_KEYS)}",
            )
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                f"web.esbuild.{name}",
            )
        )
        if not raw:
            return default
        if cast is None:
            return raw
        try:
            return cast(raw)
        except (TypeError, ValueError) as exc:
            log_event(
                _fallback_log,
                logging.DEBUG,
                "setting_cast_failed",
                name=name,
                raw=str(raw)[:50],
                err=type(exc).__name__,
            )
            return default

    def _esbuild_fail_closed(self) -> bool:
        """Whether a failed esbuild build must raise instead of degrading.

        Degrading is correct for a user and wrong for a developer, so the two
        cases are split by who is watching rather than by how bad the failure
        is: under ``--test-enable`` or ``--dev=assets`` somebody is positioned
        to fix it now, and an empty bundle there reads as unrelated test
        failures somewhere else entirely (a missing service, absent
        translations) which is how the cause stays hidden. Production keeps
        serving the degraded page.

        ``web.esbuild.fail_closed`` overrides in either direction — set it to
        ``0`` to get the old behaviour back in a test run that has to survive a
        broken bundle, or to ``1`` to make a staging server strict.
        """
        override = self._get_esbuild_setting("fail_closed", default=None)
        if override is not None:
            return str(override).strip().lower() not in ("0", "false", "")
        return bool(tools.config["test_enable"] or "assets" in tools.config["dev_mode"])

    def _esbuild_forced_fallback_bundles(self) -> set[str]:
        forced_raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("web.esbuild.force_fallback_bundles", "")
        )
        return {s.strip() for s in forced_raw.split(",") if s.strip()}

    def _esbuild_cooldown_key(self, bundle: str) -> tuple[str, str]:
        return (self.env.cr.dbname, bundle)

    def _esbuild_circuit_state(self, bundle: str) -> tuple[bool, str]:
        key = self._esbuild_cooldown_key(bundle)
        entry = type(self)._esbuild_cooldowns.get(key)
        if not entry:
            return True, ""
        expiry, reason, _fails = entry
        if time.monotonic() < expiry:
            return False, reason
        type(self)._esbuild_cooldowns[key] = (0.0, reason, _fails)
        return True, ""

    def _esbuild_circuit_record_failure(self, bundle: str, reason: str) -> None:
        key = self._esbuild_cooldown_key(bundle)
        prev = type(self)._esbuild_cooldowns.get(key)
        fails = (prev[2] + 1) if prev else 1
        if fails >= 2:
            cooldown = self._get_esbuild_setting(
                "extended_cooldown_s",
                default=self._ESBUILD_EXTENDED_COOLDOWN_S,
                cast=float,
            )
        else:
            cooldown = self._get_esbuild_setting(
                "cooldown_s",
                default=self._ESBUILD_COOLDOWN_S,
                cast=float,
            )
        type(self)._esbuild_cooldowns[key] = (
            time.monotonic() + cooldown,
            reason,
            fails,
        )
        log_event(
            _fallback_log,
            logging.WARNING,
            "circuit_open",
            bundle=bundle,
            reason=reason,
            cooldown_s=cooldown,
            fails=fails,
        )

    def _esbuild_circuit_record_success(self, bundle: str) -> None:
        cooldowns = type(self)._esbuild_cooldowns
        key = self._esbuild_cooldown_key(bundle)
        if key in cooldowns:
            cooldowns.pop(key, None)
            log_event(
                _fallback_log,
                logging.INFO,
                "circuit_close",
                bundle=bundle,
            )

    _ESBUILD_LOCK_RETRIES: int = 1
    _ESBUILD_LOCK_RETRY_SLEEP_S: float = 0.2

    @contextlib.contextmanager
    def _esbuild_lock_cursor(self, bundle: str):
        if not self.env.cr.readonly:
            yield self.env.cr
            return
        if _module.current_test:
            yield None
            return
        try:
            rw_cr = self.env.registry.cursor(readonly=False)
        except Exception:
            log_event(
                _lock_log,
                logging.WARNING,
                "rw_cursor_unavailable",
                bundle=bundle,
            )
            yield None
            return
        try:
            yield rw_cr
        finally:
            rw_cr.rollback()
            rw_cr.close()

    def _esbuild_try_acquire_lock(self, bundle: str, cr=None) -> bool:
        if cr is None:
            cr = self.env.cr
        retries = self._get_esbuild_setting(
            "lock_retries",
            default=self._ESBUILD_LOCK_RETRIES,
            cast=int,
        )
        sleep_s = self._get_esbuild_setting(
            "lock_retry_sleep_s",
            default=self._ESBUILD_LOCK_RETRY_SLEEP_S,
            cast=float,
        )
        key = f"esbuild:{bundle}"
        for attempt in range(retries + 1):
            cr.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                (key,),
            )
            got = cr.fetchone()[0]
            if got:
                log_event(
                    _lock_log,
                    logging.DEBUG,
                    "acquired",
                    bundle=bundle,
                    attempt=attempt,
                )
                return True
            if attempt < retries:
                time.sleep(sleep_s)
        log_event(
            _lock_log,
            logging.INFO,
            "contention",
            bundle=bundle,
            attempts=retries + 1,
        )
        return False

    @staticmethod
    def _is_hoot_test_specifier(specifier: str, *, by_directory: bool = True) -> bool:
        if "/tours/" in specifier:
            return False
        if ".test" in specifier or ".hoot" in specifier:
            return True
        return by_directory and ("/../tests/" in specifier or "/tests/" in specifier)

    @classmethod
    def _hoot_specifiers(cls, bundle: str, specifiers: Iterable[str]) -> list[str]:
        """The specifiers of *bundle* that Hoot loads itself.

        Hoot-ness is a property of the BUNDLE, not of a path. The runner's
        bundles and the tour bundle are disjoint — ``web.assets_unit_tests``
        holds 1088 ``*.test.js`` suites, ``web.assets_tests`` holds none, only
        tours and the odd integration helper — so reading ``"/tests/" in
        specifier`` as "Hoot owns this" misclassified every file of the tour
        bundle that does not sit under a ``tours/`` directory. Those were then
        left out of the eager import, silently: ``test_css_error.js``,
        ``auth_passkey``'s tours and a dozen more never registered, and the
        runner could only report the ready code as "always falsy".

        So the directory reading applies only where it is true — a bundle that
        the Hoot runner loads through an import map. Elsewhere a suite is still
        recognised by name, which keeps a self-contained runner bundle
        (``im_livechat.embed_assets_unit_tests``) lazy without declaring the
        relationship.
        """
        registry = esm_registry()
        by_directory = (
            bundle in registry.import_map_includes
            or bundle in registry.import_map_included_bundles
        )
        return [
            spec
            for spec in specifiers
            if cls._is_hoot_test_specifier(spec, by_directory=by_directory)
        ]

    @classmethod
    def _build_loader_shim_js(cls) -> str:
        src_path = Path(file_path("web/static/src/module_loader.js"))
        mtime = src_path.stat().st_mtime
        cached = cls._loader_shim_cache
        if cached and cached[0] == mtime:
            return cached[1]
        source = src_path.read_text(encoding="utf-8")
        minified = _rjsmin(source)
        cls._loader_shim_cache = (mtime, minified)
        log_event(
            _loader_log,
            logging.DEBUG,
            "shim_compiled",
            source_bytes=len(source),
            minified_bytes=len(minified),
        )
        return minified

    @tools.conditional(
        "xml" not in tools.config["dev_mode"],
        tools.ormcache(
            "bundle",
            "tuple(sorted(assets_params.items()))",
            cache="assets",
        ),
    )
    def _get_native_module_nodes_cached(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None = None,
    ) -> EsmNodePair:
        return self._get_native_module_nodes_impl(
            bundle,
            debug=False,
            assets_params=assets_params,
            _raise_on_decline=True,
        )

    def _get_native_module_nodes(
        self,
        bundle: str,
        debug: str = "",
        assets_params: dict[str, Any] | None = None,
    ) -> EsmNodePair:
        debug_assets = self._is_debug_assets(debug)
        if assets_params is None:
            assets_params = self.env["ir.asset"]._get_asset_params()
        if not debug_assets and bundle not in self._esbuild_forced_fallback_bundles():
            try:
                pre, post = self._get_native_module_nodes_cached(
                    bundle, assets_params=assets_params
                )
            except _EsmFallbackError:
                pre, post = self._get_native_module_nodes_impl(
                    bundle, debug=debug, assets_params=assets_params
                )
        else:
            pre, post = self._get_native_module_nodes_impl(
                bundle, debug=debug, assets_params=assets_params
            )
        return self._dedup_request_import_map(bundle, pre), post

    def _dedup_request_import_map(
        self,
        bundle: str,
        pre_nodes: list[AssetNode],
    ) -> list[AssetNode]:
        if not request:
            return pre_nodes

        def _is_import_map(node: AssetNode) -> bool:
            return node[0] == "script" and node[1].get("type") == "importmap"

        if not any(_is_import_map(node) for node in pre_nodes):
            return pre_nodes
        if not getattr(request, "_esm_import_map_rendered", False):
            request._esm_import_map_rendered = True
            return pre_nodes
        log_event(
            _esm_log,
            logging.DEBUG,
            "importmap_skipped",
            bundle=bundle,
            reason="already_rendered",
        )
        return [node for node in pre_nodes if not _is_import_map(node)]

    def _get_native_module_nodes_impl(
        self,
        bundle: str,
        debug: str = "",
        assets_params: dict[str, Any] | None = None,
        _raise_on_decline: bool = False,
    ) -> EsmNodePair:
        debug_assets = self._is_debug_assets(debug)
        if assets_params is None:
            assets_params = self.env["ir.asset"]._get_asset_params()

        if debug_assets:
            asset_bundle = self._get_asset_bundle(
                bundle,
                js=True,
                css=False,
                debug_assets=True,
                assets_params=assets_params,
            )
            native_data = asset_bundle.get_native_module_data()
        else:
            native_data = self._get_native_module_data_cached(
                bundle,
                assets_params=assets_params,
            )

        if not native_data["import_map"]:
            log_event(
                _esm_log,
                logging.DEBUG,
                "no_native_modules",
                bundle=bundle,
            )
            return [], []

        if not debug_assets:
            asset_bundle = self._get_asset_bundle(
                bundle,
                js=True,
                css=False,
                debug_assets=False,
                assets_params=assets_params,
            )
            esbuild_result, child_bundles = self._esm_run_esbuild(
                bundle, asset_bundle, assets_params
            )
            if esbuild_result.code:
                return self._esm_prod_nodes(
                    bundle,
                    asset_bundle,
                    esbuild_result,
                    assets_params,
                    child_bundles,
                    raise_on_decline=_raise_on_decline,
                )
            if _raise_on_decline:
                raise _EsmFallbackError
        return self._esm_debug_nodes(
            bundle, asset_bundle, native_data, debug_assets, assets_params
        )

    def _esm_run_esbuild(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        assets_params: dict[str, Any] | None,
    ) -> tuple[EsbuildResult, list[AssetsBundle]]:
        forced_bundles = self._esbuild_forced_fallback_bundles()

        allow, circuit_reason = self._esbuild_circuit_state(bundle)
        esbuild_result = EsbuildResult("", None, None)
        child_bundles: list[AssetsBundle] = []
        if bundle in forced_bundles:
            log_event(
                _fallback_log,
                logging.INFO,
                "admin_override",
                bundle=bundle,
            )
        elif not allow:
            log_event(
                _fallback_log,
                logging.DEBUG,
                "circuit_blocked",
                bundle=bundle,
                reason=circuit_reason,
            )
        else:
            with self._esbuild_lock_cursor(bundle) as lock_cr:
                if lock_cr is None:
                    log_event(
                        _fallback_log,
                        logging.INFO,
                        "lock_unavailable",
                        bundle=bundle,
                    )
                elif not self._esbuild_try_acquire_lock(bundle, cr=lock_cr):
                    log_event(
                        _fallback_log,
                        logging.INFO,
                        "lock_contention",
                        bundle=bundle,
                    )
                else:
                    child_bundles = self._get_dynamic_child_bundles(
                        bundle, assets_params, debug_assets=False
                    )
                    _parent_specs = {a.module_path for a in asset_bundle.native_modules}
                    _child_specs = {
                        asset.module_path
                        for child_ab in child_bundles
                        for asset in child_ab.native_modules
                    } - _parent_specs
                    secondary_stubs = self._secondary_parent_stubs(
                        bundle, assets_params
                    )
                    dynamic_child_specs = None
                    if _child_specs:
                        aliasable = {
                            s
                            for s in _child_specs
                            if "/../" not in s and not s.startswith("../")
                        }
                        if aliasable:
                            child_stubs = asset_bundle._bridges.build_shim_sources(
                                aliasable
                            )
                            secondary_stubs = {**child_stubs, **secondary_stubs}
                        dynamic_child_specs = (
                            frozenset(_child_specs - aliasable) or None
                        )
                    try:
                        esbuild_result = asset_bundle.esbuild_native_bundle(
                            timeout_s=self._get_esbuild_setting(
                                "timeout_s",
                                default=EsbuildCompiler._ESBUILD_TIMEOUT_S,
                                cast=int,
                            ),
                            target=self._get_esbuild_setting(
                                "target",
                                default=EsbuildCompiler._ESBUILD_TARGET,
                            ),
                            source_maps=self._get_esbuild_setting(
                                "source_maps",
                                default=EsbuildCompiler._ESBUILD_SOURCE_MAPS,
                            ),
                            dynamic_child_specs=dynamic_child_specs,
                            secondary_parent_stubs=secondary_stubs or None,
                        )
                        self._esbuild_circuit_record_success(bundle)
                    except Exception as e:
                        log_event(
                            _fallback_log,
                            logging.WARNING,
                            "esbuild_exception",
                            bundle=bundle,
                            err=type(e).__name__,
                            msg=str(e)[:200],
                        )
                        if self._esbuild_fail_closed():
                            # Deliberately without recording a circuit failure:
                            # the breaker would open and every later render
                            # would take the `circuit_blocked` branch above and
                            # degrade silently again, so only the first build
                            # of the run would be honest.
                            raise EsbuildBundleError(
                                f"esbuild failed for bundle {bundle!r}: {e}"
                            ) from e
                        self._esbuild_circuit_record_failure(
                            bundle,
                            reason=type(e).__name__,
                        )
                        esbuild_result = EsbuildResult("", None, None)
        return esbuild_result, child_bundles

    def _get_dynamic_parent_bundles(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
    ) -> tuple[str, ...]:
        contributors = dict.fromkeys((bundle,))
        for asset in self.env["ir.asset"]._get_asset_paths(
            bundle=bundle,
            assets_params=assets_params or self.env["ir.asset"]._get_asset_params(),
        ):
            contributors.setdefault(asset.bundle)
        return tuple(contributors)

    def _get_dynamic_child_bundles(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
        *,
        debug_assets: bool,
    ) -> list[AssetsBundle]:
        registry = esm_registry()
        child_names = dict.fromkeys(
            child_name
            for parent_name in self._get_dynamic_parent_bundles(bundle, assets_params)
            for child_name in registry.dynamic_children.get(parent_name, ())
        )
        return [
            self._get_asset_bundle(
                child_name,
                js=True,
                css=False,
                debug_assets=debug_assets
                or child_name in registry.dynamic_bundle_names,
                assets_params=assets_params,
            )
            for child_name in child_names
        ]

    @staticmethod
    def _merge_child_import_maps(
        import_map: dict[str, str],
        child_bundles: list[AssetsBundle],
    ) -> list[AssetsBundle]:
        dynamic_names = esm_registry().dynamic_bundle_names
        dynamic_bundles = []
        for child_ab in child_bundles:
            child_data = child_ab.get_native_module_data(with_bridges=False)
            import_map.update(child_data["import_map"])
            if child_ab.name in dynamic_names:
                dynamic_bundles.append(child_ab)
        return dynamic_bundles

    def _merge_include_import_maps(
        self,
        bundle: str,
        import_map: dict[str, str],
        assets_params: dict[str, Any] | None,
        *,
        debug_assets: bool,
        resolve_bridges: bool,
    ) -> tuple[str, ...]:
        include_names = tuple(esm_registry().import_map_includes.get(bundle, ()))
        for include_name in include_names:
            if not resolve_bridges:
                include_data = self._get_native_module_data_cached(
                    include_name,
                    assets_params=assets_params,
                )
                import_map.update(include_data["import_map"])
                for spec, shim_url in include_data.get("bridge_import_map", {}).items():
                    import_map.setdefault(spec, shim_url)
                continue
            include_ab = self._get_asset_bundle(
                include_name,
                js=True,
                css=False,
                debug_assets=debug_assets,
                assets_params=assets_params,
            )
            include_data = include_ab.get_native_module_data(with_bridges=False)
            import_map.update(include_data["import_map"])
            discovered, _ext_seen = include_ab._bridges._discover_bridge_specifiers(
                set(include_data["import_map"]),
                set(self._ODOO_EXTERNAL_LIBS),
            )
            self._resolve_bridge_specifiers_to_urls(
                import_map,
                discovered,
                drop_unresolved=True,
                bundle=include_name,
            )
        return include_names

    def _secondary_shared_specs(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
    ) -> frozenset[str]:
        parents = esm_registry().secondary_parents.get(bundle)
        if not parents:
            return frozenset()
        parent_spec_sets = []
        for parent in parents:
            parent_ab = self._get_asset_bundle(
                parent,
                js=True,
                css=False,
                debug_assets=False,
                assets_params=assets_params,
            )
            specs = set(
                parent_ab.get_native_module_data(with_bridges=False)["import_map"]
            )
            if specs:
                parent_spec_sets.append(specs)
        if not parent_spec_sets:
            return frozenset()
        shared = set.intersection(*parent_spec_sets)
        sec_ab = self._get_asset_bundle(
            bundle,
            js=True,
            css=False,
            debug_assets=False,
            assets_params=assets_params,
        )
        own_specs = set(sec_ab.get_native_module_data(with_bridges=False)["import_map"])
        discovered, _ext = sec_ab._bridges._discover_bridge_specifiers(
            own_specs,
            set(self._ODOO_EXTERNAL_LIBS),
        )
        return frozenset(set(discovered) & shared)

    def _secondary_parent_stubs(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
    ) -> dict[str, str]:
        shared = self._secondary_shared_specs(bundle, assets_params)
        if not shared:
            return {}
        sec_ab = self._get_asset_bundle(
            bundle,
            js=True,
            css=False,
            debug_assets=False,
            assets_params=assets_params,
        )
        return sec_ab._bridges.build_shim_sources(set(shared))

    def _merge_secondary_import_maps(
        self,
        bundle: str,
        import_map: dict[str, str],
        assets_params: dict[str, Any] | None,
        *,
        debug_assets: bool,
    ) -> None:
        for sec_name in esm_registry().secondary_import_map_includes.get(bundle, ()):
            sec_ab = self._get_asset_bundle(
                sec_name,
                js=True,
                css=False,
                debug_assets=debug_assets,
                assets_params=assets_params,
            )
            sec_data = sec_ab.get_native_module_data(with_bridges=False)
            for spec, url in sec_data["import_map"].items():
                import_map.setdefault(spec, url)

    def _resolve_bridge_specifiers_to_urls(
        self,
        import_map: dict[str, str],
        discovered: Iterable[str],
        *,
        drop_unresolved: bool,
        bundle: str = "",
    ) -> dict[str, str]:
        resolved_map = {}
        for spec in discovered:
            current = import_map.get(spec)
            if current and not current.startswith(
                ("/web/assets/esm/bridges/", "data:")
            ):
                continue
            resolved = self._ODOO_EXTERNAL_LIBS.get(
                spec
            ) or self._specifier_to_static_url(spec)
            if resolved:
                import_map[spec] = resolved
                resolved_map[spec] = resolved
            elif current and drop_unresolved:
                del import_map[spec]
        if resolved_map:
            extra = discover_transitive_import_specifiers(
                resolved_map,
                known_specifiers=set(import_map),
                ext_libs=self._ODOO_EXTERNAL_LIBS,
                lib_candidates=EsbuildCompiler._LIB_CANDIDATES,
                bundle_name=bundle,
            )
            for spec in sorted(extra):
                resolved = self._ODOO_EXTERNAL_LIBS.get(
                    spec
                ) or self._specifier_to_static_url(spec)
                if resolved:
                    import_map[spec] = resolved
                    resolved_map[spec] = resolved
        return resolved_map

    def _esm_prod_nodes(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        esbuild_result: EsbuildResult,
        assets_params: dict[str, Any] | None,
        child_bundles: list[AssetsBundle] | None = None,
        *,
        raise_on_decline: bool = False,
    ) -> EsmNodePair:
        esbuild_code = esbuild_result.code
        pre = []
        post = []
        prod_import_map = dict(self._ODOO_EXTERNAL_LIBS)

        if child_bundles is None:
            child_bundles = self._get_dynamic_child_bundles(
                bundle, assets_params, debug_assets=False
            )
        dynamic_bundles = self._merge_child_import_maps(prod_import_map, child_bundles)

        if dynamic_bundles:
            combined_modules = []
            for dyn_ab in dynamic_bundles:
                combined_modules.extend(dyn_ab.native_modules)
            bridge_map = dynamic_bundles[0]._bridges._build_native_to_legacy_bridge(
                set(prod_import_map),
                modules=combined_modules,
            )
            prod_import_map.update(bridge_map)

        include_names = self._merge_include_import_maps(
            bundle,
            prod_import_map,
            assets_params,
            debug_assets=False,
            resolve_bridges=False,
        )

        self._merge_secondary_import_maps(
            bundle,
            prod_import_map,
            assets_params,
            debug_assets=False,
        )

        if include_names:
            self_bridges = asset_bundle._bridges._build_parent_self_bridge()
            prod_import_map.update(self_bridges)
            for asset in asset_bundle.native_modules:
                header = asset.parsed_header
                if not (header and header["alias"]):
                    continue
                alias = header["alias"]
                current = prod_import_map.get(alias, "")
                if current.startswith("/web/assets/esm/bridges/"):
                    continue
                shim = self_bridges.get(asset.module_path)
                if shim:
                    prod_import_map[alias] = shim

        pre.append(
            (
                "script",
                {
                    "type": "importmap",
                    "data-bundle": bundle,
                    "text": json_mod.dumps(
                        {"imports": prod_import_map},
                    ),
                },
            )
        )
        shim_js = self._build_loader_shim_js()
        pre.append(("script", {"text": shim_js}))
        esm_tpl = asset_bundle.generate_esm_template_bundle(
            use_import=False,
        )
        bundle_code = self._combine_bundle_with_templates(esbuild_code, esm_tpl)
        esm_url = None
        try:
            esm_url = self._save_esm_attachment(
                bundle,
                bundle_code,
                metafile=esbuild_result.metafile,
                sourcemap=esbuild_result.sourcemap,
            )
        except ReadOnlySqlTransaction:
            log_event(
                _attach_log,
                logging.WARNING,
                "save_failed_inline",
                bundle=bundle,
                readonly=bool(self.env.cr.readonly),
                declined=raise_on_decline,
            )
            if raise_on_decline:
                raise _EsmFallbackError from None
        if esm_url:
            post.append(
                (
                    "script",
                    {
                        "type": "module",
                        "src": esm_url,
                        "data-bridge": bundle,
                    },
                )
            )
        else:
            post.append(
                (
                    "script",
                    {
                        "type": "module",
                        "text": bundle_code,
                        "data-bridge": bundle,
                    },
                )
            )
        _has_satellites = bool(
            esm_registry().import_map_includes.get(bundle),
        )
        if esm_tpl and _has_satellites:
            tpl_url = None
            try:
                tpl_url = self._save_esm_attachment(
                    f"{bundle}.templates",
                    esm_tpl,
                )
            except ReadOnlySqlTransaction:
                log_event(
                    _attach_log,
                    logging.WARNING,
                    "save_failed_inline",
                    bundle=f"{bundle}.templates",
                    readonly=bool(self.env.cr.readonly),
                    declined=raise_on_decline,
                )
                if raise_on_decline:
                    raise _EsmFallbackError from None
            if tpl_url:
                post.append(
                    (
                        "script",
                        {
                            "type": "module",
                            "src": tpl_url,
                            "data-templates": bundle,
                        },
                    )
                )
            else:
                post.append(
                    (
                        "script",
                        {
                            "type": "module",
                            "text": esm_tpl,
                            "data-templates": bundle,
                        },
                    )
                )
        _n_real_url, _n_bridges, _n_data_uri = self._import_map_url_breakdown(
            prod_import_map
        )
        log_event(
            _esm_log,
            logging.DEBUG,
            "render",
            bundle=bundle,
            branch="prod",
            pre=len(pre),
            post=len(post),
            importmap=len(prod_import_map),
            url=_n_real_url,
            bridges=_n_bridges,
            data=_n_data_uri,
            dyn=len(dynamic_bundles),
            includes=len(include_names) if include_names else 0,
        )
        return pre, post

    def _esm_debug_nodes(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        native_data: dict[str, Any],
        debug_assets: bool,
        assets_params: dict[str, Any] | None,
    ) -> EsmNodePair:
        pre_nodes = []
        post_nodes = []
        import_map = dict(native_data["import_map"])

        import_map.update(self._ODOO_EXTERNAL_LIBS)

        lazy_bundles = self._get_dynamic_child_bundles(
            bundle, assets_params, debug_assets=True
        )
        self._merge_child_import_maps(import_map, lazy_bundles)

        self._merge_include_import_maps(
            bundle,
            import_map,
            assets_params,
            debug_assets=debug_assets,
            resolve_bridges=True,
        )

        self._merge_secondary_import_maps(
            bundle,
            import_map,
            assets_params,
            debug_assets=debug_assets,
        )

        all_native_specifiers = set(native_data["import_map"])
        combined_native_modules = list(asset_bundle.native_modules)
        for lazy_ab in lazy_bundles:
            all_native_specifiers.update(m.module_path for m in lazy_ab.native_modules)
            combined_native_modules.extend(lazy_ab.native_modules)

        discovered, _ext_seen = asset_bundle._bridges._discover_bridge_specifiers(
            all_native_specifiers,
            set(self._ODOO_EXTERNAL_LIBS),
            modules=combined_native_modules,
        )
        resolved_bridges = self._resolve_bridge_specifiers_to_urls(
            import_map,
            discovered,
            drop_unresolved=False,
            bundle=bundle,
        )

        _req = request or None
        _already_has_esm = _req and getattr(
            _req,
            "_esm_import_map_rendered",
            False,
        )

        if not _already_has_esm:
            pre_nodes.append(
                (
                    "script",
                    {
                        "type": "importmap",
                        "data-bundle": bundle,
                        "text": json_mod.dumps({"imports": import_map}, indent=2),
                    },
                )
            )

        if not debug_assets:
            hoot_owned = set(self._hoot_specifiers(bundle, native_data["import_map"]))
            reachable_without_hoot = {
                url
                for spec, url in native_data["import_map"].items()
                if spec not in hoot_owned
            }
            pre_nodes.extend(
                ("link", {"rel": "modulepreload", "href": url})
                for url in native_data["preload_urls"]
                if url in reachable_without_hoot
            )

        bridge_specifiers = sorted(
            set(native_data["import_map"]) | set(self._ODOO_EXTERNAL_LIBS)
        )
        if bridge_specifiers and not _already_has_esm:
            shim_js = self._build_loader_shim_js()
            pre_nodes.append(("script", {"text": shim_js}))

        if bridge_specifiers:
            bridge_code = ""

            hoot_specs = self._hoot_specifiers(bundle, bridge_specifiers)
            non_hoot_specs = [s for s in bridge_specifiers if s not in set(hoot_specs)]

            if not _already_has_esm:
                import_lines = []
                register_entries = []
                for i, specifier in enumerate(non_hoot_specs):
                    var = f"__m{i}"
                    import_lines.append(
                        f"import * as {var} from {json_mod.dumps(specifier)};"
                    )
                    register_entries.append(f"  {json_mod.dumps(specifier)}: {var}")
                bridge_code = "\n".join(import_lines) + "\n"
                bridge_code += "odoo.loader.registerNativeModules({\n"
                bridge_code += ",\n".join(register_entries)
                bridge_code += "\n});\n"
            elif bundle in esm_registry().import_map_included_bundles:
                if non_hoot_specs:
                    imports = ", ".join(
                        f"import({json_mod.dumps(s)})" for s in non_hoot_specs
                    )
                    bridge_code += f"await Promise.allSettled([{imports}]);\n"
            elif bundle in esm_registry().secondary_bundle_names:
                # Every module, not the ones whose PATH looks like a tour. A
                # secondary bundle is on the page to run: its modules register
                # themselves by side effect, and nothing about a specifier says
                # whether it does. Selecting on ``"/tours/" in s`` evaluated
                # ``website/static/tests/tours/...`` and silently skipped
                # ``test_assetsbundle/static/tests/test_css_error.js``, a tour
                # sitting directly in ``static/tests`` -- so its tour was
                # missing from the registry on frontend pages only, and the
                # runner could only report the ready code as "always falsy".
                #
                # The page's OTHER parent already loads this same bundle whole
                # (it links the artifact rather than importing by specifier),
                # so this is also what makes the two agree.
                #
                # ``allSettled`` for the same reason as the branch above: one
                # module that throws on this page must not stop the rest from
                # registering.
                if non_hoot_specs:
                    imports = ", ".join(
                        f"import({json_mod.dumps(s)})" for s in non_hoot_specs
                    )
                    bridge_code += f"await Promise.allSettled([{imports}]);\n"
            else:
                own_specs = [
                    s for s in non_hoot_specs if s in native_data["import_map"]
                ]
                if own_specs:
                    import_lines = []
                    register_entries = []
                    for i, specifier in enumerate(own_specs):
                        var = f"__s{i}"
                        url = native_data["import_map"][specifier]
                        import_lines.append(
                            f"import * as {var} from {json_mod.dumps(url)};"
                        )
                        register_entries.append(f"  {json_mod.dumps(specifier)}: {var}")
                    bridge_code += "\n".join(import_lines) + "\n"
                    bridge_code += "odoo.loader.registerNativeModules({\n"
                    bridge_code += ",\n".join(register_entries)
                    bridge_code += "\n});\n"

            start_hoot = [s for s in hoot_specs if s.endswith("/start.hoot")]
            other_tests = [s for s in hoot_specs if s not in start_hoot]
            if start_hoot and other_tests:
                specifier_list = ",\n".join(
                    f"  {json_mod.dumps(s)}" for s in other_tests
                )
                bridge_code += (
                    f"const {{loadAndStart}} = await import({json_mod.dumps(start_hoot[0])});\n"
                    f"loadAndStart([\n{specifier_list}\n]);\n"
                )

            if bridge_code.strip():
                post_nodes.append(
                    (
                        "script",
                        {
                            "type": "module",
                            "data-bridge": bundle,
                            "text": bridge_code,
                        },
                    )
                )

        esm_tpl = asset_bundle.generate_esm_template_bundle(
            use_import=True,
        )
        if esm_tpl:
            post_nodes.append(
                (
                    "script",
                    {
                        "type": "module",
                        "data-templates": bundle,
                        "text": esm_tpl,
                    },
                )
            )

        _n_real_url, _n_bridges, _n_data_uri = self._import_map_url_breakdown(
            import_map
        )
        log_event(
            _esm_log,
            logging.DEBUG,
            "render",
            bundle=bundle,
            branch="debug",
            pre=len(pre_nodes),
            post=len(post_nodes),
            importmap=len(import_map),
            url=_n_real_url,
            bridges=_n_bridges,
            data=_n_data_uri,
            bridge_shims=len(resolved_bridges),
            already_has_esm=bool(_already_has_esm),
        )
        return pre_nodes, post_nodes

    def _save_esm_attachment(
        self,
        bundle: str,
        content: str,
        metafile: str | None = None,
        sourcemap: str | None = None,
    ) -> str:
        IrAttachment = self.env["ir.attachment"]
        content_bytes = content.encode("utf-8")
        content_hash = cache_hash(content_bytes)[:16]
        url = f"/web/assets/esm/{content_hash}/{bundle}.esm.js"

        existing = IrAttachment.sudo().search(
            [("url", "=", url), ("public", "=", True)],
            limit=1,
        )
        if existing:
            log_event(
                _attach_log,
                logging.DEBUG,
                "reuse",
                bundle=bundle,
                url=url,
                bytes=len(content_bytes),
            )
            self._persist_esm_attachment_rows(
                [],
                touch_ids=existing.ids,
                bundle=bundle,
            )
            return url

        self._persist_esm_attachment_rows(
            [
                {
                    "name": f"{bundle}.esm.js",
                    "mimetype": "text/javascript",
                    "res_model": "ir.ui.view",
                    "res_id": False,
                    "type": "binary",
                    "public": True,
                    "raw": content_bytes,
                    "url": url,
                }
            ],
            bundle=bundle,
        )
        stale_count = IrAttachment.sudo().search_count(
            [
                "|",
                "|",
                "|",
                "|",
                "|",
                ("url", "=like", f"/web/assets/esm/%/{bundle}.esm.js"),
                ("url", "=like", f"/web/assets/%/{bundle}.esm.js"),
                ("url", "=like", f"/web/assets/esm/%/{bundle}.esm.js.map"),
                ("url", "=like", f"/web/assets/esm/%/{bundle}.meta.json"),
                ("url", "=like", f"/web/assets/%/{bundle}.esm.js.map"),
                ("url", "=like", f"/web/assets/%/{bundle}.meta.json"),
                ("url", "!=", url),
                ("public", "=", True),
            ]
        )
        if stale_count:
            log_event(
                _attach_log,
                logging.INFO,
                "stale_deferred",
                bundle=bundle,
                count=stale_count,
            )
        log_event(
            _attach_log,
            logging.INFO,
            "save",
            bundle=bundle,
            url=url,
            bytes=len(content_bytes),
        )

        if metafile and url.endswith(".esm.js"):
            meta_url = url[: -len(".esm.js")] + ".meta.json"
            self._save_esm_sidecar(
                bundle,
                meta_url,
                metafile.encode("utf-8"),
                mimetype="application/json",
            )
        if sourcemap and url.endswith(".esm.js"):
            sm_url = url + ".map"
            self._save_esm_sidecar(
                bundle,
                sm_url,
                sourcemap.encode("utf-8"),
                mimetype="application/json",
            )
        return url

    def _save_esm_sidecar(
        self,
        bundle: str,
        url: str,
        content: bytes,
        mimetype: str,
    ) -> None:
        IrAttachment = self.env["ir.attachment"]
        existing = IrAttachment.sudo().search(
            [
                ("url", "=", url),
                ("public", "=", True),
            ],
            limit=1,
        )
        if existing:
            log_event(
                _attach_log,
                logging.DEBUG,
                "sidecar_reuse",
                bundle=bundle,
                url=url,
            )
            self._persist_esm_attachment_rows(
                [],
                touch_ids=existing.ids,
                bundle=bundle,
            )
            return
        self._persist_esm_attachment_rows(
            [
                {
                    "name": url.rsplit("/", 1)[-1],
                    "mimetype": mimetype,
                    "res_model": "ir.ui.view",
                    "res_id": False,
                    "type": "binary",
                    "public": True,
                    "raw": content,
                    "url": url,
                }
            ],
            bundle=bundle,
        )
        log_event(
            _attach_log,
            logging.INFO,
            "sidecar_save",
            bundle=bundle,
            url=url,
            bytes=len(content),
        )

    def _persist_esm_attachment_rows(
        self,
        vals_list: list[dict],
        touch_ids: Sequence[int] = (),
        bundle: str = "",
    ) -> None:
        if _module.current_test or not request:
            if vals_list:
                if self.env.cr.readonly:
                    raise ReadOnlySqlTransaction(
                        "cannot persist ESM attachments on a read-only test cursor"
                    )
                self.env["ir.attachment"].with_user(SUPERUSER_ID).create(vals_list)
            if touch_ids and not self.env.cr.readonly:
                self.env.cr.execute(
                    "UPDATE ir_attachment SET write_date = now() at time zone 'UTC'"
                    " WHERE id = ANY(%s)",
                    (list(touch_ids),),
                )
                self.env["ir.attachment"].browse(list(touch_ids)).invalidate_recordset(
                    ["write_date"],
                )
            return
        try:
            with self.env.registry.cursor(readonly=False) as rw_cr:
                if vals_list:
                    rw_env = api.Environment(rw_cr, SUPERUSER_ID, {})
                    rw_env["ir.attachment"].create(vals_list)
                if touch_ids:
                    rw_cr.execute(
                        "UPDATE ir_attachment SET write_date = now() at time zone 'UTC'"
                        " WHERE id = ANY(%s)",
                        (list(touch_ids),),
                    )
        except Exception:
            if not vals_list:
                log_event(
                    _attach_log,
                    logging.DEBUG,
                    "touch_failed",
                    bundle=bundle,
                    ids=len(touch_ids),
                )
                return
            _logger.warning(
                "ESM attachment escalation to a read-write cursor failed; "
                "creating on the request cursor",
                exc_info=True,
            )
            if self.env.cr.readonly:
                raise ReadOnlySqlTransaction(
                    "no writable cursor reachable for ESM attachments"
                ) from None
            self.env["ir.attachment"].with_user(SUPERUSER_ID).create(vals_list)

    def _get_asset_link_urls(self, bundle: str, debug: str = "") -> list[str]:
        asset_nodes = self._get_asset_nodes(bundle, js=False, debug=debug)
        return [node[1]["href"] for node in asset_nodes if node[0] == "link"]

    def _pregenerate_assets_bundles(self) -> list[str]:
        _logger.runbot("Pregenerating assets bundles")

        js_bundles, css_bundles = self._get_bundles_to_pregenerate()

        start = time.time()
        links = [
            self._get_asset_bundle(bundle, css=False, js=True).js().url
            for bundle in sorted(js_bundles)
        ]
        _logger.info("JS Assets bundles generated in %s seconds", time.time() - start)
        start = time.time()
        links += [
            self._get_asset_bundle(bundle, css=True, js=False).css().url
            for bundle in sorted(css_bundles)
        ]
        _logger.info("CSS Assets bundles generated in %s seconds", time.time() - start)
        return links

    def _get_bundles_to_pregenerate(self) -> tuple[set[str], set[str]]:

        views = self.env["ir.ui.view"].search(
            [("type", "=", "qweb"), ("arch_db", "like", "t-call-assets")]
        )
        js_bundles = set()
        css_bundles = set()
        for view in views:
            for call_asset in etree.fromstring(view.arch_db).xpath(
                "//*[@t-call-assets]"
            ):
                asset = call_asset.get("t-call-assets")
                js = str2bool(call_asset.get("t-js", "True"))
                css = str2bool(call_asset.get("t-css", "True"))
                if js:
                    js_bundles.add(asset)
                if css:
                    css_bundles.add(asset)
        return (js_bundles, css_bundles)
