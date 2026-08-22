(function () {
    "use strict";

    const o = (globalThis.odoo ??= {});
    if (o.loader) {
        return;
    }

    /**
     * @param {EventTarget | null} target
     * @returns {string}
     */
    function bundleAssetSrc(target) {
        const el = /** @type {any} */ (target);
        const src =
            (el?.tagName === "SCRIPT" && (el.src || el.dataset?.src)) ||
            (el?.tagName === "LINK" && el.href) ||
            "";
        return src && src.includes("/web/assets/") ? String(src) : "";
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
                if (!dbg) {
                    reportJsError({
                        kind: "module_rebind",
                        message:
                            "singleton split (module rebound): " + rebound.join(","),
                    });
                }
                try {
                    this.bus.dispatchEvent(
                        new CustomEvent("rebind", { detail: { specifiers: rebound } }),
                    );
                } catch {}
            }
            try {
                this.bus.dispatchEvent(
                    new CustomEvent("registered", {
                        detail: { specifiers: entries.map(([name]) => name) },
                    }),
                );
            } catch {}
        }

        /**
         * @param {EventTarget | null} target
         * @returns {boolean}
         */
        handleAssetLoadError(target) {
            const src = bundleAssetSrc(target);
            if (!src) {
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

    const ENDPOINT = "/web/observability/js_error";
    const MAX_MESSAGE = 4096;
    const MAX_STACK = 4096;
    const MAX_CAUSE = 4096;
    const MAX_CAUSE_DEPTH = 8;
    const MAX_SEEN_KEYS = 512;

    const KINDS = new Set([
        "error",
        "unhandledrejection",
        "module_rebind",
        "service_start",
        "asset_load_error",
    ]);

    const IGNORED_MESSAGE_PREFIXES = [
        "ResizeObserver loop completed with undelivered notifications",
        "ResizeObserver loop limit exceeded",
    ];

    /**
     * @param {string} message
     * @returns {boolean}
     */
    function isIgnoredMessage(message) {
        return IGNORED_MESSAGE_PREFIXES.some((prefix) => message.startsWith(prefix));
    }

    /**
     * @param {string} str
     * @returns {string}
     */
    function hashCode(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            hash = (hash << 5) - hash + str.charCodeAt(i);
            hash |= 0;
        }
        return (hash + 16 ** 8).toString(16).slice(-8);
    }

    /**
     * @param {string} key
     * @param {unknown} value
     * @returns {unknown}
     */
    function elideNested(key, value) {
        if (key === "") {
            return value;
        }
        return value && typeof value === "object" ? "[object]" : value;
    }

    /**
     * @param {unknown} cause
     * @returns {string}
     */
    function serializeCause(cause) {
        const parts = [];
        const visited = new Set();
        let current = cause;
        let depth = 0;
        while (current !== undefined && current !== null && depth < MAX_CAUSE_DEPTH) {
            if (typeof current === "object") {
                if (visited.has(current)) {
                    parts.push("Caused by: [circular]");
                    break;
                }
                visited.add(current);
            }
            let text;
            try {
                if (current instanceof Error) {
                    text = `${current.name}: ${current.message}`;
                } else if (typeof current === "object") {
                    text = JSON.stringify(current, elideNested);
                } else {
                    text = String(current);
                }
            } catch {
                text = "[unserializable]";
            }
            parts.push(`Caused by: ${text}`);
            current = /** @type {{ cause?: unknown }} */ (current)?.cause;
            depth++;
        }
        return parts.join("\n").slice(0, MAX_CAUSE);
    }

    const seenErrors = new Set();

    /**
     * @param {{
     * message: unknown,
     * kind?: string,
     * phase?: string,
     * filename?: string,
     * line?: number,
     * col?: number,
     * stack?: string,
     * cause?: unknown,
     * reloaded?: boolean,
     * dedup?: boolean,
     * }} info
     * @returns {boolean}
     */
    function reportJsError(info) {
        const message = String(info?.message ?? "");
        if (!message || isIgnoredMessage(message)) {
            return false;
        }
        const line = (info.line ?? 0) | 0;
        const col = (info.col ?? 0) | 0;
        const stack = info.stack ? String(info.stack).slice(0, MAX_STACK) : "";
        const cause = serializeCause(info.cause);
        if (info.dedup ?? true) {
            const key = `${message}|${line}|${col}|${hashCode(stack + cause)}`;
            if (seenErrors.has(key)) {
                return false;
            }
            if (seenErrors.size >= MAX_SEEN_KEYS) {
                seenErrors.delete(seenErrors.values().next().value);
            }
            seenErrors.add(key);
        }
        try {
            const payload = {
                phase: info.phase ?? (o.isReady ? "post_boot" : "pre_boot"),
                kind: KINDS.has(info.kind) ? info.kind : "error",
                message: message.slice(0, MAX_MESSAGE),
                cause,
                filename: String(info.filename ?? ""),
                line,
                col,
                stack,
                url: globalThis.location?.href || "",
                user_agent: globalThis.navigator?.userAgent || "",
            };
            if (info.reloaded !== undefined) {
                payload.reloaded = info.reloaded;
            }
            const blob = new Blob([JSON.stringify(payload)], {
                type: "application/json",
            });
            return Boolean(globalThis.navigator?.sendBeacon?.(ENDPOINT, blob));
        } catch {
            return false;
        }
    }

    o.loader._beacon = {
        reportJsError,
        seenErrors,
        serializeCause,
        hashCode,
        limits: {
            ENDPOINT,
            MAX_MESSAGE,
            MAX_STACK,
            MAX_CAUSE,
            MAX_CAUSE_DEPTH,
            MAX_SEEN_KEYS,
            KINDS,
        },
    };

    globalThis.addEventListener?.("error", (ev) => {
        if (globalThis.odoo?.isReady) {
            return;
        }
        reportJsError({
            phase: "pre_boot",
            kind: "error",
            message: ev.message || ev.error?.message || "(no message)",
            cause: ev.error?.cause,
            filename: ev.filename,
            line: ev.lineno,
            col: ev.colno,
            stack: ev.error?.stack,
        });
    });
    globalThis.addEventListener?.(
        "error",
        (ev) => {
            const target = ev.target;
            if (!target || target === globalThis) {
                return;
            }
            const src = bundleAssetSrc(target);
            if (!src) {
                return;
            }
            const reloaded = o.loader.handleAssetLoadError(target);
            reportJsError({
                kind: "asset_load_error",
                message: reloaded
                    ? "bundle asset failed to load; reloading once"
                    : "bundle asset failed to load; reload suppressed",
                reloaded,
                filename: src,
            });
        },
        true,
    );
    globalThis.addEventListener?.("unhandledrejection", (ev) => {
        if (globalThis.odoo?.isReady) {
            return;
        }
        const reason = ev.reason;
        const message =
            reason instanceof Error
                ? reason.message
                : typeof reason === "string"
                  ? reason
                  : "(non-error rejection)";
        reportJsError({
            phase: "pre_boot",
            kind: "unhandledrejection",
            message,
            cause: /** @type {{ cause?: unknown }} */ (reason)?.cause,
            stack: reason instanceof Error ? reason.stack : "",
        });
    });
})();
