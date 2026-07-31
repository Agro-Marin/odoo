// @ts-check
/** @odoo-module native */

/** @module @web/core/errors/error_beacon */

const ENDPOINT = "/web/observability/js_error";

const seen = new Set();

const MAX_MESSAGE = 4096;
const MAX_STACK = 4096;

/**
 * @param {{
 *   message: string,
 *   kind?: "error" | "unhandledrejection",
 *   filename?: string,
 *   line?: number,
 *   col?: number,
 *   stack?: string,
 * }} info
 * @returns {boolean}
 */
export function reportJsError(info) {
    const message = String(info?.message ?? "");
    if (!message) {
        return false;
    }
    const line = (info.line ?? 0) | 0;
    const col = (info.col ?? 0) | 0;
    const key = `${message}|${line}|${col}`;
    if (seen.has(key)) {
        return false;
    }
    seen.add(key);
    try {
        const payload = {
            phase: /** @type {{ odoo?: { isReady?: boolean } }} */ (globalThis).odoo
                ?.isReady
                ? "post_boot"
                : "pre_boot",
            kind: info.kind === "unhandledrejection" ? "unhandledrejection" : "error",
            message: message.slice(0, MAX_MESSAGE),
            filename: String(info.filename ?? ""),
            line,
            col,
            stack: info.stack ? String(info.stack).slice(0, MAX_STACK) : "",
            url: globalThis.location?.href || "",
            user_agent: globalThis.navigator?.userAgent || "",
        };
        const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
        return Boolean(globalThis.navigator?.sendBeacon?.(ENDPOINT, blob));
    } catch {
        return false;
    }
}
