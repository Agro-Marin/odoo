// @ts-check
/** @odoo-module native */

let depth = 0;

/** @type {Set<() => any>} */
const pending = new Set();

/**
 * @template T
 * @param {() => Promise<T>} evaluate
 * @returns {Promise<T>}
 */
export async function runInBundleTransaction(evaluate) {
    depth++;
    try {
        return await evaluate();
    } finally {
        depth--;
        if (depth === 0 && pending.size) {
            const callbacks = [...pending];
            pending.clear();
            for (const callback of callbacks) {
                try {
                    await callback();
                } catch (error) {
                    console.error("[bundle] deferred callback failed:", error);
                }
            }
        }
    }
}

/**
 * @param {() => any} callback
 * @returns {boolean}
 */
export function deferUntilBundlesSettled(callback) {
    if (depth === 0) {
        return false;
    }
    pending.add(callback);
    return true;
}

/** @returns {boolean} */
export function isBundleEvaluating() {
    return depth > 0;
}

export function resetBundleTransactions() {
    depth = 0;
    pending.clear();
}
