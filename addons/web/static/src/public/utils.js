// @ts-check
/** @odoo-module native */

/**
 * @template {WeakKey} K
 * @template V
 */
export class PairSet {
    constructor() {
        /** @type {WeakMap<K, Set<V>>} */
        this.map = new WeakMap();
    }
    /**
     * @param {K} elem1
     * @param {V} elem2
     * @returns {void}
     */
    add(elem1, elem2) {
        const values = this.map.get(elem1);
        if (values) {
            values.add(elem2);
        } else {
            this.map.set(elem1, new Set([elem2]));
        }
    }
    /**
     * @param {K} elem1
     * @param {V} elem2
     * @returns {boolean}
     */
    has(elem1, elem2) {
        return this.map.get(elem1)?.has(elem2) ?? false;
    }
    /**
     * @param {K} elem1
     * @param {V} elem2
     * @returns {void}
     */
    delete(elem1, elem2) {
        const values = this.map.get(elem1);
        if (!values) {
            return;
        }
        values.delete(elem2);
        if (!values.size) {
            this.map.delete(elem1);
        }
    }
}

/** @typedef {Record<string, Record<string, any>>} DynamicContent */

/**
 * @param {DynamicContent} dynamicContent
 * @param {string} selector
 * @param {string} t
 * @param {any} replacement
 * @returns {void}
 */
function patchDynamicContentEntry(dynamicContent, selector, t, replacement) {
    if (replacement === undefined) {
        delete dynamicContent[selector]?.[t];
        return;
    }
    dynamicContent[selector] = dynamicContent[selector] || {};
    const forSelector = dynamicContent[selector];
    if (typeof replacement === "function" && t !== "t-component") {
        if (!forSelector[t]) {
            forSelector[t] = () => {};
        }
        const oldFn = forSelector[t];
        if (["t-att-class", "t-att-style"].includes(t)) {
            forSelector[t] = /** @type {(el: any, oldResult: any) => any} */ (
                function (el, oldResult) {
                    const result = oldResult || {};
                    Object.assign(result, oldFn.call(this, el, result));
                    Object.assign(result, replacement.call(this, el, result));
                    return result;
                }
            );
        } else if (t.startsWith("t-on-")) {
            forSelector[t] = /** @type {(ev: any, ...args: any[]) => any} */ (
                function (ev, ...args) {
                    return replacement.call(this, ev, oldFn.bind(this), ...args);
                }
            );
        } else {
            forSelector[t] = /** @type {(el: any, oldResult: any) => any} */ (
                function (el, oldResult) {
                    let result = oldFn.call(this, el, oldResult);
                    result = replacement.call(this, el, result);
                    return result;
                }
            );
        }
    } else {
        forSelector[t] = replacement;
    }
}

/**
 * @param {DynamicContent} dynamicContent
 * @param {DynamicContent} replacement
 * @returns {void}
 */
export function patchDynamicContent(dynamicContent, replacement) {
    for (const [selector, forSelector] of Object.entries(replacement)) {
        for (const [t, forT] of Object.entries(forSelector)) {
            patchDynamicContentEntry(dynamicContent, selector, t, forT);
        }
    }
}
