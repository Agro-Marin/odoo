// @ts-check
/** @odoo-module native */

/** @module @web/core/errors/error_beacon - Canonical client→server JS-error beacon (/web/observability/js_error) */

/**
 * Single source of truth for the JS-error observability beacon.
 *
 * The wire shape and endpoint are defined ONCE here for every ESM caller
 * (today: ``@web/core/registry`` schema anomalies).  It must match the
 * server contract in ``web/controllers/observability.py::js_error`` —
 * fields: ``phase`` / ``kind`` / ``message`` / ``filename`` / ``line`` /
 * ``col`` / ``stack`` / ``url`` / ``user_agent`` (the server re-clamps and
 * re-validates every field, so the caps below are convenience only).
 *
 * ``web/static/src/module_loader.js`` keeps its OWN inlined copy of this
 * logic because it is the pre-ESM bootstrap shim and runs before any ES
 * module can be imported — it cannot ``import`` from here.  That copy and
 * this module MUST stay in sync; THIS module is the canonical shape.
 */

const ENDPOINT = "/web/observability/js_error";

const seen = new Set();

const MAX_MESSAGE = 4096;
const MAX_STACK = 4096;

/**
 * Best-effort, never-throwing beacon of a JS error to the observability
 * endpoint.  Fills the page-context fields (``phase`` / ``url`` /
 * ``user_agent``) so callers pass only what they know.
 *
 * @param {{
 *   message: string,
 *   kind?: "error" | "unhandledrejection",
 *   filename?: string,
 *   line?: number,
 *   col?: number,
 *   stack?: string,
 * }} info
 * @returns {boolean} ``true`` if a fresh beacon was queued; ``false`` if it
 *   was throttled, had an empty message, or the platform has no
 *   ``sendBeacon`` (sandboxed iframe / headless runner).
 */
export function reportJsError(info) {
    const message = String(info?.message ?? "");
    if (!message) {
        return false;
    }
    const line = info.line | 0;
    const col = info.col | 0;
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
