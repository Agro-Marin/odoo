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
 * The class MUST remain a real ES class (not a plain object) because
 * Hoot tests extend it via
 * ``Object.getPrototypeOf(odoo.loader.constructor)``.  Converting it to
 * a plain object would make subclasses inherit from ``Object`` and
 * break any test that relies on the loader prototype chain.
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
 *      bundle via ``data:`` URI bridges built in
 *      ``@web/core/assets``.  This preserves registry singleton
 *      identity across bundle boundaries.
 *   2. Remain idempotent: if two bundles on the same page both inline
 *      the shim, the second one must no-op so all bundles share the
 *      same Map.
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
         * (lazy children listed in ``DYNAMIC_ESM_BUNDLES``, cross-doc
         * iframes loaded via ``@web/core/assets.loadESMBundle``) look
         * up this Map through ``data:`` URI bridges constructed in
         * Python (``assetsbundle._build_native_to_legacy_bridge``)
         * and in JS (``core/assets.js``).  Singleton identity for
         * ``@web/core/registry``, ``@web/services/*``, view type
         * registrations, etc. depends on every consumer resolving
         * the same specifier to the same object — which only works
         * because this Map is shared across bundles.
         */
        modules = new Map();

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
         * with the same key.  This matches the pre-refactor behavior
         * and is deliberate — it lets a bundle re-register modules
         * during hot reload in dev mode without stale state.  In
         * production, two registrations of the same specifier would
         * indicate a mis-configured bundle graph (duplicated
         * module), which callers can observe by listening on
         * ``bus`` once that event surface exists.
         *
         * @param {Record<string, any>} modulesByName
         */
        registerNativeModules(modulesByName) {
            const names = Object.keys(modulesByName);
            _loaderDebug("registerNativeModules count=", names.length);
            for (const [name, mod] of Object.entries(modulesByName)) {
                this.modules.set(name, mod);
            }
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
            const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
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
    globalThis.addEventListener?.("unhandledrejection", (ev) => {
        const reason = ev.reason;
        const message = reason instanceof Error
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
            stack: reason instanceof Error && reason.stack
                ? String(reason.stack).slice(0, 4096)
                : "",
            url: globalThis.location?.href || "",
            user_agent: globalThis.navigator?.userAgent || "",
        });
    });
})();
