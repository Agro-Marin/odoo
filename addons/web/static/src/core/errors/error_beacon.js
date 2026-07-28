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

// Kinds the server accepts (web/controllers/observability.py::js_error).
// Anything else is normalized to "error" there too; normalizing here as well
// keeps a caller typo from being logged as a category that does not exist.
const KINDS = new Set(["error", "unhandledrejection", "module_rebind", "service_start"]);

/**
 * Java ``String.hashCode`` over one string, as 8 hex chars.
 *
 * Deliberately inlined rather than imported from
 * ``@web/core/utils/format/strings``: this module is loaded by
 * ``@web/core/registry`` at the very start of boot and exists to work when
 * everything else is broken, so it carries no imports at all.  The 32-bit
 * width is ample — ``seen`` holds a handful of entries per page, not the tens
 * of thousands that pushed ``core/templates.js`` to a 53-bit hash.
 *
 * ``module_loader.js`` has a byte-identical copy; keep both in step.
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
 * Flatten an error's ``cause`` chain into one string.
 *
 * OWL reports a lifecycle failure as "An error occured in the owl lifecycle
 * (see this Error's ``cause`` property)" — the message names the property but
 * the beacon never carried it, so the log told operators to inspect something
 * they could not reach.  Walks iteratively (a cause is any value: an Error, a
 * string, a plain object, or undefined) and never throws, because a reporter
 * that raises while reporting loses the original error too.
 *
 * ``module_loader.js`` has a byte-identical copy; keep both in step.
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
            // A cycle (e1.cause = e2; e2.cause = e1) would otherwise spin until
            // the depth cap, filling the payload with repeats of two frames.
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
                text = JSON.stringify(current) ?? String(current);
            } else {
                text = String(current);
            }
        } catch {
            // Getters that throw, JSON cycles, exotic toString — the chain is
            // best-effort, so record that a level existed and move on.
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
 *   kind?: "error" | "unhandledrejection" | "module_rebind" | "service_start",
 *   filename?: string,
 *   line?: number,
 *   col?: number,
 *   stack?: string,
 *   cause?: unknown,
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
    const stack = info.stack ? String(info.stack).slice(0, MAX_STACK) : "";
    // The stack discriminates: OWL reports every lifecycle failure with one
    // generic message at 0:0, so a (message,line,col) key collapsed unrelated
    // crashes into a single beacon and dropped all but the first.
    const key = `${message}|${line}|${col}|${hashCode(stack)}`;
    if (seen.has(key)) {
        return false;
    }
    if (seen.size >= MAX_SEEN_KEYS) {
        seen.delete(seen.values().next().value);
    }
    seen.add(key);
    try {
        const payload = {
            phase: /** @type {{ odoo?: { isReady?: boolean } }} */ (globalThis).odoo
                ?.isReady
                ? "post_boot"
                : "pre_boot",
            kind: KINDS.has(/** @type {string} */ (info.kind)) ? info.kind : "error",
            message: message.slice(0, MAX_MESSAGE),
            cause: serializeCause(info.cause),
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
