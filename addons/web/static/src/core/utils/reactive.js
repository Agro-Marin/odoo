// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/reactive */

import { reactive } from "@odoo/owl";

export class SignalStore {
    constructor() {
        return reactive(this);
    }
}

/**
 * @template {object[]} T
 * @param {(...args: [...T]) => any} cb
 * @param {[...T]} deps
 * @returns {() => void} disposer: stops the effect from firing again
 */
export function effect(cb, deps) {
    let disposed = false;
    const reactiveDeps = reactive(deps, () => {
        if (disposed) {
            return;
        }
        cb(...reactiveDeps);
    });
    cb(...reactiveDeps);
    return () => {
        disposed = true;
    };
}

/**
 * Historical alias of {@link effect}, kept for its existing callers now that
 * `effect` returns a disposer itself.
 *
 * @template {object[]} T
 * @param {(...args: [...T]) => any} cb
 * @param {[...T]} deps
 * @returns {() => void}
 */
export function disposableEffect(cb, deps) {
    return effect(cb, deps);
}
