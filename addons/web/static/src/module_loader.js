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
        } catch {}
    }

    class OdooModuleLoader {
        modules = new Map();

        bus = new EventTarget();

        /**
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
                } catch {}
            }
        }

        /**
         * @param {EventTarget | null} target
         * @returns {boolean}
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
        } catch {}
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
