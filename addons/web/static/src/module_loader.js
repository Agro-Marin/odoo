/**
 * Odoo module loader bootstrap (post-ESM).
 *
 * This file is NOT included in any asset bundle.  It is read from disk
 * by ``ir.qweb._build_loader_shim_js()`` at asset-node-generation time,
 * minified, and emitted as an inline ``<script>`` tag BEFORE any
 * ``<script type="module">`` runs.  The inline execution ensures
 * ``window.odoo.loader`` exists when the esbuild bundle calls
 * ``odoo.loader.registerNativeModules({...})`` at the top of its
 * evaluation.
 *
 * Why a static file instead of a Python string:
 *   • Real syntax highlighting, linting, and editor tooling.
 *   • Unit-testable in isolation via hoot (module_loader.test.js).
 *   • Single source of truth: the class name, field names, and method
 *     signatures match the ambient TypeScript declaration in
 *     ``@types/odoo.d.ts``; grep works.
 *
 * The class MUST remain a real ES class (not a plain object).  Tests
 * recover it from the live instance via ``odoo.loader.constructor`` and
 * re-instantiate it (``module_loader.test.js``); a plain object would
 * have ``Object`` as its constructor and break that recovery.  Keeping
 * a class shell also leaves the door open for Hoot to subclass the
 * loader for isolated test-module graphs without changing this file.
 *
 * ──────────────────────────────────────────────────────────────────
 * Historical note
 * ──────────────────────────────────────────────────────────────────
 *
 * Pre-2026 this file was a 450-line AMD module loader with
 * ``define()``, dependency-graph resolution, cycle detection, lazy
 * jobs, and an error reporter with a visual banner.  It was the
 * runtime scaffolding that booted every legacy
 * ``/** @odoo-module *\/ odoo.define(...)`` file.
 *
 * The 2026-03 → 2026-04 fork-wide ESM migration ended that era.  Every
 * JS source in ``addons/`` now carries ``/** @odoo-module native *\/``;
 * dependency resolution is handled by esbuild at bundle time and by
 * the browser's native module graph at load time.  The esbuild
 * generated entry calls exactly one loader method —
 * ``registerNativeModules({spec: namespace, ...})`` — so the loader's
 * shrunken job is:
 *
 *   1. Provide a shared ``Map`` of module specifier → namespace so
 *      sibling bundles (e.g. ``website.assets_inside_builder_iframe``)
 *      resolve ``@web/core/registry`` to the SAME object as the parent
 *      bundle via bridge modules (server-built attachments under
 *      ``/web/assets/esm/bridges/``, or runtime ``data:`` bridges
 *      built by ``@web/core/module_bridge``).  This preserves
 *      registry singleton identity across bundle boundaries.
 *   2. Remain idempotent: if two bundles on the same page both inline
 *      the shim, the second one must no-op so all bundles share the
 *      same Map.
 *   3. Guard the singleton invariant.  The one thing that breaks
 *      (1) is a specifier re-bound to a DIFFERENT namespace object —
 *      a duplicated module in the bundle graph would split the
 *      ``@web/core/registry`` singleton silently.  The loader detects
 *      this by identity and surfaces it on ``bus`` (event ``rebind``)
 *      plus the debug-gated asset log, without ever failing the
 *      bundle's top-level evaluation.
 *   4. Self-heal stale asset URLs.  A content-addressed bundle URL
 *      swept by the attachment GC 404s on a stale cached page;
 *      ``handleAssetLoadError`` reacts with ONE rate-limited reload
 *      so the page re-renders with fresh URLs (see its docstring).
 *
 * Everything else the old loader did is provably unused across the
 * entire fork (core, enterprise, design-themes, agromarin).  The
 * remaining surface is exercised end-to-end by
 * ``static/tests/modules/module_loader.test.js``.
 */
(function () {
    "use strict";

    // Idempotent bootstrap: if a loader is already installed (e.g. by a
    // parallel bundle on the same page) skip re-installing so every
    // bundle shares the SAME ``odoo.loader.modules`` Map and therefore
    // the SAME module instances (critical for registry singleton
    // identity across bundle boundaries).
    const o = (globalThis.odoo ??= {});
    if (o.loader) {
        return;
    }

    // ──────────────────────────────────────────────────────────────
    // Inlined asset logger
    // ──────────────────────────────────────────────────────────────
    //
    // The shim runs BEFORE any ESM module, so it cannot ``import``
    // from ``@web/core/utils/asset_log``.  Duplicate the activation
    // logic inline — any change here should mirror the Python side
    // (``odoo.libs.asset_log``) and JS side
    // (``@web/core/utils/asset_log``) so operators see a consistent
    // opt-in surface across the stack.
    //
    // Activation (any of):
    //   • ``?debug=assets`` (or any debug mode containing "assets")
    //   • ``localStorage.setItem("debug.assets", "1")``
    //   • ``window.__ODOO_ASSET_TRACE__ = true``
    function _loaderDebug(...parts) {
        try {
            const o = globalThis.odoo;
            const on =
                (o && typeof o.debug === "string" && o.debug.includes("assets")) ||
                globalThis.localStorage?.getItem?.("debug.assets") ||
                globalThis.__ODOO_ASSET_TRACE__;
            if (on) {
                console.debug("[asset.loader]", ...parts);
            }
        } catch {
            // Sandboxed iframe (no localStorage access): silently disabled.
        }
    }

    class OdooModuleLoader {
        /**
         * Shared Map of module specifier → module namespace object.
         *
         * Populated by ``registerNativeModules`` from the esbuild
         * bundle's auto-generated top-level entry.  Sibling bundles
         * (lazy children declared in the manifests'
         * ``esm.dynamic_children``, cross-doc iframes loaded via
         * ``@web/core/assets.loadESMBundle``) look up this Map through
         * bridge modules constructed in Python
         * (``odoo.tools.assets.esm_bridges.BridgeShimManager``:
         * attachment URLs under ``/web/assets/esm/bridges/``, with a
         * ``data:`` URI fallback on read-only cursors) and in JS
         * (``@web/core/module_bridge``).  Singleton identity for
         * ``@web/core/registry``, ``@web/services/*``, view type
         * registrations, etc. depends on every consumer resolving
         * the same specifier to the same object — which only works
         * because this Map is shared across bundles.
         */
        modules = new Map();

        /**
         * Lifecycle event surface for the module graph.  Today it
         * dispatches exactly one event:
         *
         *   • ``rebind`` — a CustomEvent fired when ``registerNativeModules``
         *     re-binds an already-known specifier to a DIFFERENT
         *     namespace object.  ``detail.specifiers`` is the list of
         *     affected specifiers.  In production this means a
         *     duplicated module in the bundle graph (singleton split
         *     risk); in dev hot-reload it's the expected signal that a
         *     module was re-evaluated.  Integrations can subscribe via
         *     ``odoo.loader.bus.addEventListener("rebind", ...)``.
         */
        bus = new EventTarget();

        /**
         * Register already-evaluated ES module namespaces into the
         * shared Map.
         *
         * Called from two places:
         *   • The esbuild bundle's auto-generated entry, after its
         *     ``import * as __mN from "..."`` statements run.
         *   • ``@web/core/assets.loadESMBundle`` in cross-doc mode
         *     (when loading a bundle into a target iframe, the
         *     injected bridge script forwards the resolved specifier
         *     → namespace pairs back here so the parent's loader
         *     stays authoritative).
         *
         * Overwrite semantics: ``Map.set`` replaces any prior entry
         * with the same key — last-write-wins, unchanged from the
         * pre-refactor behavior.  Re-binding a specifier to the SAME
         * namespace object (repeat dynamic ``import()`` returning the
         * cached namespace, parallel cross-doc bridges, the second
         * inline shim) is benign and stays silent.
         *
         * Re-binding to a DIFFERENT namespace object is the one event
         * that breaks singleton identity across bundles — it's
         * detected by reference and surfaced on ``bus`` (event
         * ``rebind``) plus the debug-gated asset log.  These are
         * opt-in channels by design: never a beacon or ``console.error``,
         * so a legitimate dev hot-reload can't spam telemetry.  The
         * registration itself never throws — it runs at the bundle's
         * top level, where a raised error would white-screen the page.
         *
         * @param {Record<string, any>} modulesByName
         */
        registerNativeModules(modulesByName) {
            const entries = Object.entries(modulesByName);
            _loaderDebug("registerNativeModules count=", entries.length);
            /** @type {string[] | undefined} */
            let rebound;
            for (const [name, mod] of entries) {
                const prev = this.modules.get(name);
                if (prev !== undefined && prev !== mod) {
                    (rebound ??= []).push(name);
                }
                this.modules.set(name, mod);
            }
            if (rebound) {
                _loaderDebug("registerNativeModules rebind", rebound);
                try {
                    this.bus.dispatchEvent(
                        new CustomEvent("rebind", { detail: { specifiers: rebound } }),
                    );
                } catch {
                    // A context lacking ``CustomEvent`` (or a
                    // ``dispatchEvent`` that itself throws) must not
                    // abort the bundle's top-level evaluation.  A
                    // throwing listener doesn't reach here — the DOM
                    // reports those globally and ``dispatchEvent``
                    // still returns.
                }
            }
        }

        /**
         * Self-heal a failed bundle-asset load with ONE guarded reload.
         *
         * Bundle and bridge URLs are content-addressed
         * (``/web/assets/<unique>/...``, ``/web/assets/esm/<hash>/...``);
         * when the attachment garbage collector sweeps a row while a
         * stale cached page still references its URL, the script 404s
         * and the page white-screens with no recovery path.  Reloading
         * re-renders through ``ir.qweb``, which regenerates the bundle
         * and mints fresh URLs.
         *
         * Guard: at most one reload per minute per tab, recorded in
         * ``sessionStorage`` — a persistent failure (server down,
         * genuine bundle error) degrades to the normal error surface
         * instead of a reload loop.  No storage access (sandboxed
         * iframe) means no rate limit is possible, so no reload either.
         *
         * @param {EventTarget | null} target the element whose load failed
         * @returns {boolean} whether a reload was triggered
         */
        handleAssetLoadError(target) {
            const el = /** @type {HTMLScriptElement | null} */ (target);
            const src = el?.tagName === "SCRIPT" && (el.src || el.dataset?.src);
            if (!src || !src.includes("/web/assets/")) {
                return false;
            }
            const GUARD_KEY = "odoo-asset-reload-ts";
            try {
                const storage = globalThis.sessionStorage;
                const last = parseInt(storage.getItem(GUARD_KEY) ?? "", 10) || 0;
                const now = Date.now();
                if (now - last < 60_000) {
                    return false;
                }
                storage.setItem(GUARD_KEY, String(now));
            } catch {
                return false;
            }
            _loaderDebug("asset load failed, reloading once:", src);
            this._reloadPage();
            return true;
        }

        /** Reload seam — overridden in tests; reloads only THIS document. */
        _reloadPage() {
            globalThis.location.reload();
        }
    }

    o.loader = new OdooModuleLoader();

    // ──────────────────────────────────────────────────────────────
    // Inlined pre-bundle error reporter
    // ──────────────────────────────────────────────────────────────
    //
    // The shim runs BEFORE the esbuild bundle, so it catches the
    // failure window in which the bundle itself is parsing / evaluating
    // (a syntax error in a single source file fails the whole bundle
    // load and leaves ``@web/services/error_service`` unreachable; the
    // page goes white with no telemetry).  Once the bundle loads
    // successfully, the in-app error_service installs its own listeners
    // on top of these — both fire; the endpoint tolerates duplicates.
    //
    // This is the PRE-ESM mirror of ``@web/core/errors/error_beacon``:
    // that module is the canonical wire shape + endpoint + throttle for
    // every ES-module caller, but the shim cannot ``import`` it (it runs
    // before any module evaluates), so the same logic is inlined here.
    // Keep the payload fields and endpoint in sync with that module and
    // the server contract (``observability.py::js_error``).
    //
    // Throttle: one beacon per (message, line, col) per page lifetime.
    // ``ErrorEvent.error`` is sometimes missing (cross-origin scripts);
    // we still report message/line/col which is enough to triage.
    const seenErrors = new Set();
    function reportError(payload) {
        const key = `${payload.message}|${payload.line}|${payload.col}`;
        if (seenErrors.has(key)) {
            return;
        }
        seenErrors.add(key);
        try {
            const blob = new Blob([JSON.stringify(payload)], {
                type: "application/json",
            });
            globalThis.navigator?.sendBeacon?.("/web/observability/js_error", blob);
        } catch {
            // sendBeacon can throw on payload size > UA quota or in
            // sandboxed iframes.  The error reporter must never raise
            // a secondary error that the page can't surface.
        }
    }
    globalThis.addEventListener?.("error", (ev) => {
        reportError({
            phase: globalThis.odoo?.isReady ? "post_boot" : "pre_boot",
            kind: "error",
            message: String(ev.message || ev.error?.message || "(no message)"),
            filename: String(ev.filename || ""),
            line: ev.lineno | 0,
            col: ev.colno | 0,
            stack: ev.error?.stack ? String(ev.error.stack).slice(0, 4096) : "",
            url: globalThis.location?.href || "",
            user_agent: globalThis.navigator?.userAgent || "",
        });
    });
    // Resource load failures don't bubble — this capture-phase listener
    // sees them with ``ev.target`` = the failing element (runtime errors
    // have ``target === window`` and are handled by the reporter above).
    // A failing bundle-asset script triggers the loader's one-shot reload
    // self-heal; the beacon is sent regardless of the reload because
    // ``sendBeacon`` is designed to survive navigation.
    globalThis.addEventListener?.(
        "error",
        (ev) => {
            const target = ev.target;
            if (
                target &&
                target !== globalThis &&
                o.loader.handleAssetLoadError(target)
            ) {
                reportError({
                    phase: globalThis.odoo?.isReady ? "post_boot" : "pre_boot",
                    kind: "asset_load_error",
                    message: "bundle asset failed to load; reloading once",
                    filename: String(
                        /** @type {HTMLScriptElement} */ (target).src || "",
                    ),
                    line: 0,
                    col: 0,
                    stack: "",
                    url: globalThis.location?.href || "",
                    user_agent: globalThis.navigator?.userAgent || "",
                });
            }
        },
        true,
    );
    globalThis.addEventListener?.("unhandledrejection", (ev) => {
        const reason = ev.reason;
        const message =
            reason instanceof Error
                ? reason.message
                : typeof reason === "string"
                  ? reason
                  : "(non-error rejection)";
        reportError({
            phase: globalThis.odoo?.isReady ? "post_boot" : "pre_boot",
            kind: "unhandledrejection",
            message: String(message),
            filename: "",
            line: 0,
            col: 0,
            stack:
                reason instanceof Error && reason.stack
                    ? String(reason.stack).slice(0, 4096)
                    : "",
            url: globalThis.location?.href || "",
            user_agent: globalThis.navigator?.userAgent || "",
        });
    });
})();
