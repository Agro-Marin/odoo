// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/render_instrumentation - Dev-mode render counters for performance audits */

import { onRendered } from "@odoo/owl";

/**
 * Increment a global counter every time the calling component renders.
 * Counters are read via ``globalThis.__renderStats()`` (snapshot of all
 * label → count pairs) and reset via ``globalThis.__renderReset()``.
 *
 * Gated by ``globalThis.__renderTrace``: when falsy (default), the hook
 * captures no data and pays only an ``onRendered`` registration. Set the
 * flag in DevTools (``__renderTrace = true``) before reproducing a
 * scenario, then read stats with ``__renderStats()``.
 *
 * Intended for Tier 1.1 perf audits — quantifying how many component
 * renders fire per user action so that ``t-memo`` adoption decisions
 * can be grounded in measurement rather than intuition.
 *
 * @param {string} label  Stable identifier for the counter. Use the
 *  component's class or template name so reads are unambiguous across
 *  a session — e.g. ``"list.ListRenderer"``, ``"fields.CharField"``.
 */
export function useRenderCounter(label) {
    onRendered(() => {
        if (/** @type {Record<string, any>} */ (globalThis).__renderTrace) {
            const stats = /** @type {Record<string, any>} */ (
                globalThis.__renderStats_ ||= /** @type {Record<string, number>} */ (
                    Object.create(null)
                )
            );
            stats[label] = (stats[label] || 0) + 1;
        }
    });
}

// Install global accessors once per process. Idempotent so HMR is safe.
if (
    typeof (/** @type {Record<string, any>} */ (globalThis).__renderStats) !==
    "function"
) {
    /** @returns {Record<string, number>} */
    /** @type {Record<string, any>} */ (globalThis).__renderStats = () =>
        Object.assign(
            Object.create(null),
            /** @type {Record<string, any>} */ (globalThis).__renderStats_ || {},
        );
    /** @type {Record<string, any>} */ (globalThis).__renderReset = () => {
        /** @type {Record<string, any>} */ (globalThis).__renderStats_ =
            /** @type {Record<string, number>} */ (Object.create(null));
    };
    /** @type {Record<string, any>} */ (globalThis).__renderTrace = false;
}
