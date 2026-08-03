// @ts-check
/** @odoo-module native */

/** @module @web/core/errors/error_beacon */

const ENDPOINT = "/web/observability/js_error";

const seen = new Set();

const MAX_MESSAGE = 4096;
const MAX_STACK = 4096;
// Bounded: the key embeds the message, so a page that fails once per record
// grows this set without limit. A `Set` iterates in insertion order, so
// dropping the oldest keeps de-duplication working for the recent errors --
// the only ones a burst is likely to repeat.
const MAX_SEEN_KEYS = 512;

const MAX_CAUSE = 4096;
const MAX_CAUSE_DEPTH = 8;

// Kinds observability.py::js_error accepts; anything else falls back to error.
const KINDS = new Set([
    "error",
    "unhandledrejection",
    "module_rebind",
    "service_start",
    "asset_load_error",
]);

/**
 * Inlined, not imported: this module must carry no imports. Copy in
 * module_loader.js — keep both in step.
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
 * ``JSON.stringify`` replacer that elides nested objects, bounding an unknown
 * cause by its own key count. Copy in module_loader.js — keep both in step.
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
 * Flatten an error's ``cause`` chain — the property OWL's lifecycle message
 * points at. Never throws. Byte-identical copy in module_loader.js (modulo the
 * shim's indentation); keep both in step.
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

/**
 * @param {{
 *   message: string,
 *   kind?: "error" | "unhandledrejection" | "module_rebind" | "service_start"
 *     | "asset_load_error",
 *   filename?: string,
 *   line?: number,
 *   col?: number,
 *   stack?: string,
 *   cause?: unknown,
 *   phase?: string,
 *   dedup?: boolean,
 * }} info
 *   `phase` overrides the default (`post_boot`/`pre_boot`, read off `odoo.isReady`)
 *   for callers that report a specific lifecycle moment, e.g. a boot-mount
 *   failure. `dedup` (default `true`) can be turned off for a caller that wants
 *   every occurrence beaconed rather than the first per
 *   `(message,line,col,hash(stack+cause))`.
 * @returns {boolean}
 */
export function reportJsError(info) {
    const message = String(info?.message ?? "");
    if (!message) {
        return false;
    }
    const line = (info.line ?? 0) | 0;
    const col = (info.col ?? 0) | 0;
    const stack = info.stack ? String(info.stack).slice(0, MAX_STACK) : "";
    const cause = serializeCause(info.cause);
    if (info.dedup ?? true) {
        // Cause is in the key, not just the stack: OWL wraps inside handleError
        // (owl.es.js:1661), so the wrapper's stack is the scheduler frames and two
        // component crashes in one tick collide. The component frames are the cause.
        const key = `${message}|${line}|${col}|${hashCode(stack + cause)}`;
        if (seen.has(key)) {
            return false;
        }
        if (seen.size >= MAX_SEEN_KEYS) {
            seen.delete(seen.values().next().value);
        }
        seen.add(key);
    }
    const isReady = /** @type {{ odoo?: { isReady?: boolean } }} */ (globalThis).odoo
        ?.isReady;
    try {
        const payload = {
            phase: info.phase ?? (isReady ? "post_boot" : "pre_boot"),
            kind: KINDS.has(/** @type {string} */ (info.kind)) ? info.kind : "error",
            message: message.slice(0, MAX_MESSAGE),
            cause,
            filename: String(info.filename ?? ""),
            line,
            col,
            stack,
            url: globalThis.location?.href || "",
            user_agent: globalThis.navigator?.userAgent || "",
        };
        const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
        return Boolean(globalThis.navigator?.sendBeacon?.(ENDPOINT, blob));
    } catch {
        return false;
    }
}
