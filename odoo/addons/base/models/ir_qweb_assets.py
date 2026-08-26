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
from odoo.libs.hashing import cache_hash
from odoo.modules import module as _module
from odoo.tools.assets.esbuild import (
    EXTERNAL_LIB_ALIASES,
    EsbuildCompiler,
    EsbuildResult,
)
from odoo.tools.assets.esbuild_policy import EsbuildCircuit
from odoo.tools.assets.esm_graph import (
    addon_specifier_to_url,
    discover_transitive_import_specifiers,
    find_escaping_relative_imports,
    resolve_specifier_url,
)
from odoo.tools.assets.esm_registry import esm_registry, external_libs
from odoo.tools.assets.nodes import (
    LOADER_SHIM_MARKER,
    AssetNode,
    bridge_external_specifiers,
    combine_bundle_with_templates,
    count_import_map_urls,
    has_esm_test_satellites,
    import_map_specs,
    inline_module_node,
    is_debug_assets,
    is_hoot_test_specifier,
    is_import_map_node,
    is_loader_shim_node,
    link_to_node,
    prepare_register_native_modules_js,
)
from odoo.tools.misc import file_path, str2bool

from odoo.addons.base.models.assetsbundle import AssetsBundle, BundleFileSpec

_logger = logging.getLogger(__name__)

EsmNodePair = tuple[list[AssetNode], list[AssetNode]]

_esm_log = get_asset_logger("esm")
_attach_log = get_asset_logger("attach")
_fallback_log = get_asset_logger("fallback")
_loader_log = get_asset_logger("loader")
_lock_log = get_asset_logger("lock")
_pregen_log = get_asset_logger("pregen")

_esbuild_circuit = EsbuildCircuit()


class _BuildDeclined(Exception):
    pass
class _EsmFallbackError(_BuildDeclined):
    pass
class _StandaloneBundleDeclined(_BuildDeclined):
    pass
class EsbuildBundleError(RuntimeError):
    pass


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

    _is_debug_assets = staticmethod(is_debug_assets)

    def _get_asset_links(
        self,
        bundle: str,
        css: bool = True,
        js: bool = True,
        debug: str | None = None,
        autoprefix: bool = False,
    ) -> list[str]:
        rtl = css and self._is_rtl_language()
        autoprefix = css and autoprefix
        assets_params = self.env["ir.asset"]._prepare_assets_params()

        if self._is_debug_assets(debug):
            return self._get_asset_links_uncached(
                bundle,
                css=css,
                js=js,
                debug_assets=True,
                assets_params=assets_params,
                rtl=rtl,
                autoprefix=autoprefix,
            )
        return self._get_asset_links_cached(
            bundle,
            css=css,
            js=js,
            assets_params=assets_params,
            rtl=rtl,
            autoprefix=autoprefix,
        )

    def _is_rtl_language(self) -> bool:
        return (
            self.env["res.lang"]
            .sudo()
            ._get_data(code=(self.env.lang or self.env.user.lang))
            .direction
            == "rtl"
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
    def _get_asset_links_cached(
        self,
        bundle: str,
        css: bool = True,
        js: bool = True,
        assets_params: dict[str, Any] | None = None,
        rtl: bool = False,
        autoprefix: bool = False,
    ) -> list[str]:
        return self._get_asset_links_uncached(
            bundle, css, js, False, assets_params, rtl, autoprefix=autoprefix
        )

    def _get_asset_content(
        self, bundle: str, assets_params: dict[str, Any] | None = None
    ) -> tuple[list[BundleFileSpec], list[str]]:
        if assets_params is None:
            assets_params = self.env["ir.asset"]._prepare_assets_params()
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
            assets_params = self.env["ir.asset"]._prepare_assets_params()
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

    @staticmethod
    def _link_to_node(
        path: str,
        defer_load: bool = False,
        lazy_load: bool = False,
        media: str | None = None,
    ) -> AssetNode | None:
        return link_to_node(
            path, defer_load=defer_load, lazy_load=lazy_load, media=media
        )

    def _get_asset_links_uncached(
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

    _external_libs = staticmethod(external_libs)

    _specifier_to_static_url = staticmethod(addon_specifier_to_url)

    def _resolve_specifier_url(self, spec: str) -> str | None:
        return resolve_specifier_url(
            spec, self._external_libs(), EsbuildCompiler._LIB_CANDIDATES
        )

    _get_import_map_url_counts = staticmethod(count_import_map_urls)

    _combine_bundle_with_templates = staticmethod(combine_bundle_with_templates)

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

    def _get_standalone_bundle(self, bundle: str) -> tuple[str, str] | None:
        assets_params = self.env["ir.asset"]._prepare_assets_params()
        try:
            return self._get_standalone_bundle_cached(bundle, assets_params)
        except _StandaloneBundleDeclined:
            return None

    @tools.conditional(
        "xml" not in tools.config["dev_mode"],
        tools.ormcache(
            "bundle",
            "tuple(sorted(assets_params.items()))",
            cache="assets",
        ),
    )
    def _get_standalone_bundle_cached(
        self, bundle: str, assets_params: dict[str, Any]
    ) -> tuple[str, str]:
        asset_bundle = self._get_asset_bundle(
            bundle, css=False, assets_params=assets_params
        )
        esbuild_result, _child_bundles = self._compile_with_esbuild_locked(
            bundle, asset_bundle, assets_params
        )
        if not esbuild_result.code:
            raise _StandaloneBundleDeclined
        code = self._combine_bundle_with_templates(
            esbuild_result.code,
            asset_bundle.generate_esm_template_bundle(use_import=False),
        )
        code = self._prepare_loader_shim_js() + "\n" + code
        try:
            url = self._save_esm_attachment(
                bundle,
                code,
                metafile=esbuild_result.metafile,
                sourcemap=None,
            )
        except Exception as exc:
            _logger.warning(
                "Could not persist the standalone bundle %s", bundle, exc_info=True
            )
            raise _StandaloneBundleDeclined from exc
        return url, code

    def _get_esm_bundle_payload(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None = None,
        debug_assets: bool = False,
    ) -> dict:
        if assets_params is None:
            assets_params = self.env["ir.asset"]._prepare_assets_params()
        if debug_assets:
            return self._get_esm_bundle_payload_uncached(bundle, assets_params)
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
        return self._get_esm_bundle_payload_uncached(bundle, assets_params)

    def _get_esm_bundle_payload_uncached(
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
        self._check_lazy_bundle_relative_imports(asset_bundle)
        native_data = asset_bundle.get_native_module_data()
        import_map = dict(self._external_libs())
        import_map.update(native_data["import_map"])
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

    def _check_lazy_bundle_relative_imports(
        self,
        asset_bundle: AssetsBundle,
    ) -> None:
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

    _esbuild_circuit = _esbuild_circuit
    _ESBUILD_COOLDOWN_S: float = 60.0
    _ESBUILD_EXTENDED_COOLDOWN_S: float = 600.0

    def _get_esbuild_config(self):
        return self.env["ir.config_parameter"].sudo()

    def _is_esbuild_fail_closed(self) -> bool:
        return self._get_esbuild_config().get_param_bool(
            "web.esbuild.fail_closed",
            bool(tools.config["test_enable"] or "assets" in tools.config["dev_mode"]),
        )

    def _get_esbuild_bundles_forced_fallback(self) -> set[str]:
        forced_raw = self._get_esbuild_config().get_param(
            "web.esbuild.force_fallback_bundles", ""
        )
        return {s.strip() for s in forced_raw.split(",") if s.strip()}

    def _get_esbuild_cooldown_key(self, bundle: str) -> tuple[str, str]:
        return (self.env.cr.dbname, bundle)

    def _get_esbuild_circuit_state(self, bundle: str) -> tuple[bool, str]:
        return _esbuild_circuit.state(
            self._get_esbuild_cooldown_key(bundle), now=time.monotonic()
        )

    def _open_esbuild_circuit(self, bundle: str, reason: str) -> None:
        config = self._get_esbuild_config()
        now = time.monotonic()
        entry = _esbuild_circuit.record_failure(
            self._get_esbuild_cooldown_key(bundle),
            reason,
            now=now,
            cooldown_s=config.get_param_float(
                "web.esbuild.cooldown_s", self._ESBUILD_COOLDOWN_S
            ),
            extended_cooldown_s=config.get_param_float(
                "web.esbuild.extended_cooldown_s", self._ESBUILD_EXTENDED_COOLDOWN_S
            ),
        )
        log_event(
            _fallback_log,
            logging.WARNING,
            "circuit_open",
            bundle=bundle,
            reason=reason,
            cooldown_s=entry.expiry - now,
            fails=entry.failures,
        )

    def _close_esbuild_circuit(self, bundle: str) -> None:
        if _esbuild_circuit.record_success(self._get_esbuild_cooldown_key(bundle)):
            log_event(
                _fallback_log,
                logging.INFO,
                "circuit_close",
                bundle=bundle,
            )

    _ESBUILD_LOCK_RETRIES: int = 1
    _ESBUILD_LOCK_RETRY_SLEEP_S: float = 0.2

    @contextlib.contextmanager
    def _get_esbuild_lock_cursor(self, bundle: str):
        if self.env.cr.readonly and _module.current_test:
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

    def _acquire_esbuild_lock(self, bundle: str, cr=None) -> bool:
        if cr is None:
            cr = self.env.cr
        config = self._get_esbuild_config()
        retries = config.get_param_int(
            "web.esbuild.lock_retries", self._ESBUILD_LOCK_RETRIES
        )
        sleep_s = config.get_param_float(
            "web.esbuild.lock_retry_sleep_s", self._ESBUILD_LOCK_RETRY_SLEEP_S
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

    _is_hoot_test_specifier = staticmethod(is_hoot_test_specifier)

    @classmethod
    def _get_hoot_specifiers(cls, bundle: str, specifiers: Iterable[str]) -> list[str]:
        registry = esm_registry()
        if bundle in registry.import_map_includes:
            return []
        by_directory = bundle in registry.import_map_included_bundles
        return [
            spec
            for spec in specifiers
            if cls._is_hoot_test_specifier(spec, by_directory=by_directory)
        ]

    @classmethod
    def _prepare_loader_shim_js(cls) -> str:
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

    @classmethod
    def _prepare_loader_shim_node(cls, bundle: str) -> AssetNode:
        return (
            "script",
            {LOADER_SHIM_MARKER: bundle, "text": cls._prepare_loader_shim_js()},
        )

    @staticmethod
    def _has_esm_test_satellites(debug: str | bool | None) -> bool:
        return has_esm_test_satellites(
            debug, test_enable=bool(tools.config["test_enable"])
        )

    @tools.conditional(
        "xml" not in tools.config["dev_mode"],
        tools.ormcache(
            "bundle",
            "tuple(sorted(assets_params.items()))",
            "with_test_satellites",
            "page_scope",
            "esbuild_ok",
            cache="assets",
        ),
    )
    def _get_native_module_nodes_cached(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None = None,
        with_test_satellites: bool = False,
        page_scope: tuple[str, ...] = (),
        esbuild_ok: bool = True,
    ) -> EsmNodePair:
        return self._get_native_module_nodes_uncached(
            bundle,
            debug=False,
            assets_params=assets_params,
            _raise_on_decline=True,
            with_test_satellites=with_test_satellites,
            page_scope=page_scope,
            esbuild_ok=esbuild_ok,
        )

    def _get_native_module_nodes(
        self,
        bundle: str,
        debug: str = "",
        assets_params: dict[str, Any] | None = None,
    ) -> EsmNodePair:
        debug_assets = self._is_debug_assets(debug)
        if assets_params is None:
            assets_params = self.env["ir.asset"]._prepare_assets_params()
        satellites = self._has_esm_test_satellites(debug)
        page_scope = self._get_esm_page_scope(bundle)
        esbuild_ok = not debug_assets and self._can_compile_with_esbuild(bundle)
        if not debug_assets:
            try:
                pre, post = self._get_native_module_nodes_cached(
                    bundle,
                    assets_params=assets_params,
                    with_test_satellites=satellites,
                    page_scope=page_scope,
                    esbuild_ok=esbuild_ok,
                )
            except _EsmFallbackError:
                pre, post = self._get_native_module_nodes_uncached(
                    bundle,
                    debug=debug,
                    assets_params=assets_params,
                    with_test_satellites=satellites,
                    page_scope=page_scope,
                    esbuild_ok=False,
                )
        else:
            pre, post = self._get_native_module_nodes_uncached(
                bundle,
                debug=debug,
                assets_params=assets_params,
                with_test_satellites=satellites,
                page_scope=page_scope,
                esbuild_ok=False,
            )
        self._record_esm_page_bundle(bundle)
        return self._dedup_request_page_scripts(bundle, pre), post

    _is_import_map_node = staticmethod(is_import_map_node)
    _is_loader_shim_node = staticmethod(is_loader_shim_node)
    _get_import_map_specs = staticmethod(import_map_specs)

    def _dedup_request_page_scripts(
        self,
        bundle: str,
        pre_nodes: list[AssetNode],
    ) -> list[AssetNode]:
        if not request:
            return pre_nodes
        first = not getattr(request, "_esm_import_map_rendered", False)
        if first:
            if not any(self._is_import_map_node(node) for node in pre_nodes):
                return pre_nodes
            request._esm_import_map_rendered = True
            request._esm_import_map_specs = self._get_import_map_specs(pre_nodes)
            return pre_nodes
        self._warn_on_dropped_import_map_specs(bundle, pre_nodes)
        return [
            node
            for node in pre_nodes
            if not (self._is_import_map_node(node) or self._is_loader_shim_node(node))
        ]

    def _warn_on_dropped_import_map_specs(
        self, bundle: str, pre_nodes: list[AssetNode]
    ) -> None:
        rendered = getattr(request, "_esm_import_map_specs", frozenset())
        dropped = sorted(self._get_import_map_specs(pre_nodes) - rendered)
        log_event(
            _esm_log,
            logging.WARNING if dropped else logging.DEBUG,
            "importmap_skipped",
            bundle=bundle,
            reason="already_rendered",
            unresolvable=len(dropped),
            specs=",".join(dropped[:5]),
        )

    def _get_native_module_nodes_uncached(
        self,
        bundle: str,
        debug: str = "",
        assets_params: dict[str, Any] | None = None,
        _raise_on_decline: bool = False,
        with_test_satellites: bool = False,
        page_scope: tuple[str, ...] = (),
        esbuild_ok: bool = True,
    ) -> EsmNodePair:
        debug_assets = self._is_debug_assets(debug)
        if assets_params is None:
            assets_params = self.env["ir.asset"]._prepare_assets_params()

        asset_bundle = self._get_asset_bundle(
            bundle,
            js=True,
            css=False,
            debug_assets=debug_assets,
            assets_params=assets_params,
        )
        native_data = (
            asset_bundle.get_native_module_data()
            if debug_assets
            else self._get_native_module_data_cached(
                bundle,
                assets_params=assets_params,
            )
        )

        if not native_data["import_map"]:
            log_event(
                _esm_log,
                logging.DEBUG,
                "no_native_modules",
                bundle=bundle,
            )
            return [], []

        if not debug_assets and esbuild_ok:
            esbuild_result, child_bundles = self._compile_with_esbuild_locked(
                bundle, asset_bundle, assets_params, page_scope
            )
            if esbuild_result.code:
                return self._get_esm_nodes_prod(
                    bundle,
                    asset_bundle,
                    esbuild_result,
                    assets_params,
                    child_bundles,
                    raise_on_decline=_raise_on_decline,
                    with_test_satellites=with_test_satellites,
                )
            if _raise_on_decline:
                raise _EsmFallbackError
        return self._get_esm_nodes_debug(
            bundle,
            asset_bundle,
            native_data,
            debug_assets,
            assets_params,
            with_test_satellites=with_test_satellites,
        )

    def _can_compile_with_esbuild(self, bundle: str) -> bool:
        if bundle in self._get_esbuild_bundles_forced_fallback():
            log_event(_fallback_log, logging.INFO, "admin_override", bundle=bundle)
            return False
        allow, circuit_reason = self._get_esbuild_circuit_state(bundle)
        if not allow:
            log_event(
                _fallback_log,
                logging.DEBUG,
                "circuit_blocked",
                bundle=bundle,
                reason=circuit_reason,
            )
        return allow

    def _get_esbuild_child_externals(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        assets_params: dict[str, Any] | None,
        child_bundles: list[AssetsBundle],
        page_scope: tuple[str, ...] = (),
    ) -> tuple[frozenset[str] | None, dict[str, str]]:
        parent_specs = {a.module_path for a in asset_bundle.native_modules}
        child_specs = {
            asset.module_path
            for child_ab in child_bundles
            for asset in child_ab.native_modules
        } - parent_specs
        secondary_stubs = self._get_secondary_parent_stubs(
            bundle, assets_params, page_scope
        )
        if not child_specs:
            return None, secondary_stubs

        aliasable = {
            spec
            for spec in child_specs
            if "/../" not in spec and not spec.startswith("../")
        }
        if aliasable:
            child_stubs = asset_bundle._bridges.build_shim_sources(aliasable)
            secondary_stubs = {**child_stubs, **secondary_stubs}
        return frozenset(child_specs - aliasable) or None, secondary_stubs

    def _compile_with_esbuild(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        dynamic_child_specs: frozenset[str] | None,
        secondary_stubs: dict[str, str],
    ) -> EsbuildResult:
        config = self._get_esbuild_config()
        try:
            result = asset_bundle.esbuild_native_bundle(
                timeout_s=config.get_param_int(
                    "web.esbuild.timeout_s", EsbuildCompiler._ESBUILD_TIMEOUT_S
                ),
                target=config.get_param("web.esbuild.target")
                or EsbuildCompiler._ESBUILD_TARGET,
                source_maps=config.get_param("web.esbuild.source_maps")
                or EsbuildCompiler._ESBUILD_SOURCE_MAPS,
                dynamic_child_specs=dynamic_child_specs,
                secondary_parent_stubs=secondary_stubs or None,
            )
        except Exception as exc:
            log_event(
                _fallback_log,
                logging.WARNING,
                "esbuild_exception",
                bundle=bundle,
                err=type(exc).__name__,
                msg=str(exc)[:200],
            )
            if self._is_esbuild_fail_closed():
                raise EsbuildBundleError(
                    f"esbuild failed for bundle {bundle!r}: {exc}"
                ) from exc
            self._open_esbuild_circuit(bundle, reason=type(exc).__name__)
            return EsbuildResult("", None, None)
        self._close_esbuild_circuit(bundle)
        return result

    def _compile_with_esbuild_locked(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        assets_params: dict[str, Any] | None,
        page_scope: tuple[str, ...] = (),
    ) -> tuple[EsbuildResult, list[AssetsBundle]]:
        empty = EsbuildResult("", None, None)
        child_bundles: list[AssetsBundle] = []
        if not self._can_compile_with_esbuild(bundle):
            return empty, child_bundles

        with self._get_esbuild_lock_cursor(bundle) as lock_cr:
            if lock_cr is None:
                log_event(
                    _fallback_log, logging.INFO, "lock_unavailable", bundle=bundle
                )
                return empty, child_bundles
            if not self._acquire_esbuild_lock(bundle, cr=lock_cr):
                log_event(_fallback_log, logging.INFO, "lock_contention", bundle=bundle)
                return empty, child_bundles

            child_bundles = self._get_dynamic_child_bundles(
                bundle, assets_params, debug_assets=False
            )
            dynamic_child_specs, secondary_stubs = self._get_esbuild_child_externals(
                bundle, asset_bundle, assets_params, child_bundles, page_scope
            )
            result = self._compile_with_esbuild(
                bundle, asset_bundle, dynamic_child_specs, secondary_stubs
            )
        return result, child_bundles

    def _get_dynamic_parent_bundles(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
    ) -> tuple[str, ...]:
        contributors = dict.fromkeys((bundle,))
        for asset in self.env["ir.asset"]._get_asset_paths(
            bundle=bundle,
            assets_params=(
                self.env["ir.asset"]._prepare_assets_params()
                if assets_params is None
                else assets_params
            ),
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
                or child_name in registry.runtime_bundle_names,
                assets_params=assets_params,
            )
            for child_name in child_names
        ]

    @staticmethod
    def _merge_child_import_maps(
        import_map: dict[str, str],
        child_bundles: list[AssetsBundle],
        *,
        map_specifiers: bool = True,
    ) -> tuple[list[AssetsBundle], set[str]]:
        dynamic_names = esm_registry().dynamic_bundle_names
        dynamic_bundles = []
        child_specifiers: set[str] = set()
        for child_ab in child_bundles:
            child_data = child_ab.get_native_module_data(with_bridges=False)
            child_specifiers.update(child_data["import_map"])
            if map_specifiers:
                import_map.update(child_data["import_map"])
            if child_ab.name in dynamic_names:
                dynamic_bundles.append(child_ab)
        return dynamic_bundles, child_specifiers

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
                set(self._external_libs()),
            )
            self._add_import_map_bridge_urls(
                import_map,
                discovered,
                drop_unresolved=True,
                bundle=include_name,
            )
        return include_names

    def _get_esm_page_scope(self, bundle: str) -> tuple[str, ...]:
        if not request or bundle not in esm_registry().secondary_bundle_names:
            return ()
        return tuple(getattr(request, "_esm_page_bundles", ()))

    @staticmethod
    def _record_esm_page_bundle(bundle: str) -> None:
        if not request:
            return
        rendered = tuple(getattr(request, "_esm_page_bundles", ()))
        if bundle not in rendered:
            request._esm_page_bundles = (*rendered, bundle)

    def _get_secondary_provider_specs(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
        page_scope: tuple[str, ...],
    ) -> set[str]:
        providers = page_scope or esm_registry().secondary_parents.get(bundle) or ()
        installed = self.env["ir.asset"]._get_addons_installed()
        spec_sets = []
        for provider in providers:
            specs = set(
                self._get_asset_bundle(
                    provider,
                    js=True,
                    css=False,
                    debug_assets=False,
                    assets_params=assets_params,
                ).get_native_module_data(with_bridges=False)["import_map"]
            )
            if specs or provider.partition(".")[0] in installed:
                spec_sets.append(specs)
        if not spec_sets:
            return set()
        return (set.union if page_scope else set.intersection)(*spec_sets)

    def _get_secondary_shared_specs(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
        page_scope: tuple[str, ...] = (),
        sec_ab: AssetsBundle | None = None,
    ) -> frozenset[str]:
        if not esm_registry().secondary_parents.get(bundle):
            return frozenset()
        shared = self._get_secondary_provider_specs(bundle, assets_params, page_scope)
        if not shared:
            return frozenset()
        if sec_ab is None:
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
            set(self._external_libs()),
        )
        stubbed = frozenset(set(discovered) & shared)
        if page_scope:
            self._warn_on_late_secondary_providers(
                bundle, assets_params, discovered, stubbed
            )
        return stubbed

    def _warn_on_late_secondary_providers(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
        discovered: Iterable[str],
        stubbed: frozenset[str],
    ) -> None:
        declared = self._get_secondary_provider_specs(bundle, assets_params, ())
        late = sorted((set(discovered) & declared) - stubbed)
        if not late:
            return
        log_event(
            _esm_log,
            logging.WARNING,
            "secondary_provider_renders_late",
            bundle=bundle,
            page=",".join(self._get_esm_page_scope(bundle)),
            count=len(late),
            specs=",".join(late[:5]),
        )

    def _get_secondary_parent_stubs(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
        page_scope: tuple[str, ...] = (),
    ) -> dict[str, str]:
        sec_ab = self._get_asset_bundle(
            bundle,
            js=True,
            css=False,
            debug_assets=False,
            assets_params=assets_params,
        )
        shared = self._get_secondary_shared_specs(
            bundle, assets_params, page_scope, sec_ab=sec_ab
        )
        if not shared:
            return {}
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

    def _add_import_map_bridge_urls(
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
            resolved = self._resolve_specifier_url(spec)
            if resolved:
                import_map[spec] = resolved
                resolved_map[spec] = resolved
            elif current and drop_unresolved:
                del import_map[spec]
        if resolved_map:
            extra = discover_transitive_import_specifiers(
                resolved_map,
                known_specifiers=set(import_map),
                ext_libs=self._external_libs(),
                lib_candidates=EsbuildCompiler._LIB_CANDIDATES,
                bundle_name=bundle,
            )
            for spec in sorted(extra):
                resolved = self._resolve_specifier_url(spec)
                if resolved:
                    import_map[spec] = resolved
                    resolved_map[spec] = resolved
        return resolved_map

    def _prepare_esm_script_node(
        self,
        name: str,
        code: str,
        attrs: dict[str, str],
        *,
        raise_on_decline: bool,
        metafile: str | None = None,
        sourcemap: str | None = None,
    ) -> AssetNode:
        url = None
        try:
            url = self._save_esm_attachment(
                name, code, metafile=metafile, sourcemap=sourcemap
            )
        except Exception as exc:
            log_event(
                _attach_log,
                logging.WARNING,
                "save_failed_inline",
                bundle=name,
                readonly=bool(self.env.cr.readonly),
                declined=raise_on_decline,
                err=type(exc).__name__,
            )
            if not isinstance(exc, ReadOnlySqlTransaction):
                _logger.warning(
                    "Could not persist the ESM bundle %s; serving it inline",
                    name,
                    exc_info=True,
                )
            if raise_on_decline:
                raise _EsmFallbackError from None
        node: dict[str, str] = {"type": "module"}
        node["src" if url else "text"] = url or code
        node.update(attrs)
        return ("script", node)

    def _log_esm_render(
        self,
        bundle: str,
        branch: str,
        pre: list[AssetNode],
        post: list[AssetNode],
        import_map: dict[str, str],
        **extra: Any,
    ) -> None:
        real_urls, bridges, data_uris = self._get_import_map_url_counts(import_map)
        log_event(
            _esm_log,
            logging.DEBUG,
            "render",
            bundle=bundle,
            branch=branch,
            pre=len(pre),
            post=len(post),
            importmap=len(import_map),
            url=real_urls,
            bridges=bridges,
            data=data_uris,
            **extra,
        )

    def _get_esm_import_map_prod(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        assets_params: dict[str, Any] | None,
        child_bundles: list[AssetsBundle] | None,
        *,
        with_test_satellites: bool,
    ) -> tuple[dict[str, str], list[AssetsBundle], tuple[str, ...]]:
        import_map = dict(self._external_libs())
        if child_bundles is None:
            child_bundles = self._get_dynamic_child_bundles(
                bundle, assets_params, debug_assets=False
            )
        dynamic_bundles, child_specifiers = self._merge_child_import_maps(
            import_map, child_bundles, map_specifiers=False
        )

        if dynamic_bundles:
            combined_modules = []
            for dyn_ab in dynamic_bundles:
                combined_modules.extend(dyn_ab.native_modules)
            bridge_map = dynamic_bundles[0]._bridges._build_native_to_legacy_bridge(
                set(import_map) | child_specifiers,
                modules=combined_modules,
            )
            import_map.update(bridge_map)

        include_names = self._merge_include_import_maps(
            bundle,
            import_map,
            assets_params,
            debug_assets=False,
            resolve_bridges=False,
        )

        if with_test_satellites:
            self._merge_secondary_import_maps(
                bundle, import_map, assets_params, debug_assets=False
            )

        if include_names:
            self._add_import_map_parent_self_bridges(asset_bundle, import_map)
        return import_map, dynamic_bundles, include_names

    @staticmethod
    def _add_import_map_parent_self_bridges(
        asset_bundle: AssetsBundle, import_map: dict[str, str]
    ) -> None:
        self_bridges = asset_bundle._bridges._build_parent_self_bridge()
        import_map.update(self_bridges)
        for asset in asset_bundle.native_modules:
            header = asset.parsed_header
            if not (header and header["alias"]):
                continue
            alias = header["alias"]
            if import_map.get(alias, "").startswith("/web/assets/esm/bridges/"):
                continue
            shim = self_bridges.get(asset.module_path)
            if shim:
                import_map[alias] = shim

    def _get_esm_nodes_prod(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        esbuild_result: EsbuildResult,
        assets_params: dict[str, Any] | None,
        child_bundles: list[AssetsBundle] | None = None,
        *,
        raise_on_decline: bool = False,
        with_test_satellites: bool = False,
    ) -> EsmNodePair:
        esbuild_code = esbuild_result.code
        pre = []
        post = []
        prod_import_map, dynamic_bundles, include_names = self._get_esm_import_map_prod(
            bundle,
            asset_bundle,
            assets_params,
            child_bundles,
            with_test_satellites=with_test_satellites,
        )

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
        pre.append(self._prepare_loader_shim_node(bundle))
        esm_tpl = asset_bundle.generate_esm_template_bundle(
            use_import=False,
        )
        bundle_code = self._combine_bundle_with_templates(esbuild_code, esm_tpl)
        post.append(
            self._prepare_esm_script_node(
                bundle,
                bundle_code,
                {"data-bridge": bundle},
                raise_on_decline=raise_on_decline,
                metafile=esbuild_result.metafile,
                sourcemap=esbuild_result.sourcemap,
            )
        )
        _has_satellites = bool(
            esm_registry().import_map_includes.get(bundle),
        )
        if esm_tpl and _has_satellites:
            post.append(
                self._prepare_esm_script_node(
                    f"{bundle}.templates",
                    esm_tpl,
                    {"data-templates": bundle},
                    raise_on_decline=raise_on_decline,
                )
            )
        self._log_esm_render(
            bundle,
            "prod",
            pre,
            post,
            prod_import_map,
            dyn=len(dynamic_bundles),
            includes=len(include_names) if include_names else 0,
        )
        return pre, post

    def _get_esm_preload_links(
        self, bundle: str, native_data: dict[str, Any]
    ) -> list[AssetNode]:
        hoot_owned = set(self._get_hoot_specifiers(bundle, native_data["import_map"]))
        reachable_without_hoot = {
            url
            for spec, url in native_data["import_map"].items()
            if spec not in hoot_owned
        }
        return [
            ("link", {"rel": "modulepreload", "href": url})
            for url in native_data["preload_urls"]
            if url in reachable_without_hoot
        ]

    def _get_esm_import_map_debug(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        native_data: dict[str, Any],
        assets_params: dict[str, Any] | None,
        *,
        debug_assets: bool,
        with_test_satellites: bool,
    ) -> tuple[dict[str, str], dict[str, str]]:
        import_map = dict(self._external_libs())
        import_map.update(native_data["import_map"])

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
        if with_test_satellites:
            self._merge_secondary_import_maps(
                bundle, import_map, assets_params, debug_assets=debug_assets
            )

        all_native_specifiers = set(native_data["import_map"])
        combined_native_modules = list(asset_bundle.native_modules)
        for lazy_ab in lazy_bundles:
            all_native_specifiers.update(m.module_path for m in lazy_ab.native_modules)
            combined_native_modules.extend(lazy_ab.native_modules)

        discovered, _ext_seen = asset_bundle._bridges._discover_bridge_specifiers(
            all_native_specifiers,
            set(self._external_libs()),
            modules=combined_native_modules,
        )
        resolved_bridges = self._add_import_map_bridge_urls(
            import_map, discovered, drop_unresolved=False, bundle=bundle
        )
        return import_map, resolved_bridges

    _prepare_register_native_modules_js = staticmethod(
        prepare_register_native_modules_js
    )

    @staticmethod
    def _resolve_esm_satellite_kind(bundle: str) -> str | None:
        registry = esm_registry()
        if bundle in registry.import_map_included_bundles:
            return "import_map_include"
        if bundle in registry.secondary_bundle_names:
            return "secondary"
        return None

    def _prepare_esm_bridge_js(
        self,
        bundle: str,
        native_data: dict[str, Any],
        bridge_specifiers: list[str],
        *,
        already_has_esm: bool,
    ) -> str:
        hoot_specs = self._get_hoot_specifiers(bundle, bridge_specifiers)
        hoot_spec_set = set(hoot_specs)
        non_hoot_specs = [s for s in bridge_specifiers if s not in hoot_spec_set]
        bridge_code = ""

        if not already_has_esm:
            bridge_code = self._prepare_register_native_modules_js(
                [(spec, spec) for spec in non_hoot_specs], "__m"
            )
        elif satellite := self._resolve_esm_satellite_kind(bundle):
            if non_hoot_specs:
                imports = ", ".join(
                    f"import({json_mod.dumps(s)})" for s in non_hoot_specs
                )
                bridge_code += f"await Promise.allSettled([{imports}]);\n"
                log_event(
                    _esm_log,
                    logging.DEBUG,
                    "satellite_imports",
                    bundle=bundle,
                    kind=satellite,
                    specs=len(non_hoot_specs),
                )
        else:
            own = [
                (spec, native_data["import_map"][spec])
                for spec in non_hoot_specs
                if spec in native_data["import_map"]
            ]
            if own:
                bridge_code += self._prepare_register_native_modules_js(own, "__s")

        start_hoot = [s for s in hoot_specs if s.endswith("/start.hoot")]
        other_tests = [s for s in hoot_specs if s not in start_hoot]
        if start_hoot and any(".test" in spec for spec in other_tests):
            specifier_list = ",\n".join(f"  {json_mod.dumps(s)}" for s in other_tests)
            bridge_code += (
                f"const {{loadAndStart}} = await import("
                f"{json_mod.dumps(start_hoot[0])});\n"
                f"loadAndStart([\n{specifier_list}\n]);\n"
            )
        return bridge_code

    @staticmethod
    def _bridge_external_specifiers(native_data: dict[str, Any]) -> set[str]:
        return bridge_external_specifiers(
            native_data["import_map"], EXTERNAL_LIB_ALIASES
        )

    def _get_esm_nodes_debug(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        native_data: dict[str, Any],
        debug_assets: bool,
        assets_params: dict[str, Any] | None,
        *,
        with_test_satellites: bool = False,
    ) -> EsmNodePair:
        pre_nodes = []
        post_nodes = []
        import_map, resolved_bridges = self._get_esm_import_map_debug(
            bundle,
            asset_bundle,
            native_data,
            assets_params,
            debug_assets=debug_assets,
            with_test_satellites=with_test_satellites,
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
            pre_nodes.extend(self._get_esm_preload_links(bundle, native_data))

        bridge_specifiers = sorted(
            set(native_data["import_map"])
            | self._bridge_external_specifiers(native_data)
        )
        if bridge_specifiers and not _already_has_esm:
            pre_nodes.append(self._prepare_loader_shim_node(bundle))

        if bridge_specifiers:
            bridge_code = self._prepare_esm_bridge_js(
                bundle,
                native_data,
                bridge_specifiers,
                already_has_esm=bool(_already_has_esm),
            )
            if bridge_code.strip():
                post_nodes.append(
                    inline_module_node("data-bridge", bundle, bridge_code)
                )

        esm_tpl = asset_bundle.generate_esm_template_bundle(use_import=True)
        if esm_tpl:
            post_nodes.append(inline_module_node("data-templates", bundle, esm_tpl))

        self._log_esm_render(
            bundle,
            "debug",
            pre_nodes,
            post_nodes,
            import_map,
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
            IrAttachment._generated_asset_domain(url),
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
            self._save_esm_attachment_rows(
                [],
                touch_ids=existing.ids,
                bundle=bundle,
            )
            return url

        self._save_esm_attachment_rows(
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
        self._log_esm_artifacts_superseded(bundle, url)
        log_event(
            _attach_log,
            logging.INFO,
            "save",
            bundle=bundle,
            url=url,
            bytes=len(content_bytes),
        )
        self._save_esm_sidecars(bundle, url, metafile, sourcemap)
        return url

    def _log_esm_artifacts_superseded(self, bundle: str, keep_url: str) -> None:
        if not _attach_log.isEnabledFor(logging.INFO):
            return
        stale_count = (
            self.env["ir.attachment"]
            .sudo()
            .search_count(
                [
                    "|",
                    "|",
                    ("url", "=like", f"/web/assets/%/{bundle}.esm.js"),
                    ("url", "=like", f"/web/assets/%/{bundle}.esm.js.map"),
                    ("url", "=like", f"/web/assets/%/{bundle}.meta.json"),
                    ("url", "!=", keep_url),
                    ("public", "=", True),
                ]
            )
        )
        if stale_count:
            log_event(
                _attach_log,
                logging.INFO,
                "stale_deferred",
                bundle=bundle,
                count=stale_count,
            )

    def _save_esm_sidecars(
        self,
        bundle: str,
        url: str,
        metafile: str | None,
        sourcemap: str | None,
    ) -> None:
        if metafile:
            self._save_esm_sidecar(
                bundle,
                url.removesuffix(".esm.js") + ".meta.json",
                metafile.encode("utf-8"),
                mimetype="application/json",
            )
        if sourcemap:
            self._save_esm_sidecar(
                bundle,
                url + ".map",
                sourcemap.encode("utf-8"),
                mimetype="application/json",
            )

    def _save_esm_sidecar(
        self,
        bundle: str,
        url: str,
        content: bytes,
        mimetype: str,
    ) -> None:
        IrAttachment = self.env["ir.attachment"]
        existing = IrAttachment.sudo().search(
            IrAttachment._generated_asset_domain(url),
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
            self._save_esm_attachment_rows(
                [],
                touch_ids=existing.ids,
                bundle=bundle,
            )
            return
        self._save_esm_attachment_rows(
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

    @staticmethod
    def _drop_rows_already_present(cr, vals_list: list[dict]) -> list[dict]:
        urls = [vals["url"] for vals in vals_list if vals.get("url")]
        if not urls:
            return vals_list
        cr.execute("SELECT url FROM ir_attachment WHERE url = ANY(%s)", (urls,))
        present = {row[0] for row in cr.fetchall()}
        return [vals for vals in vals_list if vals.get("url") not in present]

    def _save_esm_attachment_rows(
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
                    fresh = self._drop_rows_already_present(rw_cr, vals_list)
                    if fresh:
                        rw_env = api.Environment(rw_cr, SUPERUSER_ID, {})
                        rw_env["ir.attachment"].create(fresh)
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
        self._log_pregeneration_coverage(js_bundles)

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

    def _log_pregeneration_coverage(self, js_bundles: set[str]) -> None:
        if not _pregen_log.isEnabledFor(logging.DEBUG):
            return
        registry = esm_registry()
        dynamic = {
            child
            for children in registry.dynamic_children.values()
            for child in children
        }
        installed = self.env["ir.asset"]._get_addons_installed()
        uncovered = dynamic - js_bundles
        uncovered_here = {b for b in uncovered if b.split(".", 1)[0] in installed}
        log_event(
            _pregen_log,
            logging.DEBUG,
            "coverage",
            discovered=len(js_bundles),
            dynamic_declared=len(dynamic),
            uncovered_declared=len(uncovered),
            uncovered_installed=len(uncovered_here),
            bundles=",".join(sorted(uncovered_here)) or "none",
        )

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
