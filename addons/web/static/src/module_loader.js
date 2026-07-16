/**
 * Odoo module loader bootstrap (post-ESM).
 *
 * This file is NOT included in any asset bundle. It is read from disk by
 * ``ir.qweb._build_loader_shim_js()`` at asset-node-generation time,
 * minified, and emitted as an inline ``<script>`` tag BEFORE any
 * ``<script type="module">`` runs, so ``window.odoo.loader`` exists when the
 * esbuild bundle calls ``odoo.loader.registerNativeModules({...})`` at the
 * top of its evaluation.
 *
 * Kept as a static file (not a Python string) for real editor tooling,
 * hoot-testability (module_loader.test.js), and to stay in sync with the
 * ambient TypeScript declaration in ``@types/odoo.d.ts``.
 *
 * The class MUST remain a real ES class (not a plain object). Tests recover
 * it from the live instance via ``odoo.loader.constructor`` and
 * re-instantiate it; a plain object would have ``Object`` as its
 * constructor and break that recovery.
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
 *      built by ``@web/core/module_bridge``), preserving registry
 *      singleton identity across bundle boundaries.
 *   2. Remain idempotent: if two bundles on the same page both inline
 *      the shim, the second one no-ops so all bundles share the same Map.
 *   3. Guard the singleton invariant: a specifier re-bound to a DIFFERENT
 *      namespace object means a duplicated module in the bundle graph
 *      silently splitting the ``@web/core/registry`` singleton. The
 *      loader detects this by identity and surfaces it on ``bus`` (event
 *      ``rebind``) plus the debug-gated asset log, without ever failing
 *      the bundle's top-level evaluation.
 *   4. Self-heal stale asset URLs: a content-addressed bundle URL swept
 *      by the attachment GC 404s on a stale cached page;
 *      ``handleAssetLoadError`` reacts with ONE rate-limited reload so
 *      the page re-renders with fresh URLs (see its docstring).
 *
 * Everything else the old AMD-era loader did (dependency-graph resolution,
 * cycle detection, lazy jobs, a visual-banner error reporter) is provably
 * unused across the fork and was removed; the remaining surface is
 * exercised end-to-end by ``static/tests/modules/module_loader.test.js``.
 */
(function () {
    "use strict";

    // Idempotent bootstrap: skip re-install (e.g. a parallel bundle already
    // loaded it) so every bundle shares the same ``odoo.loader.modules``
    // Map — critical for registry singleton identity across bundles.
    const o = (globalThis.odoo ??= {});
    if (o.loader) {
        return;
    }

    // Inlined asset logger — the shim runs before any ESM module, so it
    // can't ``import`` from ``@web/core/utils/asset_log``. Duplicate the
    // activation logic here, kept in sync with the Python
    // (``odoo.libs.asset_log``) and JS (``@web/core/utils/asset_log``) sides.
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
                // eslint-disable-next-line no-console -- opt-in asset-loader trace diagnostics
                console.debug("[asset.loader]", ...parts);
            }
        } catch {
            // Sandboxed iframe (no localStorage access): silently disabled.
        }
    }

    class OdooModuleLoader {
        /**
         * Shared Map of module specifier → namespace object, populated by
         * ``registerNativeModules`` from the esbuild bundle's entry. Sibling
         * bundles (lazy children, cross-doc iframes via
         * ``@web/core/assets.loadESMBundle``) look it up through bridge
         * modules (``odoo.tools.assets.esm_bridges.BridgeShimManager`` in
         * Python, ``@web/core/module_bridge`` in JS). Singleton identity for
         * ``@web/core/registry``, ``@web/services/*``, etc. depends on every
         * consumer resolving the same specifier to the same object via this
         * shared Map.
         */
        modules = new Map();

        /**
         * Lifecycle event surface for the module graph. Dispatches one
         * event: ``rebind`` — a CustomEvent fired when
         * ``registerNativeModules`` re-binds a known specifier to a
         * DIFFERENT namespace object (``detail.specifiers`` lists them). In
         * production this signals a singleton-split risk; in dev hot-reload
         * it's expected. Subscribe via
         * ``odoo.loader.bus.addEventListener("rebind", ...)``.
         */
        bus = new EventTarget();

        /**
         * Register already-evaluated ES module namespaces into the shared
         * Map. Called from the esbuild bundle's auto-generated entry (after
         * its ``import * as __mN`` statements run) and from
         * ``@web/core/assets.loadESMBundle`` in cross-doc mode (bridge
         * script forwarding resolved specifier → namespace pairs back to
         * the parent).
         *
         * ``Map.set`` overwrite semantics: re-binding a specifier to the
         * SAME namespace object (repeat dynamic import, parallel bridges, a
         * second inline shim) is benign and silent. Re-binding to a
         * DIFFERENT object breaks singleton identity across bundles —
         * detected by reference and surfaced on ``bus`` (event ``rebind``)
         * plus the debug-gated asset log, opt-in channels so a legitimate
         * dev hot-reload can't spam telemetry. Never throws: this runs at
         * the bundle's top level, where a raised error would white-screen
         * the page.
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
                // Production telemetry for singleton splits. A rebind under a
                // debug/hot-reload session is expected (and noisy), so only
                // beacon when NOT in debug mode: outside debug, a rebind means a
                // module was duplicated in the bundle graph and the
                // @web/core/registry singleton silently split — a real bug that
                // otherwise leaves no trace. reportError is hoisted (function
                // declaration) so it is reachable from here.
                const dbg = typeof o.debug === "string" ? o.debug : "";
                if (!dbg && typeof reportError === "function") {
                    reportError({
                        phase: o.isReady ? "post_boot" : "pre_boot",
                        kind: "module_rebind",
                        message:
                            "singleton split (module rebound): " + rebound.join(","),
                        filename: "",
                        line: 0,
                        col: 0,
                        stack: "",
                        url: globalThis.location?.href || "",
                        user_agent: globalThis.navigator?.userAgent || "",
                    });
                }
                try {
                    this.bus.dispatchEvent(
                        new CustomEvent("rebind", { detail: { specifiers: rebound } }),
                    );
                } catch {
                    // A missing CustomEvent (or dispatchEvent itself
                    // throwing) must not abort the bundle's top-level
                    // evaluation. A throwing listener doesn't reach here —
                    // the DOM reports those globally.
                }
            }
        }

        /**
         * Self-heal a failed bundle-asset load with ONE guarded reload.
         * Bundle URLs are content-addressed
         * (``/web/assets/<unique>/...``, ``/web/assets/esm/<hash>/...``);
         * when the attachment GC sweeps a row while a stale cached page
         * still references its URL, the script (or stylesheet) 404s and
         * the page white-screens (or renders unstyled) with no recovery
         * path. Reloading re-renders through ``ir.qweb``, which mints
         * fresh URLs. Covers SCRIPT and LINK elements: a stale
         * content-addressed URL can never succeed by re-requesting it, so
         * the reload is the only fix for both kinds.
         *
         * Guard: at most one reload per minute per tab (``sessionStorage``)
         * — a persistent failure (server down, genuine bundle error)
         * degrades to the normal error surface instead of looping. No
         * storage access (sandboxed iframe) means no reload either.
         *
         * @param {EventTarget | null} target the element whose load failed
         * @returns {boolean} whether a reload was triggered
         */
        handleAssetLoadError(target) {
            const el = /** @type {any} */ (target);
            const src =
                (el?.tagName === "SCRIPT" && (el.src || el.dataset?.src)) ||
                (el?.tagName === "LINK" && el.href);
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

    // Inlined pre-bundle error reporter — the shim runs before the esbuild
    // bundle, catching failures while the bundle itself is
    // parsing/evaluating (a syntax error fails the whole load and leaves
    // ``@web/services/error_service`` unreachable; the page goes white with
    // no telemetry). Once the bundle loads, the in-app error_service
    // installs its own listeners on top — both fire, and the endpoint
    // tolerates duplicates.
    //
    // PRE-ESM mirror of ``@web/core/errors/error_beacon`` (the canonical
    // wire shape/endpoint/throttle) since the shim can't ``import`` it.
    // Keep the payload fields and endpoint in sync with that module and the
    // server contract (``observability.py::js_error``).
    //
    // Throttle: one beacon per (message, line, col) per page lifetime.
    // ``ErrorEvent.error`` is sometimes missing (cross-origin scripts);
    // message/line/col alone is enough to triage.
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
    // have ``target === window`` and are handled by the reporter above). A
    // failing bundle-asset script triggers the loader's one-shot reload
    // self-heal; the beacon is sent regardless since ``sendBeacon`` survives
    // navigation.
    globalThis.addEventListener?.(
        "error",
        (ev) => {
            const target = ev.target;
            if (!target || target === globalThis) {
                return;
            }
            const el = /** @type {any} */ (target);
            const src =
                (el.tagName === "SCRIPT" && (el.src || el.dataset?.src)) ||
                (el.tagName === "LINK" && el.href) ||
                "";
            // Only /web/assets/ targets are ours to report; a failing user
            // <img>/<iframe> is not a bundle problem.
            if (!src || !src.includes("/web/assets/")) {
                return;
            }
            // Attempt the one-shot self-heal reload, but beacon UNCONDITIONALLY:
            // the reload is rate-limited (once/min/tab), so a reload-suppressed
            // failure previously produced NO telemetry — yet those repeated,
            // reload-suppressed failures are the most diagnostic signal. Record
            // whether a reload was actually triggered so the two cases are
            // distinguishable server-side.
            const reloaded = o.loader.handleAssetLoadError(target);
            reportError({
                phase: globalThis.odoo?.isReady ? "post_boot" : "pre_boot",
                kind: "asset_load_error",
                message: reloaded
                    ? "bundle asset failed to load; reloading once"
                    : "bundle asset failed to load; reload suppressed",
                reloaded,
                filename: String(src),
                line: 0,
                col: 0,
                stack: "",
                url: globalThis.location?.href || "",
                user_agent: globalThis.navigator?.userAgent || "",
            });
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
