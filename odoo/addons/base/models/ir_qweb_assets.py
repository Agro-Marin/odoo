"""ir.qweb asset & native-ESM pipeline.

Extracted from ``ir_qweb.py``: everything reachable from the ``t-call-assets``
directive — legacy JS/CSS bundle link generation, native-ESM/esbuild build
orchestration (circuit breaker, advisory build lock, import-map assembly) and
content-addressed attachment persistence. These methods extend ``ir.qweb`` via
``_inherit`` and carry no coupling to the template compiler, so the ~2.3k-line
asset subsystem can evolve and be reasoned about independently of QWeb
rendering. ``_compile_directive_call_assets`` (in ``ir_qweb.py``) is the only
templating entry point; it calls ``self._get_asset_nodes`` on the merged model.
"""

import hashlib
import json as json_mod  # stdlib json; odoo.tools.json is not needed here
import logging
import time
from collections.abc import Sequence
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
from odoo.tools.assets.esm_registry import esm_registry
from odoo.tools.misc import file_path, str2bool

from odoo.addons.base.models.assetsbundle import AssetsBundle, BundleFileSpec

_logger = logging.getLogger(__name__)

# Structured asset-pipeline loggers (odoo.assets.{category}).  Admin can
# trace the full bundle path with ``--log-handler=odoo.assets:DEBUG`` or
# isolate one subsystem via the child names.
_esm_log = get_asset_logger("esm")
_attach_log = get_asset_logger("attach")
_fallback_log = get_asset_logger("fallback")
_loader_log = get_asset_logger("loader")
_lock_log = get_asset_logger("lock")


class _EsmFallbackError(Exception):
    """Internal control-flow signal: a production native-ESM render declined
    (esbuild circuit open, lock contention, or build failure). Raised by
    ``IrQweb._get_native_module_nodes_cached`` so the ``assets`` ormcache never
    stores the degraded debug-mode fallback (ormcache does not cache
    exceptions); caught by ``_get_native_module_nodes``, which then renders the
    fallback uncached.
    """


class IrQweb(models.AbstractModel):
    _inherit = "ir.qweb"

    def _get_asset_nodes(
        self,
        bundle: str,
        css: bool = True,
        js: bool = True,
        debug: str | bool = False,
        defer_load: bool = False,
        lazy_load: bool = False,
        media: str | None = None,
        autoprefix: bool = False,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Generates asset nodes.
        If debug=assets, the assets will be regenerated when a file which composes them has been modified.
        Else, the assets will be generated only once and then stored in cache.

        When native ESM modules are present (``@odoo-module native``), the output
        includes an import map and a bridge ``<script type="module">`` that
        pre-registers them before the legacy bundle executes.  The legacy bundle
        gets ``defer`` to guarantee correct execution order.
        """
        media = (css and media) or None
        links = self._get_asset_links(
            bundle, css=css, js=js, debug=debug, autoprefix=autoprefix
        )

        # Check for native ESM modules in this bundle
        pre_nodes = []
        post_nodes = []
        has_native = False
        if js:
            pre_nodes, post_nodes = self._get_native_module_nodes(
                bundle,
                debug=debug,
            )
            # ``has_native`` indicates that native-ESM rendering happened.
            # Either pre_nodes (importmap, shim, modulepreload) or
            # post_nodes (bridge, templates) being non-empty means the
            # bundle's ESM contribution has to be returned alongside
            # the legacy links — secondary bundles (whose import map and
            # shim are skipped because the parent already rendered them)
            # may have only post_nodes, and dropping them silently would
            # leave their bridge code unrendered in the final HTML.
            has_native = bool(pre_nodes) or bool(post_nodes)

        # Classic scripts (Bootstrap, Luxon, etc.) must NOT be deferred when
        # native ESM modules are present — they set UMD globals that native
        # modules access at module scope.  Non-deferred scripts execute during
        # parsing, BEFORE any <script type="module"> scripts, guaranteeing
        # that globals like `luxon`, `Tooltip`, `Dropdown` are available.
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

    def _get_asset_links(
        self,
        bundle: str,
        css: bool = True,
        js: bool = True,
        debug: str | bool | None = None,
        autoprefix: bool = False,
    ) -> list[str]:
        """Generates asset links (URLs), not nodes.
        If debug=assets, the assets will be regenerated when a file which composes them has been modified.
        Else, the assets will be generated only once and then stored in cache.
        """
        rtl = (
            self.env["res.lang"]
            .sudo()
            ._get_data(code=(self.env.lang or self.env.user.lang))
            .direction
            == "rtl"
        )
        assets_params = self.env["ir.asset"]._get_asset_params()  # website_id
        debug_assets = debug and "assets" in debug

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
        # in non-xml-debug mode we want assets to be cached forever, and the admin can force a cache clear
        # by restarting the server after updating the source code (or using the "Clear server cache" in debug tools)
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
    ) -> list[tuple[str, dict[str, Any]]]:
        # ``_link_to_node`` returns None for a path whose extension is not a
        # known script/style/template type (e.g. an external URL with a query
        # string). Drop those: downstream consumers (the generated
        # ``t-call-assets`` loop) unpack ``(tagName, attrs)`` directly and would
        # raise TypeError on a None. Log dropped paths so a misclassified asset
        # is visible instead of silently missing from the page.
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
    ) -> tuple[str, dict[str, Any]] | None:
        ext = path.rsplit(".", maxsplit=1)[-1] if path else "js"
        is_js = ext in SCRIPT_EXTENSIONS
        is_xml = ext in TEMPLATE_EXTENSIONS
        is_css = ext in STYLE_EXTENSIONS

        if is_js:
            attributes = {
                "type": "text/javascript",
            }

            if defer_load:
                # Note that "lazy_load" will lead to "defer" being added in JS,
                # not here, otherwise this is not W3C valid (defer is probably
                # not even needed there anyways). See LAZY_LOAD_DEFER.
                attributes["defer"] = "defer"
            if path:
                if lazy_load:
                    attributes["data-src"] = path
                else:
                    attributes["src"] = path

            # NOTE: bundle scripts used to carry ``onerror="__odooAssetError=1"``
            # — a vestige of a removed reload mechanism; no runtime reader
            # existed.  Load-failure self-healing now lives in the module
            # loader shim (``module_loader.js`` captures script error events
            # for ``/web/assets/`` URLs and triggers one guarded reload).
            return ("script", attributes)

        if is_css:
            attributes = {
                "type": f"text/{ext}",  # we don't really expect to have anything else than pure css here
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
    # Import-map entries for esbuild-externalized libraries.  The
    # canonical definition lives in ``odoo.libs.constants`` so that
    # ``assetsbundle`` can read it without importing this module (the
    # two used to form an import cycle patched with a deferred import);
    # the class alias keeps the ``self._ODOO_EXTERNAL_LIBS`` read sites.
    _ODOO_EXTERNAL_LIBS = ODOO_EXTERNAL_LIBS

    @staticmethod
    def _specifier_to_static_url(spec: str) -> str | None:
        """Resolve an ``@addon/path`` specifier to a served static URL.

        Follows Odoo's bundling convention:
          * ``@web/core/registry``       → ``/web/static/src/core/registry.js``
          * ``@web/../lib/hoot/hoot``    → ``/web/static/lib/hoot/hoot.js``
          * ``@web/../tests/foo``        → ``/web/static/tests/foo.js``

        Returns ``None`` for specifiers that don't match the convention
        (e.g. bare ``luxon``, ``@odoo/owl``) — those belong in
        ``_ODOO_EXTERNAL_LIBS`` or esbuild aliases instead.
        """
        if not spec.startswith("@"):
            return None
        rest = spec[1:]
        slash = rest.find("/")
        if slash <= 0:
            return None
        addon = rest[:slash]
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

        Previously inlined in the ``/web/bundle`` controller and recomputed
        per request: bundle construction, bridge discovery (regex over every
        module source) and the XML template parse ran on every runtime
        ``loadBundle()`` call. The template attachment is content-addressed,
        so repeat computes reuse the same URL; the newest row per name
        survives ``_gc_esm_assets``, keeping cached payload URLs valid.
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

    # Cache for the minified loader shim. Populated lazily by
    # _build_loader_shim_js() from the static source file on disk, and
    # only recomputed if the file's mtime changes (dev-mode hot reload).
    _loader_shim_cache: tuple[float, str] | None = None

    # ─────────────────────────────────────────────────────────────────
    # esbuild circuit breaker (per-process, per-bundle)
    # ─────────────────────────────────────────────────────────────────
    #
    # Each failure of ``esbuild_native_bundle()`` opens a cooldown window
    # during which we skip esbuild and serve the debug-mode fallback.
    # Protects against retry-storms when esbuild is broken (missing binary,
    # syntax error in source, permissions problem) — without a breaker,
    # every request would pay the subprocess startup + failure cost.
    #
    # State survives per worker process and is cleared on restart.  The
    # admin override below (``web.esbuild.force_fallback_bundles``
    # system parameter) provides the same effect without waiting for a
    # failure, e.g. to force debug-mode for a bundle after an incident.
    # Keyed by ``(db_name, bundle)`` via ``_esbuild_cooldown_key``. This is a
    # single process-global class attribute shared by every registry in the
    # worker (plain class attributes are inherited, not copied per registry —
    # see orm/registration.py), so it MUST be namespaced by database; otherwise
    # an esbuild failure for a bundle in one tenant opens the breaker for the
    # same bundle name in every other tenant.
    _esbuild_cooldowns: dict[tuple[str, str], tuple[float, str, int]] = {}
    # Hardcoded defaults — overridable via ir.config_parameter without a
    # code change.  Names mirror the parameter keys (see
    # ``_get_esbuild_setting``).  Keep the class attributes so existing
    # tests that read them directly (``self.IrQweb._ESBUILD_COOLDOWN_S``)
    # continue to pass with default semantics.
    _ESBUILD_COOLDOWN_S: float = 60.0  # after 1st failure
    _ESBUILD_EXTENDED_COOLDOWN_S: float = 600.0  # after 2nd consecutive failure

    # ─────────────────────────────────────────────────────────────────
    # Tunable settings (ir.config_parameter)
    # ─────────────────────────────────────────────────────────────────
    #
    # Surface every hardcoded esbuild timing as a system parameter so
    # ops can tune post-incident without redeploying.  Parameter keys
    # follow the ``web.esbuild.<name>`` convention for consistency with
    # the existing ``web.esbuild.force_fallback_bundles`` admin toggle.
    #
    # Defaults match the hardcoded values so existing behavior is
    # unchanged when no parameter is set.
    _ESBUILD_SETTING_KEYS: frozenset = frozenset(
        {
            "cooldown_s",
            "extended_cooldown_s",
            "lock_retries",
            "lock_retry_sleep_s",
            "timeout_s",
            "target",
            # Source-map mode: ``""`` (off — default), ``"linked"``
            # (RECOMMENDED for production debugging: sidecar ``.js.map``
            # attachment + a ``//# sourceMappingURL=`` directive in the
            # bundle — the only mode devtools and the error-dialog stack
            # annotator (``@web/core/errors/stack_frames``) can discover),
            # ``"external"`` (sidecar without the directive — for maps
            # consumed out-of-band, e.g. a crash reporter), or ``"inline"``
            # (base64 in the bundle, no sidecar but ~2x download).
            # Operators turn this on without redeploying; the ``.map``
            # sidecar is served immutable by ``content_esm_assets``.
            "source_maps",
        }
    )

    def _get_esbuild_setting(self, name: str, default, cast=None):
        """Return the value of ``web.esbuild.<name>``, falling back to
        ``default`` if unset / unparseable.

        Reads through ``ir.config_parameter`` (itself cached on the
        ``ormcache`` layer, so repeated lookups in the same transaction
        are cheap).  ``cast`` is applied to a non-None raw value; on
        cast failure the default is used and a DEBUG log records why so
        operators can spot a typo in their parameter.
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
        # get_param() returns ``False`` (not ``None``) when the key is
        # unset — a naive ``raw is None`` check would miss the common
        # case and poison callers with ``float(False) == 0.0``.  Use
        # Python truthiness: any legitimate string value is truthy
        # (``"0.0"`` is truthy even though its cast is 0.0).
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

        Read from ``web.esbuild.force_fallback_bundles`` (comma-separated,
        ir.config_parameter — its ``get_param`` is itself ormcached). Consulted
        both by the production esbuild path and by ``_get_native_module_nodes``,
        which bypasses the node cache for these so a freshly added override
        silences a bundle without a server restart or cache clear.
        """
        forced_raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("web.esbuild.force_fallback_bundles", "")
        )
        return {s.strip() for s in forced_raw.split(",") if s.strip()}

    def _esbuild_cooldown_key(self, bundle: str) -> tuple[str, str]:
        """Database-scoped key for ``_esbuild_cooldowns``.

        The cooldown dict is a single process-global class attribute shared by
        every registry in the worker, so an unscoped (bundle-only) key would let
        an esbuild failure in one database open the breaker for the same bundle
        name in every other database. Namespacing by ``cr.dbname`` isolates
        tenants while keeping the shared-dict design.
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

    # ─────────────────────────────────────────────────────────────────
    # esbuild concurrency lock (advisory, transaction-scoped)
    # ─────────────────────────────────────────────────────────────────
    #
    # Rationale: two requests cold-starting the same bundle would each
    # spawn esbuild (3s on ``web.assets_web``) and both would try to
    # ``INSERT`` the same attachment, with only one winning.  The
    # duplicate-CPU path is visible as back-to-back ``event=bundled``
    # lines in the log.  A Postgres transaction-scoped advisory lock
    # serializes the expensive path: the first request acquires the
    # lock and runs esbuild; concurrent requests see the lock held,
    # degrade to the debug-mode branch for that single render (the
    # user's page loads, just with un-minified nodes), and the lock
    # auto-releases when the first request's transaction commits.
    #
    # We intentionally use ``pg_try_advisory_xact_lock`` (non-blocking)
    # with one short retry rather than a blocking acquire so we don't
    # tie up web workers behind a slow esbuild on a deployment where
    # reverse-proxy timeouts are shorter than esbuild startup.

    _ESBUILD_LOCK_RETRIES: int = 1
    _ESBUILD_LOCK_RETRY_SLEEP_S: float = 0.2

    def _esbuild_try_acquire_lock(self, bundle: str) -> bool:
        """Try to take the per-bundle advisory lock.

        Returns True if acquired; the lock is transaction-scoped and
        releases automatically when the current cursor's transaction
        commits or rolls back (no manual release needed).

        Returns False after ``retries + 1`` attempts, in which case the
        caller should fall back to the debug-mode path.  ``retries`` and
        the inter-attempt sleep are read from
        ``web.esbuild.lock_retries`` / ``lock_retry_sleep_s`` (defaults
        come from ``_ESBUILD_LOCK_RETRIES`` / ``_ESBUILD_LOCK_RETRY_SLEEP_S``).
        """
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
            self.env.cr.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                (key,),
            )
            got = self.env.cr.fetchone()[0]
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

        Hoot wraps each test file inside a ``describe()`` suite, so eager
        import would bypass that wrapper.  Hoot tests are loaded through
        ``start.hoot``'s ``loadAndStart()`` instead.  Tour files
        (``/static/tests/tours/*.js``) and their specifiers
        (``@addon/../tests/tours/...``) are NOT Hoot tests — they
        register themselves into the ``web_tour.tours`` registry on
        module load and must be eagerly imported.
        """
        if "/tours/" in specifier:
            return False
        return (
            "/../tests/" in specifier or ".test" in specifier or "/tests/" in specifier
        )

    @classmethod
    def _build_loader_shim_js(cls) -> str:
        """Return a self-executing JS snippet that bootstraps ``odoo.loader``.

        The source lives in ``addons/web/static/src/module_loader.js`` so
        that it can be edited with regular JS tooling (linters, unit tests,
        syntax highlighting).  This method reads and minifies it once,
        caching the result keyed by the file's mtime so that local edits
        during development are picked up automatically.

        The loader MUST be a class instance (not a plain object) because
        Hoot-based tests subclass it via
        ``Object.getPrototypeOf(odoo.loader.constructor)`` and instantiate
        the subclass for isolated module graphs.  A plain-object shim
        would make the subclass extend ``Object`` and break that pattern.
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
    ) -> tuple[
        list[tuple[str, dict[str, Any]]],
        list[tuple[str, dict[str, Any]]],
    ]:
        """Cached production native-ESM nodes (non-debug, read-write only).

        Runs the full assembly via ``_get_native_module_nodes_impl`` and caches
        the resulting nodes, so warm renders skip bundle construction, the
        esbuild subprocess, and the template parse entirely. A production
        attempt that declines (esbuild circuit open, lock contention, or build
        failure) raises ``_EsmFallbackError`` instead of returning the degraded
        debug rendering — ormcache never stores an exception, so the fallback
        is never cached.
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
        debug: str | bool = False,
        assets_params: dict[str, Any] | None = None,
    ) -> tuple[
        list[tuple[str, dict[str, Any]]],
        list[tuple[str, dict[str, Any]]],
    ]:
        """Dispatch native-ESM node generation through the assets cache.

        Production (non-debug, read-write) renders go through the ormcached
        ``_get_native_module_nodes_cached``. ``?debug=assets``, read-only
        cursors (which inline the bundle rather than persist an attachment),
        and the esbuild-declined fallback all render uncached via
        ``_get_native_module_nodes_impl``.
        """
        debug_assets = debug and "assets" in debug
        if assets_params is None:
            assets_params = self.env["ir.asset"]._get_asset_params()
        if (
            not debug_assets
            and not self.env.cr.readonly
            and bundle not in self._esbuild_forced_fallback_bundles()
        ):
            try:
                pre, post = self._get_native_module_nodes_cached(
                    bundle, assets_params=assets_params
                )
            except _EsmFallbackError:
                # Production esbuild declined (circuit open, admin override,
                # lock contention, or build failure) → render the uncached
                # debug fallback. The re-run re-evaluates those conditions
                # (cheap; no second subprocess once the circuit has opened) and
                # constructs the asset_bundle the debug branch needs.
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
        pre_nodes: list[tuple[str, dict[str, Any]]],
    ) -> list[tuple[str, dict[str, Any]]]:
        """Keep at most one ``<script type="importmap">`` per request.

        The browser evaluates every importmap on the page and logs "An
        import map rule for specifier '<spec>' was removed, as it
        conflicted with an existing rule" for each duplicate key, so a
        page composing several ESM bundles (``t-call-assets`` twice, the
        unit-test page stacking setup + tests bundles) must render the
        map of the FIRST bundle only.

        Runs in the dispatcher — outside ``_get_native_module_nodes_cached``
        — because the decision is request-scoped while the cache key is
        ``(bundle, assets_params)``: filtering inside the cached impl baked
        one request's page composition into every later render (nodes
        cached without their importmap serve broken pages forever).

        Returns a filtered COPY when dropping the node; cached lists are
        shared by reference and must never be mutated.
        """
        if not request:
            return pre_nodes

        def _is_import_map(node: tuple[str, dict[str, Any]]) -> bool:
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
        debug: str | bool = False,
        assets_params: dict[str, Any] | None = None,
        _raise_on_decline: bool = False,
    ) -> tuple[
        list[tuple[str, dict[str, Any]]],
        list[tuple[str, dict[str, Any]]],
    ]:
        """Generate import map, OWL pre-load, and bridge nodes for native ESM.

        :param str bundle: name of the asset bundle to render
        :param debug: debug flags (``'assets'`` rebuilds without cache)
        :param assets_params: parameters forwarded to ``ir.asset``
        :return: 2-tuple ``(pre_nodes, post_nodes)`` flanking the legacy bundle
        :rtype: tuple[list, list]
        """
        # ``pre_nodes`` go BEFORE the legacy bundle:
        #   1. ``<script src="owl.js">`` — non-deferred, sets ``window.owl``
        #   2. ``<script type="importmap">`` with specifier → URL mappings
        #   3. ``<link rel="modulepreload">`` hints (production only)
        # ``post_nodes`` go AFTER the legacy bundle:
        #   4. ``<script type="module">`` bridge — imports native modules
        #      and registers them in ``odoo.loader.modules`` via
        #      ``registerNativeModules()``.  Runs after the bundle because
        #      both ``defer`` and ``type="module"`` share the same deferred
        #      execution queue in document order.
        debug_assets = debug and "assets" in debug
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
        # Single minified <script type="module"> replaces 600+ individual
        # files + import map + modulepreload hints + bridge script.
        #
        # Two pre-checks short-circuit the expensive path (subprocess +
        # attachment insert) straight to the debug-mode fallback:
        #
        #   • Admin override via ``web.esbuild.force_fallback_bundles``
        #     (comma-separated bundle names in ir.config_parameter) —
        #     operators can silence a broken bundle without a restart.
        #   • Circuit breaker state — set by ``_esbuild_circuit_record_failure``
        #     on prior failures; blocks retries until the cooldown expires.
        #
        # Both cases fall through to the existing debug-mode branch,
        # which serves individual ES modules + import map.  Rendering is
        # slower and uglier (no minification, modulepreload hints still
        # emitted) but functional.
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
                    bundle, asset_bundle, esbuild_result, assets_params, child_bundles
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

        Honors the admin force-fallback override, the per-bundle circuit
        breaker and the advisory build lock, and records circuit
        success/failure.

        :return: ``(esbuild_result, child_bundles)`` — the esbuild build
            (its ``.code`` is ``""`` when the build is skipped or fails;
            the caller then degrades to the debug-mode nodes, and
            ``.metafile`` / ``.sourcemap`` carry the sibling artifacts) and
            the dynamic-child ``AssetsBundle`` objects constructed for the
            spec scan, for ``_esm_prod_nodes`` to reuse instead of
            re-constructing all of them (empty when the build was skipped
            — the prod-nodes path is not reached in that case).
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
            # Silent skip during cooldown — the circuit-open event
            # was logged once when the breaker tripped, so don't
            # spam the log with a line per request.
            log_event(
                _fallback_log,
                logging.DEBUG,
                "circuit_blocked",
                bundle=bundle,
                reason=circuit_reason,
            )
        elif not self._esbuild_try_acquire_lock(bundle):
            # Another request is mid-build; degrade THIS render to
            # debug-mode so the user's page loads without waiting.
            # Emitted at INFO because contention is interesting for
            # capacity planning (frequent misses → consider
            # pre-generation via ``_pregenerate_assets_bundles``).
            log_event(
                _fallback_log,
                logging.INFO,
                "lock_contention",
                bundle=bundle,
            )
        else:
            # Pre-compute dynamic children's native-module specs so
            # the parent's esbuild call can externalise them (see
            # the docstring on ``esbuild_native_bundle``).  Done
            # here because qweb already has access to ``_get_asset_bundle``
            # and the cost is paid by the import-map merge below
            # anyway — handing the same data to esbuild costs only
            # a set comprehension.
            _child_specs: set[str] = set()
            for _child_name in esm_registry().dynamic_children.get(bundle, ()):
                _child_ab = self._get_asset_bundle(
                    _child_name,
                    js=True,
                    css=False,
                    debug_assets=(_child_name in esm_registry().dynamic_bundle_names),
                    assets_params=assets_params,
                )
                child_bundles.append(_child_ab)
                _child_specs.update(a.module_path for a in _child_ab.native_modules)
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
                )
                self._esbuild_circuit_record_success(bundle)
            except Exception as e:
                # Distinct ``odoo.assets.fallback`` event so alerting
                # on prod→debug degradation doesn't require
                # string-matching on a free-form message.  The
                # degraded rendering is handled by falling through
                # into the debug-mode branch below.
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

    def _esm_prod_nodes(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        esbuild_result: EsbuildResult,
        assets_params: dict[str, Any] | None,
        child_bundles: list[AssetsBundle] | None = None,
    ) -> tuple[
        list[tuple[str, dict[str, Any]]],
        list[tuple[str, dict[str, Any]]],
    ]:
        """Assemble production native-ESM nodes from a successful esbuild build.

        Builds the merged import map (externals, dynamic bundles, includes,
        secondary satellites, self-bridges and alias overrides), emits the
        importmap + loader shim, inlines template registration into the
        bundle, and persists (or inlines, in read-only txns) the module and
        templates attachments.

        :param EsbuildResult esbuild_result: the successful build — its
            ``.code`` is the bundle source; ``.metafile`` / ``.sourcemap``
            are persisted as sibling attachments alongside the module.
        :param list child_bundles: dynamic-child ``AssetsBundle`` objects
            already constructed by ``_esm_run_esbuild`` (same construction
            parameters as the fallback below); ``None`` constructs them.
        :return: ``(pre, post)`` flanking the legacy bundle
        """
        esbuild_code = esbuild_result.code
        pre = []
        post = []
        # Import map: @odoo/* externals + dynamic bundle specifiers
        # so runtime import() can resolve them.
        prod_import_map = dict(self._ODOO_EXTERNAL_LIBS)

        # Collect dynamic ESM bundles and build bridges for
        # their @web/... dependencies (data: URI shims reading
        # from odoo.loader.modules — same instance, no dups).
        # The child bundles were already constructed once by
        # ``_esm_run_esbuild`` for the spec scan; reuse them here
        # instead of re-running every child's ``__init__`` (15
        # constructions saved per cold ``web.assets_web`` render).
        if child_bundles is None:
            child_bundles = [
                self._get_asset_bundle(
                    lazy_name,
                    js=True,
                    css=False,
                    debug_assets=lazy_name in esm_registry().dynamic_bundle_names,
                    assets_params=assets_params,
                )
                for lazy_name in esm_registry().dynamic_children.get(bundle, ())
            ]
        dynamic_bundles = []
        for lazy_ab in child_bundles:
            is_dynamic = lazy_ab.name in esm_registry().dynamic_bundle_names
            # Only ``import_map`` is consumed here — the combined
            # dynamic-child bridge is built separately below — so skip
            # the per-child bridge build + attachment persistence.
            lazy_data = lazy_ab.get_native_module_data(with_bridges=False)
            prod_import_map.update(lazy_data["import_map"])
            if is_dynamic:
                dynamic_bundles.append(lazy_ab)

        # Build instance-sharing bridges for dynamic bundles.
        # Combine ALL dynamic bundles' native_modules so that
        # bridges export the union of all needed names (e.g.
        # spreadsheet needs `groupBy` from arrays, website
        # needs `shallowEqual` — both must be in one bridge).
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

        # Include import map entries from associated bundles
        # (e.g. test bundles that skip esbuild and rely on the
        # parent's import map for bare-specifier resolution).
        include_names = esm_registry().import_map_includes.get(bundle, ())
        for include_name in include_names:
            # debug_assets=False here → reuse the ormcached native
            # module data (keyed by bundle + assets_params) instead of
            # rebuilding the bundle and its bridge on every render.
            include_data = self._get_native_module_data_cached(
                include_name,
                assets_params=assets_params,
            )
            prod_import_map.update(include_data["import_map"])
            # The include's bridges cover specifiers its OWN files import
            # from elsewhere — mostly this parent's modules (absent from
            # the map, added here) but also DYNAMIC-CHILD specifiers,
            # which already have a direct URL from the child merge above.
            # Those must keep the direct URL: the parent's esbuild output
            # externalizes dynamic-child specs and imports them through
            # the map at page-load time, when ``odoo.loader.modules`` is
            # not yet populated — a shim there yields undefined exports.
            # The direct URL also preserves singleton identity for the
            # satellite (browsers singleton ES modules by URL).  Same
            # first-wins rule the secondary-includes loop below applies.
            for spec, shim_url in include_data.get("bridge_import_map", {}).items():
                prod_import_map.setdefault(spec, shim_url)

        # Include NEW import-map specifiers from secondary
        # satellite bundles (e.g. ``web.assets_tests`` loaded
        # via the conditional template).  Only specifiers not
        # already in the parent are added so we don't override
        # the parent's resolved URLs with the satellite's
        # bridge shims (which would create circular shim
        # references during the parent's bridge initialisation).
        secondary_names = esm_registry().secondary_import_map_includes.get(
            bundle,
            [],
        )
        for sec_name in secondary_names:
            sec_ab = self._get_asset_bundle(
                sec_name,
                js=True,
                css=False,
                debug_assets=False,
                assets_params=assets_params,
            )
            # Only ``import_map`` is consumed; skip the bridge build.
            sec_data = sec_ab.get_native_module_data(with_bridges=False)
            for spec, url in sec_data["import_map"].items():
                prod_import_map.setdefault(spec, url)

        # When satellites exist, they load individual source
        # files from this bundle.  Those files may import bare
        # specifiers (``@ai/vad_audio_recorder``) that are only
        # resolved internally inside the esbuild bundle — the
        # browser sees the raw source and needs an import-map
        # entry.  Emit self-bridges that read from
        # ``odoo.loader.modules`` (populated by the esbuild
        # bundle's ``registerNativeModules`` call).
        #
        # IMPORTANT: bridges OVERRIDE any URL mapping a satellite
        # may have published for the same specifier.  Reason:
        # cross-bundle module sharing requires the satellite's
        # ``import { GraphModel } from "@web/views/graph/graph_model"``
        # to land on the parent's already-registered singleton
        # (loaded inline inside the esbuild bundle), NOT to fetch
        # ``/web/static/src/views/graph/graph_model.js`` and
        # re-evaluate it as a second module instance.  Satellites
        # legitimately expose URLs for their OWN test files; for
        # production files transitively included by satellite-
        # contributed sub-bundles (e.g. ``spreadsheet/__manifest__``
        # adds ``web/static/src/views/graph/graph_model.js`` to
        # ``spreadsheet.o_spreadsheet``, which is then included
        # into ``web.assets_unit_tests`` via the test-bundle
        # contribution) those URLs would otherwise cause every
        # ``patchWithCleanup(GraphModel.prototype, …)`` in a test
        # to patch a parallel-universe class that the production
        # controller never sees.  The bridge resolution preserves
        # singleton identity, which is also what HOOT's mocks
        # ``patchWithCleanup`` rely on.
        if include_names:
            self_bridges = asset_bundle._bridges._build_parent_self_bridge()
            prod_import_map.update(self_bridges)
            # ── Alias override ──────────────────────────────
            # Modules that declare an ``alias=@odoo/xyz``
            # header (hoot.js / hoot-dom.js / hoot-mock.js)
            # are present in ``_ODOO_EXTERNAL_LIBS`` with a
            # DIRECT URL pointing at the vendored ESM file.
            # That direct URL causes satellites' bare imports
            # (``import "@odoo/hoot"``) to fetch the file and
            # RE-EVALUATE it — the same file that the esbuild
            # bundle already inlined, duplicating side-effects
            # like ``customElements.define("hoot-fixture", …)``
            # in ``fixture.js``.  Reuse the self-bridge for
            # the asset's native module_path and key it under
            # the alias too, so the satellite reads from
            # ``odoo.loader.modules`` instead of re-fetching.
            from odoo.tools.assets.esm_graph import (
                _parse_odoo_module_header as _parse_hdr,
            )

            for asset in asset_bundle.native_modules:
                header = _parse_hdr(asset.raw_content)
                if not (header and header["alias"]):
                    continue
                alias = header["alias"]
                current = prod_import_map.get(alias, "")
                # ``/web/assets/esm/bridges/`` is the bridge
                # attachment prefix (see
                # ``BridgeShimManager._persist_bridge_shims``).  When
                # the alias already resolves to a bridge URL,
                # leave it alone — the existing shim reads from
                # the same ``odoo.loader.modules`` entry we'd
                # overwrite it with, so clobbering only churns
                # the attachment URL without changing semantics.
                if current.startswith("/web/assets/esm/bridges/"):
                    continue
                shim = self_bridges.get(asset.module_path)
                if shim:
                    prod_import_map[alias] = shim

        # ALWAYS emit the importmap node here.  Only ONE
        # ``<script type="importmap">`` may be evaluated per
        # document, but this method runs inside the ormcached
        # ``_get_native_module_nodes_cached`` whose key is
        # ``(bundle, assets_params)`` — request-independent.
        # Consulting ``request._esm_import_map_rendered`` here
        # (as this method used to) baked one request's page
        # composition into the process cache: a bundle first
        # rendered as the SECOND ESM bundle of a page was cached
        # WITHOUT its importmap and served broken to every later
        # page that rendered it alone.  The per-request dedup now
        # happens outside the cache, in the dispatcher
        # (``_get_native_module_nodes`` →
        # ``_dedup_request_import_map``); the debug branch keeps
        # its own flag handling because it is never cached and
        # the flag also shapes its generated bridge code.
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
        # Bootstrap odoo.loader — must be a class instance (not
        # a plain object) because Hoot's ModuleSetLoader does
        # ``extends loader.constructor`` and calls parent methods
        # like startModule/addJob via the prototype chain.
        shim_js = self._build_loader_shim_js()
        pre.append(("script", {"text": shim_js}))
        # Inline the templates-registration code at the END of
        # the bundle's module body so ``registerTemplate(...)``
        # calls run SYNCHRONOUSLY right after
        # ``registerNativeModules({...})`` — and crucially
        # *before* the microtask queue drains.
        #
        # Why this matters: the bundle's source files often do
        # ``whenReady(() => mount(MyComponent, ...))`` at module
        # top level.  ``whenReady`` resolves immediately when
        # the document is already parsed (which it is by the
        # time deferred module scripts execute), so the mount
        # callback is queued as a microtask during this
        # bundle's evaluation.  If templates were emitted as a
        # SEPARATE ``<script type="module">`` after this one,
        # the browser would drain microtasks BETWEEN the two
        # modules — the mount would run with no templates
        # registered, throwing "Missing template: <name>".
        # Inlining keeps both into one module body so the
        # microtask drain (and therefore any whenReady mount)
        # happens AFTER both registerNativeModules and
        # registerTemplate have run.
        #
        # ``use_import=False`` makes the templates code reach
        # for ``odoo.loader.modules.get("@web/core/templates")``
        # rather than ``import``, so it picks up the SAME
        # module instance just registered above (no double-
        # evaluation, singleton identity preserved).
        esm_tpl = asset_bundle.generate_esm_template_bundle(
            use_import=False,
        )
        bundle_code = esbuild_code
        if esm_tpl:
            # When source maps are on, esbuild emits a
            # ``//# sourceMappingURL=<name>.map`` directive at
            # the END of its output so devtools knows where to
            # fetch the map from.  Browsers read the LAST
            # sourceMappingURL comment in the file — if we
            # append the templates body after the directive,
            # the directive becomes invisible to devtools and
            # source maps silently stop working.  Strip it
            # before appending templates, then re-emit it at
            # the very end so the combined bundle still has a
            # trailing directive.
            esb_base = esbuild_code
            sm_directive = ""
            _tail_idx = esbuild_code.rfind("//# sourceMappingURL=")
            if _tail_idx != -1 and "\n" not in esbuild_code[_tail_idx:].rstrip("\n"):
                # Match spans from the directive marker to the
                # end of file (possibly followed by a single
                # trailing newline).  esbuild always emits the
                # directive as the LAST non-empty line.
                sm_directive = esbuild_code[_tail_idx:].rstrip("\n")
                esb_base = esbuild_code[:_tail_idx].rstrip("\n") + "\n"
            bundle_code = (
                esb_base
                + "/* ── Inlined templates registration ── */\n"
                + esm_tpl
                + ("\n" + sm_directive + "\n" if sm_directive else "")
            )
        # Persist and reference by URL even on read-only request cursors:
        # ``_save_esm_attachment`` routes its INSERT through a dedicated
        # read-write registry cursor (a primary cursor even on a
        # replica-routed render — see ``_persist_esm_attachment_rows``),
        # so replica renders no longer inline the multi-MB bundle into
        # every response.  Inlining remains as the degradation path for
        # contexts with no writable cursor at all (read-only test
        # cursors, primary down) — functionally identical, just heavier.
        esm_url = None
        try:
            esm_url = self._save_esm_attachment(
                bundle,
                bundle_code,
                metafile=esbuild_result.metafile,
                sourcemap=esbuild_result.sourcemap,
            )
        except ReadOnlySqlTransaction:
            # Raised cleanly (no SQL executed) by
            # ``_persist_esm_attachment_rows`` when no writable cursor
            # exists — the transaction is intact, inlining is safe.
            # Anything else propagates as before: a real save error must
            # not be papered over with a silently degraded page.
            log_event(
                _attach_log,
                logging.WARNING,
                "save_failed_inline",
                bundle=bundle,
                readonly=bool(self.env.cr.readonly),
            )
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
        # Companion templates attachment for IMPORT_MAP_INCLUDES
        # satellites: bundles in IMPORT_MAP_INCLUDES need the
        # templates as a separately-resolvable specifier in
        # their parent's import map (so test files that import
        # ``@web/core/templates`` resolve to the parent's
        # registered instance).  Skipped when the templates
        # are already inlined into the main bundle and no
        # satellite needs them.
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
                )
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
        # URL-vs-data-URI breakdown helps correlate browser-side
        # "import map rule was removed" warnings with the exact
        # mix of specifier targets the server rendered.  A
        # client-side seed from this map should eliminate all
        # "conflicting rule" warnings for lazy bundles.
        # Bridge URIs used to be ``data:text/javascript,...``
        # (pre-refactor); now they're attachment URLs at
        # ``/web/assets/esm/bridges/<hash>.js``.  The
        # diagnostic still splits the two so historical log
        # comparisons make sense — any ``data:`` counts after
        # the refactor would indicate a caller hasn't migrated.
        _n_bridges = sum(
            1
            for v in prod_import_map.values()
            if v.startswith("/web/assets/esm/bridges/")
        )
        _n_data_uri = sum(1 for v in prod_import_map.values() if v.startswith("data:"))
        _n_real_url = len(prod_import_map) - _n_bridges - _n_data_uri
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
    ) -> tuple[
        list[tuple[str, dict[str, Any]]],
        list[tuple[str, dict[str, Any]]],
    ]:
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

        # Pre-register dynamic ESM bundle specifiers in the import map
        # so that runtime import() (after loadBundle) can resolve them.
        # Only URLs are added — modules are NOT eagerly loaded.

        lazy_bundles = []
        for lazy_name in esm_registry().dynamic_children.get(bundle, ()):
            lazy_ab = self._get_asset_bundle(
                lazy_name,
                js=True,
                css=False,
                debug_assets=True,
                assets_params=assets_params,
            )
            # Only ``import_map`` is consumed (no bridge used here); skip the
            # discarded per-child bridge build.
            lazy_data = lazy_ab.get_native_module_data(with_bridges=False)
            import_map.update(lazy_data["import_map"])
            lazy_bundles.append(lazy_ab)

        # Include import map entries from associated bundles (e.g. test
        # bundles that skip esbuild and rely on the parent's import map).
        for include_name in esm_registry().import_map_includes.get(bundle, ()):
            include_ab = self._get_asset_bundle(
                include_name,
                js=True,
                css=False,
                debug_assets=debug_assets,
                assets_params=assets_params,
            )
            include_data = include_ab.get_native_module_data(with_bridges=False)
            import_map.update(include_data["import_map"])
            # The include's modules import cross-bundle specifiers the map
            # must resolve, but bridge SHIMS read ``odoo.loader.modules`` —
            # non-functional in debug mode (same reason as the conversion
            # loop below).  Merging them verbatim shadowed the parent's
            # direct URLs and poisoned the whole module graph: verified
            # 2026-06-10, the hoot runner failed all ~1311 tests under
            # ``?debug=assets`` (vs 8 genuine failures in production mode)
            # with every shim-routed export ``undefined``.  Discover the
            # specifier KEYS only — building and persisting the shim values
            # (~340 attachment writes per debug render) was pure waste once
            # every entry gets converted anyway — and resolve each to a
            # direct URL: keep an existing direct mapping, else derive the
            # static URL, else drop for a clean "module not found".  The
            # exclusion set is the include's own import-map keys, i.e. the
            # exact ``native_specifiers`` the bridge build would have used.
            discovered, _ext_seen = include_ab._bridges._discover_bridge_specifiers(
                set(include_data["import_map"]),
                set(self._ODOO_EXTERNAL_LIBS),
            )
            for _spec in discovered:
                _current = import_map.get(_spec)
                if _current and not _current.startswith(
                    ("/web/assets/esm/bridges/", "data:")
                ):
                    continue
                _resolved = self._ODOO_EXTERNAL_LIBS.get(
                    _spec
                ) or self._specifier_to_static_url(_spec)
                if _resolved:
                    import_map[_spec] = _resolved
                elif _current:
                    del import_map[_spec]

        # Include NEW import-map specifiers from secondary satellite
        # bundles (e.g. ``web.assets_tests`` loaded via the conditional
        # template).  Only specifiers not already in the parent are
        # added so we don't override the parent's resolved URLs with
        # the satellite's bridge shims.
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

        # Instance-sharing bridge: data: URI shims that re-export from
        # ``odoo.loader.modules`` so dynamic bundles share the parent
        # bundle's singleton instances (e.g. same registry).
        # When dynamic bundles exist, rebuild the bridge with COMBINED
        # native modules (main + dynamic) so all needed exports are
        # included in a single shim per specifier.
        all_native_specifiers = set(native_data["import_map"])
        combined_native_modules = list(asset_bundle.native_modules)
        for lazy_ab in lazy_bundles:
            all_native_specifiers.update(m.module_path for m in lazy_ab.native_modules)
            combined_native_modules.extend(lazy_ab.native_modules)

        # In debug mode, bridge shims (modules reading from
        # odoo.loader.modules) CANNOT work: there is no esbuild
        # bundle to pre-populate the modules map, so _m is undefined
        # and the shim crashes.  Discover the specifier KEYS only —
        # building and persisting shim attachments here was pure waste
        # (same reasoning as the include-path conversion above) — and
        # resolve each to a direct URL:
        # 1. If the specifier already has a direct URL in import_map
        #    (from native_data or _ODOO_EXTERNAL_LIBS), keep it —
        #    the existing URL is already correct.
        # 2. Otherwise, resolve the @addon/... specifier back to a
        #    served static URL.  This is always safe in debug:
        #    browsers singleton ES modules by URL, so every bundle
        #    that imports the same specifier shares the exact same
        #    module instance.
        # 3. If the specifier can't be resolved (unusual), leave it
        #    out — the browser gets a clean "module not found"
        #    instead of the confusing undefined-property crash.
        discovered, _ext_seen = asset_bundle._bridges._discover_bridge_specifiers(
            all_native_specifiers,
            set(self._ODOO_EXTERNAL_LIBS),
            modules=combined_native_modules,
        )
        resolved_bridges = {}
        for _spec in discovered:
            _current = import_map.get(_spec)
            # A "direct URL" here means a real source/asset URL pointing
            # at a file NOT generated by ``_persist_bridge_shims``
            # (i.e. anything outside ``/web/assets/esm/bridges/``).  If
            # the spec already resolves to such a URL, a bridge is
            # redundant — the direct URL hits the source bytes, a
            # shim would only proxy through ``odoo.loader.modules``.
            if (
                _current
                and not _current.startswith("/web/assets/esm/bridges/")
                and not _current.startswith("data:")
            ):
                continue
            # No direct URL — prefer the canonical mapping in
            # _ODOO_EXTERNAL_LIBS (deep-import aliases like
            # @odoo/hoot-dom-helpers-events resolve to a vendored
            # path that the ``@addon/...`` → ``/addon/static/src/...``
            # convention can't compute), then fall back to the
            # convention-derived static URL.
            _resolved = self._ODOO_EXTERNAL_LIBS.get(
                _spec
            ) or self._specifier_to_static_url(_spec)
            if _resolved:
                resolved_bridges[_spec] = _resolved
        import_map.update(resolved_bridges)

        # Check if a previous ESM bundle on this page already rendered
        # an import map (e.g. the setup bundle on the test page).
        # Only ONE import map per document is allowed by the spec.
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
            if _req:
                _req._esm_import_map_rendered = True

        # 3. Modulepreload hints for faster loading (skip in debug mode
        #    to reduce noise and allow individual file debugging)
        if not debug_assets:
            pre_nodes.extend(
                ("link", {"rel": "modulepreload", "href": url})
                for url in native_data["preload_urls"]
            )

        # Register ALL native modules in the legacy loader so that
        # require() works for both same-bundle legacy modules and
        # dynamically-loaded lazy bundles (e.g. web_tour.automatic).
        # Include @odoo/owl explicitly so legacy odoo.define() code
        # (e.g. spreadsheet) can require() it — OWL is loaded via
        # import map, not as a native module in the bundle.
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

            # Tour files (``/tests/tours/*.js``) auto-register into the
            # legacy ``web_tour.tours`` registry at module load — they
            # must be eagerly imported so the registration side-effect
            # runs.  Hoot tests (``.test.js`` files, or anything in
            # ``/tests/`` outside ``/tours/``) are wrapped in
            # ``describe()`` blocks and must be loaded through Hoot's
            # runner instead, so they are excluded from eager imports.
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
                    # backslash in a (developer-controlled) module path
                    # cannot break out of the string literal — same
                    # treatment the registration keys below already get.
                    import_lines.append(
                        f"import * as {var} from {json_mod.dumps(specifier)};"
                    )
                    register_entries.append(f"  {json_mod.dumps(specifier)}: {var}")
                bridge_code = "\n".join(import_lines) + "\n"
                bridge_code += "odoo.loader.registerNativeModules({\n"
                bridge_code += ",\n".join(register_entries)
                bridge_code += "\n});\n"
            else:
                # Secondary bundle: source modules are already loaded
                # by the primary bundle's esbuild output, so skip
                # generic eager imports.  Tour files, however, are
                # specific to test bundles and the parent does not
                # know about them — eager-import them here for their
                # registration side-effect.
                tour_specs = [s for s in non_hoot_specs if "/tours/" in s]
                if tour_specs:
                    bridge_code = (
                        "\n".join(f"import {json_mod.dumps(s)};" for s in tour_specs)
                        + "\n"
                    )

            # ESM native test loading: import all Hoot test files
            # eagerly via start.hoot's loadAndStart(), following Hoot's
            # canonical pattern (import all → start()).  No factories
            # needed.
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

        # ESM template module — inline in debug mode.
        # Secondary bundles use use_import=False so that templates
        # access @web/core/templates via odoo.loader.modules.get()
        # instead of import — the data: URI bridge may not export all
        # names (e.g. checkPrimaryTemplateParents).
        esm_tpl = asset_bundle.generate_esm_template_bundle(
            use_import=not _already_has_esm,
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

        _n_bridges = sum(
            1 for v in import_map.values() if v.startswith("/web/assets/esm/bridges/")
        )
        _n_data_uri = sum(1 for v in import_map.values() if v.startswith("data:"))
        _n_real_url = len(import_map) - _n_bridges - _n_data_uri
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

        ``metafile`` / ``sourcemap`` are the esbuild build's sibling
        artifacts, passed only by the main-bundle save; they are ``None``
        for the separately-generated ``.templates.esm.js`` saves, which
        carry no metafile or source map.

        The URL is **content-addressable**: the hash segment is derived
        from the bundle bytes themselves, not from the source files'
        mtimes.  Two builds that produce byte-identical output share one
        attachment, and editing a source file in a way that doesn't
        change the emitted bundle (whitespace, reordered imports that
        esbuild normalizes) does NOT invalidate the browser cache.

        The ``/web/assets/esm/`` path prefix distinguishes content-hashed
        ESM bundles from the legacy ``/web/assets/{version}/`` layout
        used for concatenated ``.min.js`` bundles; the stale-version
        glob below matches both. Superseded rows are NOT deleted here —
        deletion is deferred to ``IrAttachment._gc_esm_assets`` after a
        grace window; this method only triggers the assets-cache clear
        that version propagation requires.
        """
        IrAttachment = self.env["ir.attachment"]
        content_bytes = content.encode("utf-8")
        # 16 hex chars = 64 bits of entropy, far beyond the birthday
        # bound for a single tenant's bundle corpus (~50 bundles).
        content_hash = hashlib.sha256(content_bytes).hexdigest()[:16]
        url = f"/web/assets/esm/{content_hash}/{bundle}.esm.js"

        # Check if attachment already exists
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
            # Touch the row so the asset GC sees a REUSED artifact as
            # live.  Content-addressing means a reverted deploy (content
            # A → B → back to A) reuses A's original row, whose
            # ``write_date`` (and id) are older than B's — without the
            # touch, ``_gc_esm_assets``'s newest-per-name heuristic
            # treats B as the live version and sweeps A while every
            # cached node still embeds A's URL (hard 404; the ESM serve
            # path has no rebuild).  Best-effort, out-of-band commit —
            # same rationale as the create below.
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
        # Clean old versions across both the legacy per-version URL
        # layout (``/web/assets/<ver>/<bundle>.esm.js``) and the
        # content-addressable layout (``/web/assets/esm/<hash>/…``).
        # ``=like`` patterns are approximate: ``_`` is a single-char
        # wildcard (bundle names are full of literal underscores) and the
        # leading ``%`` can span path segments, so the sweep CAN over-match
        # sibling bundle names.  Contained by design — matches are only
        # deferred to ``_gc_esm_assets``, which re-derives liveness itself;
        # the cost of a false positive is an extra cache clear, never a
        # deleted live row.
        # Sweep matching ``.meta.json`` and ``.esm.js.map`` siblings
        # too — otherwise old hashes leave orphan rows that pile up
        # in ``ir.attachment`` and waste filestore bytes (one stale
        # 1MB metafile or 3MB sourcemap per rebuild adds up fast on
        # busy dev DBs).
        stale = IrAttachment.sudo().search(
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
        if stale:
            # Deletion is DEFERRED to IrAttachment._gc_esm_assets: the
            # superseded rows must keep serving in-flight pages, stale CDN
            # HTML and workers that have not yet processed the cache-clear
            # signal (the ESM serve path has no on-the-fly rebuild, so a
            # deleted row is a hard 404 there). The cache clear itself —
            # previously a side effect of stale.unlink() — must still
            # happen so every worker re-renders its nodes with the new
            # version's URL.
            self.env.registry.clear_cache("assets")
            log_event(
                _attach_log,
                logging.INFO,
                "stale_deferred",
                bundle=bundle,
                count=len(stale),
            )
        log_event(
            _attach_log,
            logging.INFO,
            "save",
            bundle=bundle,
            url=url,
            bytes=len(content_bytes),
        )

        # Sibling metafile attachment (esbuild bundle analysis). ``metafile``
        # is supplied only by the main-bundle save; it is ``None`` for the
        # ``.templates.esm.js`` saves (a different code path with no metafile),
        # so the sidecar is skipped there.
        if metafile and url.endswith(".esm.js"):
            meta_url = url[: -len(".esm.js")] + ".meta.json"
            self._save_esm_sidecar(
                bundle,
                meta_url,
                metafile.encode("utf-8"),
                mimetype="application/json",
            )
        # Source-map sidecar — esbuild's ``--sourcemap=external`` mode
        # appends ``//# sourceMappingURL=<basename>.map`` to the
        # bundle, so the browser fetches this attachment URL ONLY when
        # devtools is open (zero runtime cost otherwise).  Same
        # ``.esm.js`` -> ``.esm.js.map`` filename relationship esbuild
        # picks by default, so the comment in the bundle resolves
        # correctly relative to the bundle URL.
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

        Used for metafiles today; extensible to source maps or other
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

        The rendered nodes embedding these attachment URLs are stored in
        the process-memory ``assets`` ormcache the moment the enclosing
        cached method returns — and ormcache entries never roll back with
        the transaction.  Creating the rows on the REQUEST cursor meant a
        later failure in the same request (access error in another
        template section, serialization abort) rolled the attachment back
        while the cache kept serving its URL: a hard 404 with no rebuild
        path, since the ESM serve route deliberately has none (see
        ``ir.attachment.unlink``).  A dedicated cursor that commits
        independently of the render closes that window — the same
        invariant, and the same escalation pattern,
        ``BridgeShimManager._persist_bridges_via_rw_cursor`` applies to
        bridge shims.  It also lets read-only replica renders (e.g. the
        ``/web/bundle`` lazy-load route) persist without relying on the
        http layer's whole-request read-write retry.

        Test mode writes on the request cursor instead (the
        pre-refactor behavior): rollback-safety is meaningless inside a
        test transaction, and while an HttpCase's registry cursor is a
        TestCursor sharing the test transaction, a plain
        TransactionCase's ``registry.cursor()`` opens a REAL cursor
        whose out-of-band commit is invisible to the test's snapshot
        and leaks rows past the test rollback.

        The attachments are content-addressed and idempotent, so the
        out-of-band commit is safe; a concurrent worker doing the same
        produces a harmless duplicate row (served via ``limit 1``,
        cleaned by the GC).

        :param vals_list: ``ir.attachment`` create values.  When the RW
            cursor is unreachable (primary down), falls back to creating
            on the request cursor — the pre-refactor behavior — and lets
            any error propagate so a URL is never returned (and cached)
            without a surviving row.
        :param touch_ids: existing attachment ids whose ``write_date``
            must be bumped so ``_gc_esm_assets`` keeps treating a REUSED
            content-addressed row as live (content reverts re-use old
            rows; see the reuse branches of the two savers).  Best-effort:
            a failed touch only shortens GC protection, never the render.
        """
        if _module.current_test:
            if vals_list:
                if self.env.cr.readonly:
                    # Raise WITHOUT executing the doomed INSERT: a failed
                    # statement aborts the transaction and would poison
                    # every later query of the render.  Same type the
                    # INSERT itself would raise, so callers that let it
                    # propagate (the /web/bundle payload path) still get
                    # the http layer's read-write retry.
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
            # No writable registry cursor reachable — degrade to the
            # request cursor (pre-refactor path).  A failure here
            # propagates: better to fail the render than to cache a URL
            # whose row may not survive the transaction.
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

    def _get_asset_link_urls(self, bundle: str, debug: str | bool = False) -> list[str]:
        asset_nodes = self._get_asset_nodes(bundle, js=False, debug=debug)
        return [node[1]["href"] for node in asset_nodes if node[0] == "link"]

    def _pregenerate_assets_bundles(self) -> list[str]:
        """Pregenerate all assets that may be used in web pages to speed up first loading.
        Mainly useful for tests.

        Looks for all ``t-call-assets`` in views to build the minimal set of
        bundles. Only generates assets without extras, ignoring rtl.
        """
        _logger.runbot("Pregenerating assets bundles")

        js_bundles, css_bundles = self._get_bundles_to_pregenarate()

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

    def _get_bundles_to_pregenarate(self) -> tuple[set[str], set[str]]:
        """
        Returns the list of bundles to pregenerate.
        """

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
