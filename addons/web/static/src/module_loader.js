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
                        cause: "",
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
            // Unconditional, unlike `rebind`: a bridge shim generated for a
            // specifier this page had not registered yet binds `undefined` and,
            // being a plain `const`, would keep it forever. The shims listen for
            // this and re-read once, so a producer that registers later still
            // reaches the consumers that read at use time.
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

    const MAX_CAUSE = 4096;
    const MAX_CAUSE_DEPTH = 8;

    /**
     * Java ``String.hashCode`` over one string, as 8 hex chars.
     *
     * Byte-identical copy of the helper in
     * ``@web/core/errors/error_beacon`` — this shim is the pre-ESM bootstrap
     * and cannot ``import``.  Keep both in step; that module is canonical.
     *
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
     * ``JSON.stringify`` replacer that keeps the root's own scalars and elides
     * any nested object, bounding serialization of an unknown cause by its own
     * key count instead of the graph it points into.
     *
     * Byte-identical copy of the helper in
     * ``@web/core/errors/error_beacon``; keep both in step.
     *
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
     * Flatten an error's ``cause`` chain into one string.
     *
     * Byte-identical copy of the helper in
     * ``@web/core/errors/error_beacon``; see that module for the rationale.
     * Keep both in step.
     *
     * @param {unknown} cause first ``.cause`` of the reported error
     * @returns {string} ``"Caused by: ..."`` segments, or ``""`` when there is none
     */
    function serializeCause(cause) {
        const parts = [];
        const visited = new Set();
        let current = cause;
        let depth = 0;
        while (current !== undefined && current !== null && depth < MAX_CAUSE_DEPTH) {
            if (typeof current === "object") {
                // A cycle would otherwise repeat two frames up to the depth cap.
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
                    // Elided, not walked: an OWL node would stringify whole.
                    text = JSON.stringify(current, elideNested);
                } else {
                    text = String(current);
                }
            } catch {
                // Best-effort: record that a level existed and move on.
                text = "[unserializable]";
            }
            parts.push(`Caused by: ${text}`);
            current = /** @type {{ cause?: unknown }} */ (current)?.cause;
            depth++;
        }
        return parts.join("\n").slice(0, MAX_CAUSE);
    }

    // The one deliberate duplicate of `@web/core/errors/error_beacon`: this
    // shim is emitted inline before the ESM bundle, so it cannot import it.
    // Kept in step with it -- same endpoint, same
    // `(message,line,col,hash(stack+cause))` dedup key, and the same 512-key
    // cap. The key embeds the message, and this shim runs on every page load
    // before anything else, so an unbounded set is a leak; insertion order
    // makes dropping the oldest the right eviction (the recent keys, the only
    // ones a burst repeats, are what dedup must keep).
    const MAX_SEEN_KEYS = 512;

    // Browser-generated `window.onerror` messages that report no application
    // fault: a ResizeObserver whose callback resizes the observed element
    // defers the next round to the following frame and tells the page so --
    // spec-defined behaviour, not a bug. Chrome raises it with no Error object,
    // so the beacon carries no stack and no filename to act on. Copy in
    // core/errors/error_beacon.js -- keep both in step.
    const IGNORED_MESSAGE_PREFIXES = [
        "ResizeObserver loop completed with undelivered notifications",
        "ResizeObserver loop limit exceeded",
    ];
    function isIgnoredMessage(message) {
        return IGNORED_MESSAGE_PREFIXES.some((prefix) => message.startsWith(prefix));
    }

    const seenErrors = new Set();
    function reportError(payload) {
        if (isIgnoredMessage(String(payload.message || ""))) {
            return;
        }
        // Stack AND cause discriminate. OWL builds its generic lifecycle
        // wrapper inside handleError (owl.es.js:1661), so the wrapper's stack is
        // the scheduler frames — identical for two component crashes flushed in
        // the same tick. The component frames are on the cause.
        const key = `${payload.message}|${payload.line}|${payload.col}|${hashCode(
            (payload.stack || "") + (payload.cause || ""),
        )}`;
        if (seenErrors.has(key)) {
            return;
        }
        if (seenErrors.size >= MAX_SEEN_KEYS) {
            seenErrors.delete(seenErrors.values().next().value);
        }
        seenErrors.add(key);
        try {
            const blob = new Blob([JSON.stringify(payload)], {
                type: "application/json",
            });
            globalThis.navigator?.sendBeacon?.("/web/observability/js_error", blob);
        } catch {}
    }

    /**
     * Beacon seam — overridden/inspected in tests.  Same reason as
     * ``_reloadPage`` above: these live in the IIFE closure, so a test has no
     * other way to reach them, and the pre-ESM shim cannot export.
     */
    o.loader._beacon = { reportError, seenErrors, serializeCause, hashCode };

    globalThis.addEventListener?.("error", (ev) => {
        // Pre-boot safety net only. Once `odoo.isReady`, the error service owns
        // generic-error beaconing -- and beacons only genuine defects, not the
        // handled business errors this listener would otherwise duplicate into
        // the js_error stream. (The asset-load listener below and module_rebind
        // are loader-specific and beacon in both phases.)
        if (globalThis.odoo?.isReady) {
            return;
        }
        reportError({
            phase: "pre_boot",
            kind: "error",
            message: String(ev.message || ev.error?.message || "(no message)"),
            cause: serializeCause(ev.error?.cause),
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
                cause: "",
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
        // Pre-boot safety net only, as with the generic "error" listener above:
        // post-boot the error service classifies and beacons, so an expected
        // rejection (SupersededError, a handled RPCError) is not reported here.
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
        reportError({
            phase: "pre_boot",
            kind: "unhandledrejection",
            message: String(message),
            // The case this exists for: OWL surfaces a lifecycle failure as a
            // rejection whose message only says to read `cause`.
            cause: serializeCause(
                reason instanceof Error
                    ? reason.cause
                    : /** @type {{ cause?: unknown }} */ (reason)?.cause,
            ),
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
