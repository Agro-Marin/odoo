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
 * A free-standing derived (computed) value. Reading `d.value` runs `fn`, which
 * tracks whatever reactive signals it reads: OWL is Proxy-based, so a read that
 * happens inside a component render or an `effect` callback subscribes that
 * consumer automatically -- exactly as a plain class getter does, only not bound
 * to an instance. Lazy (computed on read) and NOT memoized: every read re-runs
 * `fn`, so `.value` always reflects the latest sources, and OWL batches the
 * renders those reads trigger within a tick.
 *
 * Reach for this only when the computation spans multiple sources or is passed
 * around as a value; when the derived value belongs to an instance, a getter on
 * a `SignalStore` / `reactive({})` is simpler. Aligned with Vue 3 `computed` /
 * Svelte 5 `$derived`, minus the memoization.
 *
 * @template T
 * @param {() => T} fn
 * @returns {{ readonly value: T }}
 */
export function derived(fn) {
    return {
        get value() {
            return fn();
        },
    };
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
