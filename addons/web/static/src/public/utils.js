// @ts-check
/** @odoo-module native */

/** @module @web/public/utils - PairSet data structure and dynamicContent patching helpers for public pages */

/**
 * Pairs (elem1, elem2) with set semantics, backed by a WeakMap of Sets.
 *
 * Weak on the first element because the only user keys it by DOM node: an
 * element dropped from the document without its interactions being stopped
 * (there is no way to guarantee that from here) would otherwise be pinned,
 * together with every interaction class started on it, for the page's lifetime.
 * Nothing enumerates the pairs, so weakness costs nothing.
 */
export class PairSet {
    constructor() {
        this.map = new WeakMap();
    }
    add(elem1, elem2) {
        if (!this.map.has(elem1)) {
            this.map.set(elem1, new Set());
        }
        this.map.get(elem1).add(elem2);
    }
    has(elem1, elem2) {
        if (!this.map.has(elem1)) {
            return false;
        }
        return this.map.get(elem1).has(elem2);
    }
    delete(elem1, elem2) {
        if (!this.map.has(elem1)) {
            return;
        }
        const s = this.map.get(elem1);
        s.delete(elem2);
        if (!s.size) {
            this.map.delete(elem1);
        }
    }
}

/**
 * Patches a "t-" entry of a dynamic content.
 *
 * The wrappers are plain functions, not arrows, and forward their `this` to
 * both sides of the chain: the framework invokes a definition with the
 * interaction as `this`, so an entry written as an unbound method reference
 * (`"t-on-click": this.onClick`) would otherwise lose it the moment anything
 * patched that entry.
 *
 * @param {Object} dynamicContent
 * @param {string} selector
 * @param {string} t
 * @param {any|function} replacement, if a function, takes the element (or the
 *     event, for `t-on-`) and the replaced function's output as parameters
 */
function patchDynamicContentEntry(dynamicContent, selector, t, replacement) {
    dynamicContent[selector] = dynamicContent[selector] || {};
    const forSelector = dynamicContent[selector];
    if (replacement === undefined) {
        delete forSelector[t];
    } else if (typeof replacement === "function" && t !== "t-component") {
        if (!forSelector[t]) {
            forSelector[t] = () => {};
        }
        const oldFn = forSelector[t];
        if (["t-att-class", "t-att-style"].includes(t)) {
            forSelector[t] = function (el, oldResult) {
                const result = oldResult || {};
                Object.assign(result, oldFn.call(this, el, result));
                Object.assign(result, replacement.call(this, el, result));
                return result;
            };
        } else if (t.startsWith("t-on-")) {
            forSelector[t] = function (ev, ...args) {
                // bound, because the documented way to chain is a bare
                // `oldFn(ev)` call in the patching handler
                return replacement.call(this, ev, oldFn.bind(this), ...args);
            };
        } else {
            forSelector[t] = function (el, oldResult) {
                let result = oldFn.call(this, el, oldResult);
                result = replacement.call(this, el, result);
                return result;
            };
        }
    } else {
        forSelector[t] = replacement;
    }
}

/**
 * Patches several entries in a dynamicContent.
 * Example usage:
 * patchDynamicContent(this.dynamicContent, {
 *     _root: {
 *         "t-att-class": (el, old) => ({
 *             "test": this.condition && old.test,
 *         }),
 *         // a t-on- handler is called with the event, not the element
 *         "t-on-click": (ev, oldFn) => {
 *             oldFn(ev);
 *             this.doMoreStuff();
 *         },
 *     },
 * })
 *
 * `old` is undefined when nothing was registered for that entry yet.
 *
 * @param {Object} dynamicContent
 * @param {Object} replacement
 */
export function patchDynamicContent(dynamicContent, replacement) {
    for (const [selector, forSelector] of Object.entries(replacement)) {
        for (const [t, forT] of Object.entries(forSelector)) {
            patchDynamicContentEntry(dynamicContent, selector, t, forT);
        }
    }
}
