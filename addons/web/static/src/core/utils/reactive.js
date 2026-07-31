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
 */
export function effect(cb, deps) {
    const reactiveDeps = reactive(deps, () => {
        cb(...reactiveDeps);
    });
    cb(...reactiveDeps);
}

/**
 * @template {object[]} T
 * @param {(...args: [...T]) => any} cb
 * @param {[...T]} deps
 * @returns {() => void}
 */
export function disposableEffect(cb, deps) {
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
