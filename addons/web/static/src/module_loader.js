(function () {
    "use strict";

    const o = (globalThis.odoo ??= {});
    if (o.loader) {
        return;
    }

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
            if (!src || !src.includes("/web/assets/")) {
                return;
            }
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
