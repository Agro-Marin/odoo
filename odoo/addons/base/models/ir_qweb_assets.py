"""ir.qweb asset & native-ESM pipeline.

Extends ``ir.qweb`` via ``_inherit`` with everything reachable from the
``t-call-assets`` directive: legacy JS/CSS link generation, native-ESM/esbuild
build orchestration (circuit breaker, advisory build lock, import-map assembly)
and content-addressed attachment persistence. Sole templating entry point is
``_compile_directive_call_assets`` (in ``ir_qweb.py``), which calls
``self._get_asset_nodes``.
"""

import contextlib
import hashlib
import json as json_mod  # stdlib json; odoo.tools.json is not needed here
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
from odoo.modules import module as _module
from odoo.tools.assets.esbuild import EsbuildCompiler, EsbuildResult
from odoo.tools.assets.esm_graph import _parse_odoo_module_header
from odoo.tools.assets.esm_registry import esm_registry
from odoo.tools.misc import file_path, str2bool

from odoo.addons.base.models.assetsbundle import AssetsBundle, BundleFileSpec

_logger = logging.getLogger(__name__)

# A single rendered asset node ``(tag_name, attributes)``, the shape the
# compiled ``t-call-assets`` loop unpacks.
AssetNode = tuple[str, dict[str, Any]]
# ``(pre_nodes, post_nodes)`` flanking the legacy bundle in the native-ESM path.
EsmNodePair = tuple[list[AssetNode], list[AssetNode]]

# Structured asset-pipeline loggers (odoo.assets.{category}); trace with
# ``--log-handler=odoo.assets:DEBUG`` or isolate a subsystem via child names.
_esm_log = get_asset_logger("esm")
_attach_log = get_asset_logger("attach")
_fallback_log = get_asset_logger("fallback")
_loader_log = get_asset_logger("loader")
_lock_log = get_asset_logger("lock")


class _EsmFallbackError(Exception):
    """Signal that a production native-ESM render declined (circuit open, lock
    contention, or build failure). Raised by ``_get_native_module_nodes_cached``
    so ormcache never stores the degraded fallback (it does not cache
    exceptions); caught by ``_get_native_module_nodes``, which renders uncached.
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
        """Return the rendered asset nodes for ``bundle``.

        ``debug=assets`` regenerates on source change; otherwise nodes are
        cached. When native ESM modules are present the output gains an import
        map and a bridge ``<script type="module">`` that pre-registers them
        before the (``defer``-ed) legacy bundle executes.
        """
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
            # Non-empty pre_nodes OR post_nodes means the bundle contributed
            # ESM that must ship alongside the legacy links: secondary bundles
            # (import map/shim skipped, already rendered by the parent) may
            # carry only post_nodes, and dropping those loses their bridge code.
            has_native = bool(pre_nodes) or bool(post_nodes)

        # Classic scripts (Bootstrap, Luxon…) must NOT be deferred when native
        # ESM is present: they set UMD globals native modules read at module
        # scope, and non-deferred scripts run during parsing, before any
        # <script type="module">, so those globals are ready in time.
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
        """Whether ``debug`` requests the un-cached, per-file assets mode.

        The ``isinstance(..., str)`` guard is load-bearing: compiled QWeb passes
        ``values.get("debug")`` which may be ``None`` (or a bare ``bool``), and
        the older ``"assets" in debug`` idiom raises ``TypeError`` on a non-str.
        Any non-string input degrades to non-debug instead of crashing.
        """
        return isinstance(debug, str) and "assets" in debug

    def _get_asset_links(
        self,
        bundle: str,
        css: bool = True,
        js: bool = True,
        debug: str | None = None,
        autoprefix: bool = False,
    ) -> list[str]:
        """Return asset links (URLs), not nodes.

        ``debug=assets`` regenerates on source change; otherwise links are cached.
        """
        rtl = (
            self.env["res.lang"]
            .sudo()
            ._get_data(code=(self.env.lang or self.env.user.lang))
            .direction
            == "rtl"
        )
        assets_params = self.env["ir.asset"]._get_asset_params()  # website_id
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

    # other methods used for the asset bundles
    @tools.conditional(
        # Non-xml-debug mode: cache forever; admin clears via server restart or
        # "Clear server cache" in debug tools.
        "xml" not in tools.config["dev_mode"],
        tools.ormcache(
            "bundle",
            "css",
            "js",
            "tuple(sorted(assets_params.items()))",
            "rtl",
            "autoprefix",
            cache="assets",
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
            assets_params = self.env["ir.asset"]._get_asset_params()  # website_id
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
        # ``_link_to_node`` returns None for an unrecognized extension (e.g. an
        # external URL with a query string). Drop those — the ``t-call-assets``
        # loop unpacks ``(tagName, attrs)`` and would raise TypeError on None —
        # but log each so a misclassified asset is visible, not silently gone.
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
                # "lazy_load" adds "defer" in JS, not here (here would not be
                # W3C valid). See LAZY_LOAD_DEFER.
                attributes["defer"] = "defer"
            if path:
                if lazy_load:
                    attributes["data-src"] = path
                else:
                    attributes["src"] = path

            # Load-failure self-healing lives in the module loader shim
            # (``module_loader.js`` catches script errors for ``/web/assets/``
            # URLs and triggers one guarded reload) — not an onerror attr here.
            return ("script", attributes)

        if is_css:
            # ``rel="stylesheet"`` is CSS by definition → always ``text/css``.
            # ``STYLE_EXTENSIONS`` includes scss/sass, but those compile to CSS
            # before serving; hardcoding ``text/css`` avoids emitting an invalid
            # ``text/scss`` type if a raw ``.scss`` href ever slips through.
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

    # URL of the OWL ESM library — real ESM build, loaded via import map
    _OWL_ESM_URL = "/web/static/lib/owl/owl.es.js"
    # Import-map entries for esbuild-externalized libraries. Canonical
    # definition lives in ``odoo.libs.constants`` (so ``assetsbundle`` can read
    # it without an import cycle); this alias keeps ``self._ODOO_EXTERNAL_LIBS``.
    _ODOO_EXTERNAL_LIBS = ODOO_EXTERNAL_LIBS

    @staticmethod
    def _specifier_to_static_url(spec: str) -> str | None:
        """Resolve an ``@addon/path`` specifier to a served static URL.

        Follows Odoo's bundling convention:
          * ``@web/core/registry``       → ``/web/static/src/core/registry.js``
          * ``@web/../lib/hoot/hoot``    → ``/web/static/lib/hoot/hoot.js``
          * ``@web/../tests/foo``        → ``/web/static/tests/foo.js``

        Returns ``None`` for specifiers outside the convention (bare ``luxon``,
        or the RESERVED ``@odoo/*`` namespace of vendored libs) — those resolve
        through ``_ODOO_EXTERNAL_LIBS``, which every caller probes first.
        """
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
        """Split import-map targets into ``(real_urls, bridge_shims, data_uris)``.

        Diagnostic only — feeds the ``render`` log event. Bridge shims live
        under ``/web/assets/esm/bridges/``; ``data:`` URIs are the legacy
        pre-attachment form (a non-zero count post-refactor flags an
        unmigrated caller). Shared by the prod and debug paths.
        """
        n_bridges = sum(
            1 for v in import_map.values() if v.startswith("/web/assets/esm/bridges/")
        )
        n_data = sum(1 for v in import_map.values() if v.startswith("data:"))
        n_real = len(import_map) - n_bridges - n_data
        return n_real, n_bridges, n_data

    @staticmethod
    def _combine_bundle_with_templates(esbuild_code: str, esm_tpl: str) -> str:
        """Append inlined template registration to the esbuild bundle, keeping
        any trailing ``//# sourceMappingURL=`` directive last.

        Templates MUST share the bundle's module body so ``registerTemplate``
        runs right after ``registerNativeModules`` (before the microtask queue
        drains and any ``whenReady`` mount fires). Since browsers honour only
        the LAST ``sourceMappingURL`` comment, the trailing directive is
        stripped and re-emitted at the end. Returns ``esbuild_code`` unchanged
        when there is no template body.
        """
        if not esm_tpl:
            return esbuild_code
        esb_base = esbuild_code
        sm_directive = ""
        tail_idx = esbuild_code.rfind("//# sourceMappingURL=")
        if tail_idx != -1 and "\n" not in esbuild_code[tail_idx:].rstrip("\n"):
            # The directive is esbuild's last non-empty line; the match spans
            # from the marker to EOF (plus an optional single trailing newline).
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
        """Fetch native module data for a bundle (cached in non-dev mode).

        Returns the dict from ``AssetsBundle.get_native_module_data()``,
        with sets converted to sorted tuples for cache serialization.
        """
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
        """Payload for the ``/web/bundle`` lazy-load endpoint (dispatch).

        ``?debug=assets`` requests bypass the cache so file edits show up
        immediately, mirroring the native-module-nodes dispatch. Cached
        values are shared by reference — callers must treat the dict and
        its members as immutable.
        """
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
        """Cached variant of the lazy-bundle payload (see the dispatch)."""
        return self._esm_bundle_payload_impl(bundle, assets_params)

    def _esm_bundle_payload_impl(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
    ) -> dict:
        """Compute the lazy ESM bundle payload.

        The template attachment is content-addressed, so repeat computes reuse
        the same URL; the newest row per name survives ``_gc_esm_assets``,
        keeping cached payload URLs valid.
        """
        asset_bundle = self._get_asset_bundle(
            bundle,
            js=True,
            css=False,
            debug_assets=True,
            assets_params=assets_params,
        )
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

    # Minified loader-shim cache, populated by _build_loader_shim_js() and
    # recomputed only when the source file's mtime changes (dev hot reload).
    _loader_shim_cache: tuple[float, str] | None = None

    # ── esbuild circuit breaker (per-process, per-bundle) ──
    # Each ``esbuild_native_bundle()`` failure opens a cooldown during which we
    # skip esbuild and serve the debug fallback, protecting against retry-storms
    # when esbuild is broken (missing binary, syntax error, permissions). State
    # is per worker process, cleared on restart. MUST be namespaced by database:
    # it is one process-global class attribute shared by every registry in the
    # worker (class attrs are inherited, not copied — see orm/registration.py),
    # so an unscoped key would let one tenant's failure open the breaker for the
    # same bundle name in every other tenant.
    _esbuild_cooldowns: dict[tuple[str, str], tuple[float, str, int]] = {}
    # Defaults, overridable via ir.config_parameter (keys mirror these names;
    # see ``_get_esbuild_setting``). Kept as class attributes because tests read
    # them directly (``self.IrQweb._ESBUILD_COOLDOWN_S``).
    _ESBUILD_COOLDOWN_S: float = 60.0  # after 1st failure
    _ESBUILD_EXTENDED_COOLDOWN_S: float = 600.0  # after 2nd consecutive failure

    # ── Tunable settings (ir.config_parameter) ──
    # Every hardcoded esbuild timing is surfaced as a ``web.esbuild.<name>``
    # system parameter so ops can tune post-incident without redeploying;
    # defaults match the hardcoded values.
    _ESBUILD_SETTING_KEYS: frozenset = frozenset(
        {
            "cooldown_s",
            "extended_cooldown_s",
            "lock_retries",
            "lock_retry_sleep_s",
            "timeout_s",
            "target",
            # Source-map mode: ``""`` (off, default), ``"linked"`` (sidecar
            # ``.js.map`` + ``//# sourceMappingURL=`` directive — the only mode
            # devtools and the error-dialog stack annotator can discover),
            # ``"external"`` (sidecar, no directive), or ``"inline"`` (base64 in
            # the bundle, ~2x download). The sidecar is served immutable by
            # ``content_esm_assets``.
            "source_maps",
        }
    )

    def _get_esbuild_setting(self, name: str, default, cast=None):
        """Return ``web.esbuild.<name>``, or ``default`` if unset/unparseable.

        ``cast`` is applied to the raw value; on cast failure the default is
        used and a DEBUG log records why (so a typo'd parameter is spottable).
        """
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
        # get_param() returns ``False`` (not ``None``) when unset, so use
        # truthiness: ``raw is None`` would miss that and poison callers with
        # ``float(False) == 0.0``. Any real string value is truthy.
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

    def _esbuild_forced_fallback_bundles(self) -> set[str]:
        """Bundle names an admin has forced to the debug-mode fallback.

        Read from ``web.esbuild.force_fallback_bundles`` (comma-separated).
        ``_get_native_module_nodes`` also bypasses the node cache for these, so
        a freshly added override silences a bundle without a restart.
        """
        forced_raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("web.esbuild.force_fallback_bundles", "")
        )
        return {s.strip() for s in forced_raw.split(",") if s.strip()}

    def _esbuild_cooldown_key(self, bundle: str) -> tuple[str, str]:
        """Database-scoped key for ``_esbuild_cooldowns``.

        Namespacing by ``cr.dbname`` isolates tenants: the dict is a shared
        process-global, so a bundle-only key would leak one database's failure
        into every other database's breaker.
        """
        return (self.env.cr.dbname, bundle)

    def _esbuild_circuit_state(self, bundle: str) -> tuple[bool, str]:
        """Check the circuit-breaker state for a bundle.

        Returns ``(allow, reason)``.  When ``allow`` is False, callers
        should skip esbuild and go straight to the debug-mode fallback.
        """
        key = self._esbuild_cooldown_key(bundle)
        entry = type(self)._esbuild_cooldowns.get(key)
        if not entry:
            return True, ""
        expiry, reason, _fails = entry
        if time.monotonic() < expiry:
            return False, reason
        # Cooldown expired — clear the block so we try again.  Keep the
        # failure count so a second consecutive failure escalates to the
        # extended cooldown.
        type(self)._esbuild_cooldowns[key] = (0.0, reason, _fails)
        return True, ""

    def _esbuild_circuit_record_failure(self, bundle: str, reason: str) -> None:
        """Open the circuit for ``bundle`` after a failed build.

        Second consecutive failure promotes the cooldown to the extended
        value; a successful build clears the counter.  Cooldown values
        come from ``web.esbuild.cooldown_s`` / ``extended_cooldown_s``,
        falling back to the class-level defaults if unset.
        """
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
        """Close the circuit for ``bundle`` after a successful build."""
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

    # ── esbuild concurrency lock (advisory, transaction-scoped) ──
    # Without it, two requests cold-starting the same bundle each spawn esbuild
    # (~3s on ``web.assets_web``) and race to INSERT the same attachment. A
    # transaction-scoped advisory lock serializes the expensive path: the first
    # request runs esbuild; concurrent ones see the lock held, degrade to the
    # debug branch for that single render, and the lock auto-releases on commit.
    # ``pg_try_advisory_xact_lock`` (non-blocking, one short retry) avoids tying
    # up workers behind a slow esbuild when reverse-proxy timeouts are short.
    # The lock must NEVER run on a read-only request cursor: PostgreSQL forbids
    # advisory locks during recovery (SQLSTATE 55000, unretried → hard 500), so
    # ``_esbuild_lock_cursor`` picks the legal cursor.

    _ESBUILD_LOCK_RETRIES: int = 1
    _ESBUILD_LOCK_RETRY_SLEEP_S: float = 0.2

    @contextlib.contextmanager
    def _esbuild_lock_cursor(self, bundle: str):
        """Yield the cursor on which to take the esbuild advisory lock.

        Read-write renders use the request cursor, held until the transaction
        ends (spanning build and persist). Read-only renders can't lock their
        own cursor (forbidden during recovery), so they use a dedicated
        read-write REGISTRY cursor held for the build only; releasing before
        the persist is fine since the lock only serializes the subprocess and
        the persist is idempotent (content-addressed).

        Yields ``None`` when no cursor may legally lock (a read-only TEST
        cursor, or the primary unreachable): the caller skips esbuild and
        degrades to the debug fallback.
        """
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
        """Try to take the per-bundle advisory lock on cursor *cr*.

        Returns True if acquired (transaction-scoped, auto-released on
        commit/rollback). ``cr`` defaults to the request cursor; readonly
        renders must pass the read-write cursor from ``_esbuild_lock_cursor``.
        Returns False after ``retries + 1`` attempts (caller falls back to
        debug mode); ``retries`` and the sleep come from
        ``web.esbuild.lock_retries`` / ``lock_retry_sleep_s``.
        """
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
    def _is_hoot_test_specifier(specifier: str) -> bool:
        """Whether ``specifier`` resolves to a Hoot test file.

        Hoot wraps each test in a ``describe()`` suite and loads them via
        ``start.hoot``'s ``loadAndStart()``, so they must NOT be eagerly
        imported. Tour files (``/tests/tours/*.js``) are excluded — they
        self-register into ``web_tour.tours`` on load and ARE eager-imported.
        """
        if "/tours/" in specifier:
            return False
        return (
            "/../tests/" in specifier or ".test" in specifier or "/tests/" in specifier
        )

    @classmethod
    def _build_loader_shim_js(cls) -> str:
        """Return a self-executing JS snippet that bootstraps ``odoo.loader``.

        Source lives in ``web/static/src/module_loader.js`` (editable with JS
        tooling); read and minified once, cached by mtime so dev edits are
        picked up. The loader MUST stay a class instance (not a plain object):
        Hoot tests subclass it via ``odoo.loader.constructor`` for isolated
        module graphs, which a plain-object shim would break.
        """
        src_path = Path(file_path("web/static/src/module_loader.js"))
        mtime = src_path.stat().st_mtime
        cached = cls._loader_shim_cache
        if cached and cached[0] == mtime:
            return cached[1]
        source = src_path.read_text(encoding="utf-8")
        # rjsmin preserves class syntax and IIFEs correctly.
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
        # Mirror the links/native-data caches: cache "forever" in non-xml-debug
        # mode, cleared by ir.asset writes (clear_cache("assets")) and module
        # update, or a manual server-cache clear.
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
        """Cached production native-ESM nodes (non-debug).

        Runs the full assembly via ``_get_native_module_nodes_impl`` so warm
        renders skip bundle construction, esbuild, and the template parse. A
        declined attempt (circuit open, lock contention, build failure, or an
        inline-persist degradation) raises ``_EsmFallbackError`` rather than
        returning the degraded nodes, so ormcache never caches a degraded result.
        """
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
        """Dispatch native-ESM node generation through the assets cache.

        Production (non-debug) renders go through the ormcached
        ``_get_native_module_nodes_cached`` — read-only cursors included:
        persistence uses a dedicated read-write registry cursor and the build
        lock is taken through ``_esbuild_lock_cursor``, so nothing writes on the
        request cursor. Gating on ``cr.readonly`` (as this once did) made every
        replica render pay the full uncached assembly and ran the advisory lock
        on the standby cursor, forbidden during recovery (hard 500).

        ``?debug=assets`` and the esbuild-declined fallback render uncached via
        ``_get_native_module_nodes_impl``.
        """
        debug_assets = self._is_debug_assets(debug)
        if assets_params is None:
            assets_params = self.env["ir.asset"]._get_asset_params()
        if not debug_assets and bundle not in self._esbuild_forced_fallback_bundles():
            try:
                pre, post = self._get_native_module_nodes_cached(
                    bundle, assets_params=assets_params
                )
            except _EsmFallbackError:
                # esbuild declined → render the uncached debug fallback. The
                # re-run re-evaluates the decline conditions (cheap; no second
                # subprocess) and builds the asset_bundle the debug branch needs.
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
        """Keep at most one ``<script type="importmap">`` per request.

        A page composing several ESM bundles must render only the FIRST
        bundle's map; the browser drops duplicate keys ("import map rule … was
        removed") otherwise. Runs in the dispatcher, not the cached impl, since
        the decision is request-scoped while the cache key is
        ``(bundle, assets_params)`` — filtering inside the cache would bake one
        page's composition into every later render.

        SOLE WRITER of ``request._esm_import_map_rendered`` (``_esm_debug_nodes``
        only reads it): if the debug branch also set it, this pass would strip
        the importmap that branch had just emitted, leaving bare specifiers
        unresolved. Returns a filtered COPY — cached lists must never be mutated.
        """
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
        """Generate import map, OWL pre-load, and bridge nodes for native ESM.

        :param debug: debug flags (``'assets'`` rebuilds without cache)
        :return: ``(pre_nodes, post_nodes)`` flanking the legacy bundle
        """
        # ``pre_nodes`` go BEFORE the legacy bundle:
        #   1. ``<script type="importmap">`` with specifier → URL mappings
        #      (OWL resolves through its ``@odoo/owl`` entry — no separate script)
        #   2. the ``odoo.loader`` bootstrap shim (``_build_loader_shim_js``)
        #   3. ``<link rel="modulepreload">`` hints — only on the esbuild-declined
        #      fallback path (``_esm_debug_nodes``); the esbuild prod path emits none
        # ``post_nodes`` go AFTER: the ``<script type="module">`` bridge, which
        # imports native modules and registers them via ``registerNativeModules()``
        # (runs after the bundle — ``defer`` and ``type="module"`` share one
        # deferred queue in document order).
        debug_assets = self._is_debug_assets(debug)
        if assets_params is None:
            assets_params = self.env["ir.asset"]._get_asset_params()

        if debug_assets:
            # In debug mode, rebuild from scratch (no cache)
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

        # ── Production: esbuild bundling ──
        # A single minified <script type="module"> replaces 600+ files + import
        # map + modulepreload hints + bridge script. Two pre-checks (admin
        # override ``web.esbuild.force_fallback_bundles`` and the circuit
        # breaker) short-circuit the expensive path (subprocess + attachment
        # insert) to the debug-mode branch — slower and unminified but functional.
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
        """Run production esbuild bundling for ``bundle`` if allowed.

        Honors the admin force-fallback override, the circuit breaker and the
        advisory build lock, and records circuit success/failure.

        :return: ``(esbuild_result, child_bundles)``. ``esbuild_result.code``
            is ``""`` when the build is skipped or fails (caller degrades to
            debug nodes). ``child_bundles`` are the dynamic-child bundles built
            for the spec scan, reused by ``_esm_prod_nodes`` (empty when skipped).
        """
        # Admin override (``web.esbuild.force_fallback_bundles``). The node
        # cache is bypassed for these in the dispatcher, so reaching here
        # for a forced bundle means an uncached (debug / fallback) render.
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
            # Silent skip during cooldown: the circuit-open event was logged
            # once when the breaker tripped; don't spam a line per request.
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
                    # No cursor may legally take the lock (readonly render with
                    # primary unreachable, or a readonly test cursor). Skip
                    # esbuild rather than run an unserialized build whose
                    # attachment couldn't be persisted anyway; caller degrades.
                    log_event(
                        _fallback_log,
                        logging.INFO,
                        "lock_unavailable",
                        bundle=bundle,
                    )
                elif not self._esbuild_try_acquire_lock(bundle, cr=lock_cr):
                    # Another request is mid-build; degrade THIS render to debug
                    # mode so the page loads without waiting. INFO because
                    # frequent contention signals a need for pre-generation.
                    log_event(
                        _fallback_log,
                        logging.INFO,
                        "lock_contention",
                        bundle=bundle,
                    )
                else:
                    # Pre-compute dynamic children's native-module specs so the
                    # parent's esbuild call can externalise them (see
                    # ``esbuild_native_bundle``). The child bundles are needed
                    # by ``_esm_prod_nodes`` anyway, so this costs only a comprehension.
                    child_bundles = self._get_dynamic_child_bundles(
                        bundle, assets_params, debug_assets=False
                    )
                    _child_specs = {
                        asset.module_path
                        for child_ab in child_bundles
                        for asset in child_ab.native_modules
                    }
                    # A secondary/test bundle (``web.assets_tests``) must not
                    # inline the core singletons it shares with its parent app
                    # bundle — alias them to shims reading ``odoo.loader.modules``
                    # so they resolve to the parent's registered instance.
                    secondary_stubs = self._secondary_parent_stubs(
                        bundle, assets_params
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
                            dynamic_child_specs=frozenset(_child_specs) or None,
                            secondary_parent_stubs=secondary_stubs or None,
                        )
                        self._esbuild_circuit_record_success(bundle)
                    except Exception as e:
                        # Distinct ``odoo.assets.fallback`` event so alerting on
                        # prod→debug degradation needn't string-match a message.
                        # Degradation falls through to the debug branch below.
                        log_event(
                            _fallback_log,
                            logging.WARNING,
                            "esbuild_exception",
                            bundle=bundle,
                            err=type(e).__name__,
                            msg=str(e)[:200],
                        )
                        self._esbuild_circuit_record_failure(
                            bundle,
                            reason=type(e).__name__,
                        )
                        esbuild_result = EsbuildResult("", None, None)
        return esbuild_result, child_bundles

    # ── Import-map assembly helpers, shared by the prod and debug node builders ──

    def _get_dynamic_child_bundles(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
        *,
        debug_assets: bool,
    ) -> list[AssetsBundle]:
        """Construct the ``AssetsBundle`` of every dynamic child of *bundle*.

        Debug renders build every child per-file (``debug_assets=True``);
        production builds only the truly dynamic children (runtime
        ``loadBundle`` targets) that way, so their import map exposes
        individually loadable URLs.
        """
        registry = esm_registry()
        return [
            self._get_asset_bundle(
                child_name,
                js=True,
                css=False,
                debug_assets=debug_assets
                or child_name in registry.dynamic_bundle_names,
                assets_params=assets_params,
            )
            for child_name in registry.dynamic_children.get(bundle, ())
        ]

    @staticmethod
    def _merge_child_import_maps(
        import_map: dict[str, str],
        child_bundles: list[AssetsBundle],
    ) -> list[AssetsBundle]:
        """Merge every child bundle's import map into *import_map* (in place).

        Pre-registers dynamic ESM specifiers so runtime ``import()`` (after
        ``loadBundle``) can resolve them — URLs only, modules not eagerly
        loaded. ``with_bridges=False`` skips the per-child bridge build;
        bridges are built separately under each caller's policy.

        :return: the subset of *child_bundles* that are dynamic, for the
            caller's bridge assembly.
        """
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
        """Merge *bundle*'s IMPORT_MAP_INCLUDES satellite import maps into
        *import_map*, in place (e.g. test bundles that skip esbuild and rely on
        the parent's map for bare-specifier resolution).

        The two callers differ only in bridge policy:

        ``resolve_bridges=False`` (production) — reuses the ormcached native
        data. Include shims cover specifiers its files import from elsewhere,
        but dynamic-child specifiers keep their direct URL (first-wins
        ``setdefault``): a shim would yield undefined exports at page-load when
        ``odoo.loader.modules`` isn't yet populated, and the direct URL
        preserves singleton identity (browsers singleton ES modules by URL).

        ``resolve_bridges=True`` (debug) — shims read ``odoo.loader.modules``,
        which nothing populates without an esbuild bundle, so merging them
        verbatim poisons the module graph (2026-06-10: ~1311 hoot tests failed
        under ``?debug=assets`` with every shim export ``undefined``). Instead
        the bridge specifier KEYS are discovered and each resolved to a direct
        URL (``drop_unresolved=True``: a clean "module not found" beats an
        undefined-property crash).

        :return: the include bundle names (truthiness gates satellite-only work).
        """
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
            # The exclusion set is the include's own import-map keys, i.e.
            # the exact ``native_specifiers`` the bridge build would use.
            discovered, _ext_seen = include_ab._bridges._discover_bridge_specifiers(
                set(include_data["import_map"]),
                set(self._ODOO_EXTERNAL_LIBS),
            )
            self._resolve_bridge_specifiers_to_urls(
                import_map,
                discovered,
                drop_unresolved=True,
            )
        return include_names

    def _secondary_shared_specs(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
    ) -> frozenset[str]:
        """Specifiers a SECONDARY esbuild bundle must alias to a loader shim
        rather than inline, to preserve singleton identity with its parent(s).

        A ``secondary_import_map_includes`` bundle (``web.assets_tests``) is
        esbuild-compiled self-contained, so every ``@web/core/*`` module it
        imports transitively is INLINED — a second copy distinct from the one
        the parent app bundle registered in ``odoo.loader.modules``. Patching
        that copy from a test (``patchWithCleanup(browser, …)``) never reaches
        the running app, and RPC's ``browser.fetch`` keeps using the app's copy
        (see the 2026-07 singleton-split research note). The caller
        (``_secondary_parent_stubs``) turns each returned specifier into a
        module-exact ``--alias`` to a shim reading ``odoo.loader.modules``.

        The safe set is::

            discovered(bundle) ∩ ⋂ parent.native_specifiers

        * ``discovered`` — specifiers this bundle's native modules import from
          OUTSIDE the bundle (only those can be inlined-and-split).
        * the parent intersection — specifiers EVERY declared parent registers,
          so the shim's ``odoo.loader.modules.get(spec)`` always finds an
          instance whichever parent is on the page (backend ``assets_web``,
          ``/pos/ui`` ``assets_prod``, a frontend bundle, …). A specifier only
          SOME parents own (e.g. ``@web/session``, absent from the frontend
          bundle) stays inlined — aliasing it would make the shim read
          ``undefined`` on pages whose parent never registered it.

        Parents not installed in this DB contribute no specifiers and are
        skipped (their page never renders), widening the set to what the
        installed parents share — never referencing a bundle that cannot
        resolve it. Returns an empty set for non-secondary bundles.
        """
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
            if specs:  # skip uninstalled / empty parents — their page never renders
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
        """``{spec: shim_js}`` for a secondary bundle's shared specifiers.

        Each shim re-exports from ``odoo.loader.modules.get(spec)``. The
        esbuild layer writes them to temp files and wires a module-exact
        ``--alias`` so the shim is inlined in place of a second copy of the
        shared module — preserving singleton identity with the parent app
        bundle (which registered ``spec`` and evaluates first). Empty for a
        non-secondary bundle.
        """
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
        """Merge NEW import-map specifiers from *bundle*'s secondary satellite
        bundles into *import_map*, in place (e.g. ``web.assets_tests``).

        First-wins (``setdefault``): the parent's resolved URLs are never
        overridden by a satellite's bridge shims, which would create circular
        shim references during the parent's bridge initialisation.
        """
        for sec_name in esm_registry().secondary_import_map_includes.get(bundle, ()):
            sec_ab = self._get_asset_bundle(
                sec_name,
                js=True,
                css=False,
                debug_assets=debug_assets,
                assets_params=assets_params,
            )
            # Only ``import_map`` is consumed; skip the bridge build.
            sec_data = sec_ab.get_native_module_data(with_bridges=False)
            for spec, url in sec_data["import_map"].items():
                import_map.setdefault(spec, url)

    def _resolve_bridge_specifiers_to_urls(
        self,
        import_map: dict[str, str],
        discovered: Iterable[str],
        *,
        drop_unresolved: bool,
    ) -> dict[str, str]:
        """Resolve *discovered* bridge specifiers to DIRECT URLs in *import_map*
        (in place) — the debug-mode bridge policy.

        Debug mode has no esbuild bundle to populate ``odoo.loader.modules``, so
        shims crash. For each specifier: (1) keep an existing direct URL
        (outside ``/web/assets/esm/bridges/`` and ``data:``), preserving
        singleton identity; (2) else prefer ``_ODOO_EXTERNAL_LIBS`` then the
        convention-derived static URL; (3) leave unresolvable specifiers out —
        ``drop_unresolved=True`` also removes their stale bridge/data mapping so
        the browser gets a clean "module not found".

        :return: the ``{specifier: url}`` mappings applied.
        """
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
        """Assemble production native-ESM nodes from a successful esbuild build.

        Builds the merged import map (externals, dynamic bundles, includes,
        secondary satellites, self-bridges, alias overrides), emits the
        importmap + loader shim, inlines template registration, and persists
        (or inlines, in read-only txns) the module and templates attachments.

        :param child_bundles: dynamic-child bundles already built by
            ``_esm_run_esbuild``; ``None`` constructs them.
        :param raise_on_decline: raise ``_EsmFallbackError`` instead of inlining
            when no writable cursor is reachable. Set by the ormcached caller so
            multi-MB inline nodes never enter the process cache.
        :return: ``(pre, post)`` flanking the legacy bundle
        """
        esbuild_code = esbuild_result.code
        pre = []
        post = []
        # Import map: @odoo/* externals + dynamic bundle specifiers
        # so runtime import() can resolve them.
        prod_import_map = dict(self._ODOO_EXTERNAL_LIBS)

        # Collect dynamic ESM bundles and build bridges for their @web/...
        # deps (shims reading from odoo.loader.modules — same instance, no
        # dups). Reuse the child bundles ``_esm_run_esbuild`` already built
        # for the spec scan (15 constructions saved per cold assets_web render).
        if child_bundles is None:
            child_bundles = self._get_dynamic_child_bundles(
                bundle, assets_params, debug_assets=False
            )
        dynamic_bundles = self._merge_child_import_maps(prod_import_map, child_bundles)

        # Build instance-sharing bridges for dynamic bundles, combining ALL
        # their native_modules so bridges export the union of needed names
        # (e.g. spreadsheet's `groupBy`, website's `shallowEqual` in one bridge).
        if dynamic_bundles:
            combined_modules = []
            for dyn_ab in dynamic_bundles:
                combined_modules.extend(dyn_ab.native_modules)
            # The first bundle hosts the build (persistence env + log
            # name); the combined module list is passed explicitly.
            bridge_map = dynamic_bundles[0]._bridges._build_native_to_legacy_bridge(
                set(prod_import_map),
                modules=combined_modules,
            )
            prod_import_map.update(bridge_map)

        # Merge include import maps (test bundles that skip esbuild), production
        # bridge policy (cached data + first-wins shims — see the helper).
        include_names = self._merge_include_import_maps(
            bundle,
            prod_import_map,
            assets_params,
            debug_assets=False,
            resolve_bridges=False,
        )

        # Include NEW import-map specifiers from secondary satellite
        # bundles (first-wins — see the helper's docstring).
        self._merge_secondary_import_maps(
            bundle,
            prod_import_map,
            assets_params,
            debug_assets=False,
        )

        # Satellites load this bundle's individual source files, which may
        # import bare specifiers only resolved inside the esbuild bundle. Emit
        # self-bridges reading from ``odoo.loader.modules`` (populated by the
        # bundle's ``registerNativeModules``).
        #
        # IMPORTANT: these bridges OVERRIDE any URL a satellite published for
        # the same specifier, so a satellite's ``import { GraphModel }`` lands
        # on the parent's already-registered singleton instead of re-fetching
        # and re-evaluating a second instance. Without this, every
        # ``patchWithCleanup(GraphModel.prototype, …)`` in a test would patch a
        # parallel-universe class the production controller never sees. The
        # bridge preserves the singleton identity HOOT's mocks rely on.
        if include_names:
            self_bridges = asset_bundle._bridges._build_parent_self_bridge()
            prod_import_map.update(self_bridges)
            # ── Alias override ──
            # Modules with an ``alias=@odoo/xyz`` header (hoot.js, hoot-dom.js,
            # hoot-mock.js) are in ``_ODOO_EXTERNAL_LIBS`` with a DIRECT URL, so
            # a satellite's ``import "@odoo/hoot"`` would re-fetch and re-evaluate
            # the file the esbuild bundle already inlined, duplicating
            # side-effects like ``customElements.define("hoot-fixture", …)``.
            # Key the self-bridge under the alias too, so the satellite reads
            # from ``odoo.loader.modules`` instead of re-fetching.
            for asset in asset_bundle.native_modules:
                header = _parse_odoo_module_header(asset.raw_content)
                if not (header and header["alias"]):
                    continue
                alias = header["alias"]
                current = prod_import_map.get(alias, "")
                # When the alias already resolves to a bridge URL
                # (``/web/assets/esm/bridges/`` prefix), leave it: the existing
                # shim reads the same ``odoo.loader.modules`` entry, so
                # clobbering only churns the URL without changing semantics.
                if current.startswith("/web/assets/esm/bridges/"):
                    continue
                shim = self_bridges.get(asset.module_path)
                if shim:
                    prod_import_map[alias] = shim

        # ALWAYS emit the importmap here. This runs inside the ormcached
        # ``_get_native_module_nodes_cached`` (key ``(bundle, assets_params)``,
        # request-independent), so consulting ``request._esm_import_map_rendered``
        # would bake one page's composition into the cache — a bundle first seen
        # as a page's SECOND ESM bundle would cache WITHOUT its importmap. The
        # per-request dedup happens outside the cache, in the dispatcher's
        # ``_dedup_request_import_map``.
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
        # Bootstrap odoo.loader — must be a class instance (not a plain object):
        # Hoot's ModuleSetLoader does ``extends loader.constructor`` and calls
        # parent methods (startModule/addJob) via the prototype chain.
        shim_js = self._build_loader_shim_js()
        pre.append(("script", {"text": shim_js}))
        # Inline the template-registration code at the END of the bundle's
        # module body so ``registerTemplate`` runs synchronously right after
        # ``registerNativeModules``, before the microtask queue drains. Source
        # files often do ``whenReady(() => mount(...))`` at top level, queuing a
        # microtask during evaluation; a SEPARATE ``<script type="module">``
        # would let the browser drain that microtask between the two modules,
        # mounting with no templates registered ("Missing template: <name>").
        # ``use_import=False`` makes the templates read
        # ``odoo.loader.modules.get(...)`` rather than ``import``, reusing the
        # instance just registered (no double-evaluation, singleton preserved).
        esm_tpl = asset_bundle.generate_esm_template_bundle(
            use_import=False,
        )
        bundle_code = self._combine_bundle_with_templates(esbuild_code, esm_tpl)
        # Persist and reference by URL even on read-only request cursors:
        # ``_save_esm_attachment`` routes its INSERT through a dedicated
        # read-write registry cursor, so replica renders no longer inline the
        # multi-MB bundle. Inlining remains the degradation path when no
        # writable cursor exists at all (read-only test cursor, primary down).
        esm_url = None
        try:
            esm_url = self._save_esm_attachment(
                bundle,
                bundle_code,
                metafile=esbuild_result.metafile,
                sourcemap=esbuild_result.sourcemap,
            )
        except ReadOnlySqlTransaction:
            # Raised cleanly (no SQL executed) when no writable cursor exists —
            # the transaction is intact, so inlining is safe. A real save error
            # propagates instead of being papered over with a degraded page.
            log_event(
                _attach_log,
                logging.WARNING,
                "save_failed_inline",
                bundle=bundle,
                readonly=bool(self.env.cr.readonly),
                declined=raise_on_decline,
            )
            if raise_on_decline:
                # The ormcached caller: decline instead of inlining so the
                # degraded multi-MB inline nodes never enter the process
                # cache (the uncached re-run inlines or falls back).
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
        # Companion templates attachment for IMPORT_MAP_INCLUDES satellites:
        # they need the templates as a separately-resolvable specifier in the
        # parent's import map (so test files importing ``@web/core/templates``
        # resolve to the parent's instance). Skipped when no satellite needs them.
        _has_satellites = bool(
            esm_registry().import_map_includes.get(bundle),
        )
        if esm_tpl and _has_satellites:
            # Same persist-or-inline ladder as the main bundle above.
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
                    # Same never-cache-the-inline rule as the main bundle.
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
        # URL-vs-data-URI breakdown, logged to correlate browser-side "import
        # map rule was removed" warnings with the mix of targets rendered.
        # Bridge URIs are now attachment URLs (``/web/assets/esm/bridges/``),
        # formerly ``data:`` — the split stays so any ``data:`` count flags an
        # unmigrated caller.
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
        """Build debug-mode (individual-file) native-ESM nodes.

        Emits the import map, the loader shim, the bridge module (eager imports
        + Hoot ``loadAndStart``) and the template module — all inline, no esbuild
        and no attachment writes. Bridge shims are resolved to direct URLs
        because debug mode has no esbuild bundle to populate
        ``odoo.loader.modules``. Reached for ``?debug=assets`` and as the
        uncached fallback when production esbuild declines.

        :return: ``(pre_nodes, post_nodes)`` flanking the legacy bundle
        """
        # ── Debug mode: individual files + import map ──
        pre_nodes = []
        post_nodes = []
        import_map = dict(native_data["import_map"])

        # Add @odoo/* externals to the import map so native modules
        # can resolve bare specifiers externalized by esbuild.
        import_map.update(self._ODOO_EXTERNAL_LIBS)

        # Pre-register dynamic ESM bundle specifiers. ALL children are built
        # per-file here (debug_assets=True) — even on a fallback render — since
        # there is no esbuild output to load them from.
        lazy_bundles = self._get_dynamic_child_bundles(
            bundle, assets_params, debug_assets=True
        )
        self._merge_child_import_maps(import_map, lazy_bundles)

        # Merge include import maps (test bundles that skip esbuild), debug
        # bridge policy: bridge specifiers resolve to direct URLs, since shims
        # read ``odoo.loader.modules`` which nothing populates in debug mode.
        self._merge_include_import_maps(
            bundle,
            import_map,
            assets_params,
            debug_assets=debug_assets,
            resolve_bridges=True,
        )

        # Include NEW import-map specifiers from secondary satellite
        # bundles (first-wins — see the helper's docstring).
        self._merge_secondary_import_maps(
            bundle,
            import_map,
            assets_params,
            debug_assets=debug_assets,
        )

        # Instance-sharing bridge: shims re-exporting from
        # ``odoo.loader.modules`` so dynamic bundles share the parent's
        # singletons. Combine main + dynamic native modules so every needed
        # export is in a single shim per specifier.
        all_native_specifiers = set(native_data["import_map"])
        combined_native_modules = list(asset_bundle.native_modules)
        for lazy_ab in lazy_bundles:
            all_native_specifiers.update(m.module_path for m in lazy_ab.native_modules)
            combined_native_modules.extend(lazy_ab.native_modules)

        # Discover the whole graph's bridge specifier KEYS (main + dynamic) and
        # resolve each to a direct URL — same debug policy as above (shims can't
        # work without an esbuild bundle). ``drop_unresolved=False``: a
        # pre-existing shim for an unresolvable specifier is left alone.
        discovered, _ext_seen = asset_bundle._bridges._discover_bridge_specifiers(
            all_native_specifiers,
            set(self._ODOO_EXTERNAL_LIBS),
            modules=combined_native_modules,
        )
        resolved_bridges = self._resolve_bridge_specifiers_to_urls(
            import_map,
            discovered,
            drop_unresolved=False,
        )

        # Has a previous ESM bundle on this page already rendered an import map?
        # Only ONE is allowed per document. READ-only here: the flag is written
        # solely by the dispatcher's ``_dedup_request_import_map``. This method
        # used to set it too, which made that pass strip the importmap this call
        # had just emitted — serving ``?debug=assets`` and fallback pages with no
        # import map. It still SHAPES this branch's output (importmap/shim
        # emission, ``use_import``) so a later bundle won't re-emit the first's.
        _req = request or None
        _already_has_esm = _req and getattr(
            _req,
            "_esm_import_map_rendered",
            False,
        )

        # 1. Import map — MUST come before any <script type="module">
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

        # 3. Modulepreload hints for faster loading (skip in debug mode
        #    to reduce noise and allow individual file debugging)
        if not debug_assets:
            pre_nodes.extend(
                ("link", {"rel": "modulepreload", "href": url})
                for url in native_data["preload_urls"]
            )

        # Register ALL native modules in the legacy loader so require() works
        # for same-bundle legacy modules and lazy bundles (e.g.
        # web_tour.automatic). @odoo/owl is included explicitly so legacy
        # odoo.define() code (e.g. spreadsheet) can require() it — OWL loads via
        # import map, not as a native module.
        bridge_specifiers = sorted(
            set(native_data["import_map"]) | set(self._ODOO_EXTERNAL_LIBS)
        )
        if bridge_specifiers and not _already_has_esm:
            shim_js = self._build_loader_shim_js()
            pre_nodes.append(("script", {"text": shim_js}))

        # Bridge code is ALWAYS generated (even when the import map and
        # shim were already rendered by a previous bundle on this page).
        # This registers native modules and test factories for Hoot.
        if bridge_specifiers:
            bridge_code = ""

            # Tour files (``/tests/tours/*.js``) auto-register into
            # ``web_tour.tours`` on load, so they must be eagerly imported.
            # Hoot tests (``.test.js``, or ``/tests/`` outside ``/tours/``) are
            # wrapped in ``describe()`` and load through Hoot's runner instead.
            hoot_specs = [
                s for s in bridge_specifiers if self._is_hoot_test_specifier(s)
            ]
            non_hoot_specs = [s for s in bridge_specifiers if s not in hoot_specs]

            if not _already_has_esm:
                # Primary bundle: eagerly import and register every
                # non-Hoot module (sources + tour files) under their
                # specifiers in ``odoo.loader.modules``.
                import_lines = []
                register_entries = []
                for i, specifier in enumerate(non_hoot_specs):
                    var = f"__m{i}"
                    # json.dumps quotes/escapes the specifier so a quote or
                    # backslash in the module path can't break out of the
                    # string literal (same as the registration keys below).
                    import_lines.append(
                        f"import * as {var} from {json_mod.dumps(specifier)};"
                    )
                    register_entries.append(f"  {json_mod.dumps(specifier)}: {var}")
                bridge_code = "\n".join(import_lines) + "\n"
                bridge_code += "odoo.loader.registerNativeModules({\n"
                bridge_code += ",\n".join(register_entries)
                bridge_code += "\n});\n"
            else:
                # Secondary bundle: source modules are already loaded by the
                # primary's esbuild output, so skip generic eager imports. Tour
                # files are test-bundle-specific and unknown to the parent —
                # eager-import them here for their registration side-effect.
                tour_specs = [s for s in non_hoot_specs if "/tours/" in s]
                if tour_specs:
                    bridge_code = (
                        "\n".join(f"import {json_mod.dumps(s)};" for s in tour_specs)
                        + "\n"
                    )

            # Import all Hoot test files eagerly via start.hoot's
            # loadAndStart(), following Hoot's canonical import-all → start().
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

        # ESM template module — the NATIVE branch (no esbuild). Every module,
        # including ``@web/core/templates``, loads as a native ES module through
        # the import map, NOT via esbuild's ``registerNativeModules``. So
        # templates MUST use native ``import`` (``use_import=True``): the
        # ``get()`` form returned ``undefined`` for secondary bundles once a
        # request flagged ``_already_has_esm`` (under HttpCase / ``test_js``),
        # failing the whole JS suite pre-boot. ``get()`` is valid only in the
        # esbuild branch (``_esm_prod_nodes``), which pins ``use_import=False``.
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
        """Save esbuild output as an ir.attachment, return its URL.

        ``metafile`` / ``sourcemap`` are the build's sibling artifacts, passed
        only by the main-bundle save (``None`` for ``.templates.esm.js``).

        The URL is **content-addressable**: the hash is derived from the bundle
        bytes, so byte-identical builds share one attachment and a source edit
        that doesn't change the output (whitespace, esbuild-normalized imports)
        doesn't invalidate the browser cache.

        Superseded rows are NOT deleted here — deletion is deferred to
        ``IrAttachment._gc_esm_assets`` after a grace window; this method only
        triggers the assets-cache clear that version propagation requires.
        """
        IrAttachment = self.env["ir.attachment"]
        content_bytes = content.encode("utf-8")
        # 16 hex chars = 64 bits of entropy, far beyond the birthday
        # bound for a single tenant's bundle corpus (~50 bundles).
        content_hash = hashlib.sha256(content_bytes).hexdigest()[:16]
        url = f"/web/assets/esm/{content_hash}/{bundle}.esm.js"

        existing = IrAttachment.sudo().search(
            [("url", "=", url), ("public", "=", True)],
            limit=1,
        )
        if existing:
            # Hit rate should be ~100% after warm-up — logged at DEBUG
            # because it's the common case, not newsworthy.
            log_event(
                _attach_log,
                logging.DEBUG,
                "reuse",
                bundle=bundle,
                url=url,
                bytes=len(content_bytes),
            )
            # Touch the row so the asset GC sees a REUSED artifact as live: a
            # reverted deploy (A → B → A) reuses A's older row, and without the
            # touch ``_gc_esm_assets``'s newest-per-name heuristic would sweep A
            # while cached nodes still embed A's URL (hard 404, no rebuild).
            # Best-effort out-of-band commit, as with the create below.
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
        # Count stale versions across the legacy per-version and
        # content-addressable URL layouts, plus their ``.meta.json`` /
        # ``.esm.js.map`` siblings (else old hashes leave orphan rows wasting
        # filestore). ``=like`` patterns over-match (``_`` is a wildcard, ``%``
        # spans segments), but that's contained: only the COUNT drives the cache
        # clear + log; deletion is deferred to ``_gc_esm_assets``, so a false
        # positive costs one extra cache clear, never a deleted live row.
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
            # Deletion is DEFERRED to ``_gc_esm_assets``: superseded rows must
            # keep serving in-flight pages, stale CDN HTML and workers that
            # haven't processed the cache-clear yet (the ESM serve path has no
            # rebuild, so a deleted row is a hard 404). The cache clear must
            # still fire so every worker re-renders nodes with the new URL.
            self.env.registry.clear_cache("assets")
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

        # Sibling metafile attachment (esbuild bundle analysis). ``metafile`` is
        # supplied only by the main-bundle save (``None`` for
        # ``.templates.esm.js``), so the sidecar is skipped there.
        if metafile and url.endswith(".esm.js"):
            meta_url = url[: -len(".esm.js")] + ".meta.json"
            self._save_esm_sidecar(
                bundle,
                meta_url,
                metafile.encode("utf-8"),
                mimetype="application/json",
            )
        # Source-map sidecar — esbuild's ``--sourcemap=linked`` appends
        # ``//# sourceMappingURL=<basename>.map`` to the bundle, so the browser
        # fetches this URL only when devtools is open. The ``.esm.js`` →
        # ``.esm.js.map`` name matches esbuild's default, so the directive
        # resolves relative to the bundle URL.
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
        """Persist a sibling file next to an ESM bundle attachment.

        Used for metafiles and source-map sidecars; extensible to other
        analysis side-channels.  Idempotent: reuses the existing
        attachment when the URL already maps to one.
        """
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
            # Same GC-liveness touch as the main-bundle reuse branch:
            # a reused sidecar must not look older than a superseded
            # sibling of the same name.
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
        """Persist ESM asset attachments through a dedicated RW cursor.

        Nodes embedding these URLs enter the process ``assets`` ormcache when
        the cached method returns, and ormcache never rolls back. Creating rows
        on the REQUEST cursor meant a later failure in the same request rolled
        the attachment back while the cache kept serving its URL — a hard 404,
        since the ESM serve route has no rebuild. A dedicated cursor that commits
        independently closes that window and lets read-only replica renders
        persist without the http layer's read-write retry.

        Test mode — and any render with no HTTP request (preload, pregeneration,
        cron, CLI) — writes on the current cursor instead: rollback-safety is
        moot with no request transaction, and a second REAL ``registry.cursor()``
        would deadlock against ir_attachment locks this thread already holds. It
        also matters that a plain TransactionCase's ``registry.cursor()`` opens a
        REAL cursor whose out-of-band commit leaks rows past the test rollback.

        Attachments are content-addressed and idempotent, so the out-of-band
        commit is safe; a concurrent worker just makes a harmless duplicate.

        :param vals_list: ``ir.attachment`` create values. If the RW cursor is
            unreachable (primary down), falls back to the request cursor and lets
            errors propagate so a URL is never cached without a surviving row.
        :param touch_ids: attachment ids whose ``write_date`` is bumped so
            ``_gc_esm_assets`` keeps a REUSED row live. Best-effort: a failed
            touch only shortens GC protection.
        """
        if _module.current_test or not request:
            if vals_list:
                if self.env.cr.readonly:
                    # Raise WITHOUT running the doomed INSERT: a failed statement
                    # aborts the transaction and poisons the rest of the render.
                    # Same type the INSERT would raise, so callers that propagate
                    # it (the /web/bundle path) still get the http rw retry.
                    raise ReadOnlySqlTransaction(
                        "cannot persist ESM attachments on a read-only test cursor"
                    )
                self.env["ir.attachment"].with_user(SUPERUSER_ID).create(vals_list)
            # The touch is best-effort everywhere — skip it on readonly
            # test cursors (pre-refactor reuse did no write at all).
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
                # Touch-only call: losing the write_date bump is harmless
                # (GC protection just isn't extended this render).
                log_event(
                    _attach_log,
                    logging.DEBUG,
                    "touch_failed",
                    bundle=bundle,
                    ids=len(touch_ids),
                )
                return
            # No writable registry cursor reachable — degrade to the request
            # cursor. A failure here propagates: better to fail the render than
            # cache a URL whose row may not survive the transaction.
            _logger.warning(
                "ESM attachment escalation to a read-write cursor failed; "
                "creating on the request cursor",
                exc_info=True,
            )
            if self.env.cr.readonly:
                # Raise without executing the doomed INSERT (see the
                # test-mode branch above): keeps the request transaction
                # usable for callers that catch this and inline instead.
                raise ReadOnlySqlTransaction(
                    "no writable cursor reachable for ESM attachments"
                ) from None
            self.env["ir.attachment"].with_user(SUPERUSER_ID).create(vals_list)

    def _get_asset_link_urls(self, bundle: str, debug: str = "") -> list[str]:
        asset_nodes = self._get_asset_nodes(bundle, js=False, debug=debug)
        return [node[1]["href"] for node in asset_nodes if node[0] == "link"]

    def _pregenerate_assets_bundles(self) -> list[str]:
        """Pregenerate all assets that may be used in web pages to speed up first loading.
        Mainly useful for tests.

        Looks for all ``t-call-assets`` in views to build the minimal set of
        bundles. Only generates assets without extras, ignoring rtl.
        """
        _logger.runbot("Pregenerating assets bundles")

        js_bundles, css_bundles = self._get_bundles_to_pregenerate()

        links = []
        start = time.time()
        for bundle in sorted(js_bundles):
            links += self._get_asset_bundle(bundle, css=False, js=True).js()
        _logger.info("JS Assets bundles generated in %s seconds", time.time() - start)
        start = time.time()
        for bundle in sorted(css_bundles):
            links += self._get_asset_bundle(bundle, css=True, js=False).css()
        _logger.info("CSS Assets bundles generated in %s seconds", time.time() - start)
        return links

    def _get_bundles_to_pregenerate(self) -> tuple[set[str], set[str]]:
        """Return the (js_bundles, css_bundles) name sets to pregenerate."""

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
