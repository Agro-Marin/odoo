// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/render_instrumentation - Dev-mode render counters for performance audits */

import { onRendered } from "@odoo/owl";

/**
 * Increment a global counter every time the calling component renders.
 * Read via ``globalThis.__renderStats()``, reset via ``__renderReset()``.
 * Gated by ``globalThis.__renderTrace`` (set truthy in DevTools) so the hook
 * is a no-op by default — used for Tier 1.1 perf audits of render counts.
 *
 * @param {string} label  Identifier for the counter, e.g. component/template
 *  name (``"list.ListRenderer"``) so reads stay unambiguous across a session.
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
