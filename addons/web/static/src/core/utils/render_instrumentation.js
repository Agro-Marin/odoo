// @ts-check
/** @odoo-module native */

import { onRendered } from "@odoo/owl";

/**
 * @param {string} label
 */
export function useRenderCounter(label) {
    onRendered(() => {
        if (/** @type {Record<string, any>} */ (globalThis).__renderTrace) {
            const globals = /** @type {Record<string, any>} */ (globalThis);
            const stats = /** @type {Record<string, any>} */ (
                globals.__renderStats_ ||= Object.create(null)
            );
            stats[label] = (stats[label] || 0) + 1;
        }
    });
}

if (
    typeof (/** @type {Record<string, any>} */ (globalThis).__renderStats) !==
    "function"
) {
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
