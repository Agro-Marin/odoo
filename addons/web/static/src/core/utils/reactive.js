// @ts-check
/** @odoo-module native */

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
 * @returns {() => void}
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
 * @template {object[]} T
 * @param {(...args: [...T]) => any} cb
 * @param {[...T]} deps
 * @returns {() => void}
 */
export function disposableEffect(cb, deps) {
    return effect(cb, deps);
}
