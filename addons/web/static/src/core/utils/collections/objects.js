// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/collections/objects - Object helpers: deepEqual, deepCopy, toRawDeep, pick, omit, deepMerge */

import { toRaw } from "@odoo/owl";

/**
 * Shallow compares two objects.
 *
 * @template T
 * @param {T} obj1
 * @param {T} obj2
 * @param {(a: any, b: any) => boolean} [comparisonFn]
 * @returns {boolean}
 */
export function shallowEqual(obj1, obj2, comparisonFn = (a, b) => a === b) {
    if (obj1 !== Object(obj1) || obj2 !== Object(obj2)) {
        return obj1 === obj2;
    }
    const o1 = /** @type {any} */ (obj1);
    const o2 = /** @type {any} */ (obj2);
    const obj1Keys = Reflect.ownKeys(o1);
    return (
        obj1Keys.length === Reflect.ownKeys(o2).length &&
        obj1Keys.every((key) => comparisonFn(o1[key], o2[key]))
    );
}

/**
 * Deeply compares two objects.
 *
 * @param {unknown} obj1
 * @param {unknown} obj2
 * @returns {boolean}
 */
export const deepEqual = (obj1, obj2) => shallowEqual(obj1, obj2, deepEqual);

/**
 * Recursively un-wraps OWL reactive proxies in plain objects, arrays, Maps,
 * and Sets so that the result is structured-clone compatible. Class instances
 * (Date, RegExp, ArrayBuffer, etc.) are returned by reference via a single
 * level of ``toRaw`` — ``structuredClone`` already handles their internal
 * state correctly when present in the output tree. Cycles are preserved via
 * a ``WeakMap`` accumulator.
 *
 * @template T
 * @param {T} value
 * @param {WeakMap<object, object>} [seen]
 * @returns {T}
 */
export function toRawDeep(value, seen = new WeakMap()) {
    if (value === null || typeof value !== "object") {
        return value;
    }
    const raw = toRaw(value);
    if (seen.has(raw)) {
        return /** @type {any} */ (seen.get(raw));
    }
    if (Array.isArray(raw)) {
        /** @type {any[]} */
        const out = [];
        seen.set(raw, out);
        for (let i = 0; i < raw.length; i++) {
            out[i] = toRawDeep(raw[i], seen);
        }
        return /** @type {any} */ (out);
    }
    // Plain objects: both ``Object``-prototyped and null-prototype. Class
    // instances (constructor !== Object and prototype !== null) fall through
    // to the passthrough at the bottom.
    const proto = Object.getPrototypeOf(raw);
    if (proto === Object.prototype || proto === null) {
        /** @type {Record<string, any>} */
        const out = proto === null ? Object.create(null) : {};
        seen.set(raw, out);
        for (const k of Object.keys(raw)) {
            out[k] = toRawDeep(/** @type {any} */ (raw)[k], seen);
        }
        return /** @type {any} */ (out);
    }
    if (raw instanceof Map) {
        /** @type {Map<any, any>} */
        const out = new Map();
        seen.set(raw, out);
        for (const [k, v] of raw) {
            out.set(toRawDeep(k, seen), toRawDeep(v, seen));
        }
        return /** @type {any} */ (out);
    }
    if (raw instanceof Set) {
        /** @type {Set<any>} */
        const out = new Set();
        seen.set(raw, out);
        for (const v of raw) {
            out.add(toRawDeep(v, seen));
        }
        return /** @type {any} */ (out);
    }
    // Date, RegExp, ArrayBuffer, class instances — passthrough.
    return /** @type {any} */ (raw);
}

/**
 * Deep copies an object using ``structuredClone``, which preserves Date,
 * Set, Map, ArrayBuffer, RegExp, and other structured types. Reactive OWL
 * proxies are recursively unwrapped via ``toRawDeep`` before cloning so that
 * structured types survive the copy instead of falling through to the JSON
 * fallback (which silently drops them). Functions and DOM nodes still fall
 * through to JSON.
 *
 * @template T
 * @param {T} object
 * @return {T}
 */
export function deepCopy(object) {
    if (!object) {
        return object;
    }
    try {
        return structuredClone(object);
    } catch {
        // structuredClone fails on reactive proxies; unwrap and retry.
        try {
            return structuredClone(toRawDeep(object));
        } catch {
            // Truly non-clonable input (functions, DOM nodes, etc.).
            return JSON.parse(JSON.stringify(toRawDeep(object)));
        }
    }
}

/**
 * Returns whether the given value is an object, i.e. an instance of the `Object`
 * class or of one of its direct subclass.
 *
 * Note: this may wrongly validate any object implementing a modified `toString`
 * explicitly returning `"[object Object]"`.
 *
 * @param {unknown} value
 * @returns {boolean}
 * @example
 *  // true
 *  isObject({ a: 1 });
 *  isObject(Object.create(null));
 * @example
 *  // false
 *  isObject([1, 2, 3]);
 *  isObject(new Map([["a", 1]]));
 */
export function isObject(value) {
    return Object.prototype.toString.call(value) === "[object Object]";
}

/**
 * Returns a shallow copy of object with every property in properties removed
 * if present in object.
 *
 * @template T
 * @template {keyof T} K
 * @param {T} object
 * @param {...(K)} properties
 * @returns {Omit<T, K>}
 */
export function omit(object, ...properties) {
    /** @type {any} */
    const result = {};
    const propertiesSet = new Set(properties);
    for (const key of Object.keys(object)) {
        if (!propertiesSet.has(/** @type {any} */ (key))) {
            result[key] = object[key];
        }
    }
    return result;
}

/**
 * @template T
 * @template {keyof T} K
 * @param {T} object
 * @param {...(K)} properties
 * @returns {Pick<T, K>}
 */
export function pick(object, ...properties) {
    return /** @type {Pick<T, K>} */ (
        Object.fromEntries(
            properties
                .filter((prop) => prop in /** @type {any} */ (object))
                .map((prop) => [prop, /** @type {any} */ (object)[prop]]),
        )
    );
}

/**
 * Deeply merges two values, recursively combining plain-object properties.
 * Non-object values (primitives, arrays, functions) follow "extension wins"
 * semantics: `extension` is returned as-is, unless it is `undefined`, in
 * which case `target` is returned. Arrays are not deep-merged; `extension`
 * replaces `target` entirely for array values.
 *
 * @param {any} target - The base value.
 * @param {any} extension - The value to merge on top of target.
 * @returns {any} - The merged result.
 *
 * @example
 * const target = { a: 1, b: { c: 2 } };
 * const source = { a: 2, b: { d: 3 } };
 * const output = deepMerge(target, source);
 * // output => { a: 2, b: { c: 2, d: 3 } }
 */
export function deepMerge(target, extension) {
    if (!isObject(target) && !isObject(extension)) {
        // Neither side is a plain object — nothing to merge.
        // Follow "extension wins" semantics: return extension as-is,
        // falling back to target only when extension is undefined.
        return extension !== undefined ? extension : target;
    }

    target = target || {};
    // Use Object.assign to preserve Symbol-keyed properties (spread only copies string keys).
    const output = Object.assign({}, target);
    if (isObject(extension)) {
        for (const key of Reflect.ownKeys(extension)) {
            if (key in target && isObject(extension[key])) {
                output[key] = deepMerge(target[key], extension[key]);
            } else {
                Object.assign(output, { [key]: extension[key] });
            }
        }
    }

    return output;
}
