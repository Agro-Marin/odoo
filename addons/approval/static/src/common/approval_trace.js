// @ts-check
/** @odoo-module native */
import { browser } from "@web/core/browser/browser";

/**
 * Campaign instrumentation for the approval client -- TEMPORARY SCAFFOLDING.
 *
 * The twin of `models/approval_trace.py`, for the same campaign and removed with it.
 * `machine_doc_v1/conventions.md`, "Campaign Instrumentation", is the reference; this
 * file only has to say how it is switched on and why it is shaped this way.
 *
 * OFF unless asked for, because a client log line costs a user nothing and a
 * developer everything. Two switches, either one:
 *
 *   ?approval_trace=button,service     one page load
 *   localStorage["approval.trace"]     until you clear it
 *
 * `1`, `*` or `all` mean every target. The value is read once, on first use, so a
 * page that never traces pays one `URLSearchParams` parse and nothing else.
 *
 * Lines are the same `target event key=value` grammar the Python half emits, so one
 * grep reads both sides of a flow:
 *
 *   approval.service flushed specs=3 ms=41.180 results=3
 *   approval.button  loaded model=res.partner res_id=7 gated=true approved=false
 */

const STORAGE_KEY = "approval.trace";
const URL_KEY = "approval_trace";
const EVERYTHING = new Set(["1", "*", "all", "true"]);
const MAX_ITEMS = 10;
const MAX_CHARS = 200;

let wanted = null;

function configured() {
    let raw;
    try {
        const search = browser.location?.search || "";
        raw =
            new URLSearchParams(search).get(URL_KEY) ||
            browser.localStorage?.getItem(STORAGE_KEY) ||
            "";
    } catch {
        // A blocked or absent storage must not break the page it was asked about.
        raw = "";
    }
    return new Set(
        raw
            .split(",")
            .map((name) => name.trim().toLowerCase())
            .filter(Boolean),
    );
}

function enabled(target) {
    wanted ??= configured();
    if (!wanted.size) {
        return false;
    }
    return wanted.has(target) || [...EVERYTHING].some((all) => wanted.has(all));
}

function render(value) {
    if (value === null || value === undefined) {
        return String(value);
    }
    if (typeof value === "number" || typeof value === "boolean") {
        return String(value);
    }
    if (Array.isArray(value)) {
        const shown = value.slice(0, MAX_ITEMS).map(render);
        return `[${shown.join(",")}${value.length > MAX_ITEMS ? ",+" : ""}]`;
    }
    if (typeof value === "object") {
        const entries = Object.entries(value).slice(0, MAX_ITEMS);
        return `{${entries.map(([key, item]) => `${key}:${render(item)}`).join(",")}}`;
    }
    const text = String(value);
    const capped = text.length > MAX_CHARS ? `${text.slice(0, MAX_CHARS)}...` : text;
    return /\s/.test(capped) || !capped ? JSON.stringify(capped) : capped;
}

function line(target, event, fields) {
    const rendered = Object.entries(fields || {})
        .map(([key, value]) => `${key}=${render(value)}`)
        .join(" ");
    return `approval.${target} ${event}${rendered ? ` ${rendered}` : ""}`;
}

export const trace = {
    /** Whether a payload is worth building at all. */
    on(target) {
        return enabled(target);
    },

    /** Drop the memoised switch, so the next call re-reads it. For tests. */
    forget() {
        wanted = null;
    },

    /** One line per decision this code took. */
    event(target, event, fields) {
        if (enabled(target)) {
            browser.console.debug(line(target, event, fields));
        }
    },

    /** One line per externally visible thing that happened. */
    note(target, event, fields) {
        if (enabled(target)) {
            browser.console.info(line(target, event, fields));
        }
    },

    /**
     * Await `run()` and report what it cost, whether it resolves or rejects.
     *
     * @template T
     * @param {string} target
     * @param {string} event
     * @param {Object} fields
     * @param {() => Promise<T>} run
     * @returns {Promise<T>}
     */
    async span(target, event, fields, run) {
        if (!enabled(target)) {
            return run();
        }
        const started = browser.performance.now();
        try {
            const result = await run();
            trace.event(target, event, {
                ...fields,
                ms: browser.performance.now() - started,
                r: "ok",
            });
            return result;
        } catch (error) {
            trace.event(target, event, {
                ...fields,
                ms: browser.performance.now() - started,
                r: `rejected:${error?.name || "Error"}`,
            });
            throw error;
        }
    },
};
