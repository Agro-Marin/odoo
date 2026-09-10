// @ts-check
/** @odoo-module native */

/**
 * @template T
 * @template {string | number | symbol} K
 * @typedef {keyof T | ((item: T) => K)} Criterion
 */

/**
 * @template T
 * @param {...T[]} args
 * @returns {(T[] | undefined)[]}
 */
function _cartesian(...args) {
    if (!args.length) {
        return [undefined];
    }
    const firstArray = /** @type {T[]} */ (args.shift()).map((elem) => [elem]);
    if (!args.length) {
        return firstArray;
    }
    const result = [];
    const productOfOtherArrays = _cartesian(...args);
    for (const array of firstArray) {
        for (const tuple of productOfOtherArrays) {
            result.push([...array, ...(tuple ?? [])]);
        }
    }
    return result;
}

/**
 * @private
 * @template T
 * @template {string | number | symbol} K
 * @param {Criterion<T, K>} [criterion]
 * @returns {(element: T) => any}
 */
function _getExtractorFrom(criterion) {
    if (criterion === undefined || criterion === null) {
        return (element) => element;
    }
    switch (typeof criterion) {
        case "string":
            return (element) => element[criterion];
        case "function":
            return criterion;
        default:
            throw new Error(
                `Expected criterion of type 'string' or 'function' and got '${typeof criterion}'`,
            );
    }
}

/**
 * @template T
 * @param {T | Iterable<T>} [value]
 * @returns {T[]}
 */
export function ensureArray(value) {
    return isIterable(value)
        ? [.../** @type {Iterable<T>} */ (value)]
        : [/** @type {T} */ (value)];
}

/**
 * @template T
 * @param {Iterable<T>} iter1
 * @param {Iterable<T>} iter2
 * @returns {T[]}
 */
export function intersection(iter1, iter2) {
    const s2 = new Set(iter2);
    return [...new Set(iter1)].filter((x) => s2.has(x));
}

/**
 * @param {unknown} value
 * @returns {boolean}
 */
export function isIterable(value) {
    return Boolean(value && typeof value === "object" && Symbol.iterator in value);
}

/**
 * @template T
 * @template {string | number | symbol} K
 * @param {Iterable<T>} iterable
 * @param {Criterion<T, K>} [criterion]
 * @returns {Record<K, T[]>}
 */
export function groupBy(iterable, criterion) {
    const extract = _getExtractorFrom(criterion);
    return /** @type {Record<K, T[]>} */ (
        Object.groupBy(iterable, (element) => String(extract(element)))
    );
}

/**
 * @template T
 * @template {string | number | symbol} K
 * @param {Iterable<T>} iterable
 * @param {Criterion<T, K>} [criterion]
 * @param {"asc" | "desc"} [order="asc"]
 * @returns {T[]}
 */
export function sortBy(iterable, criterion, order = "asc") {
    const extract = _getExtractorFrom(criterion);
    const sign = order === "asc" ? 1 : -1;
    return [...iterable]
        .map((el) => ({ el, key: extract(el) }))
        .sort((x, y) => {
            const a = x.key;
            const b = y.key;
            let result;
            if (typeof a === "number" && typeof b === "number") {
                const aNaN = Number.isNaN(a);
                const bNaN = Number.isNaN(b);
                result = aNaN || bNaN ? Number(aNaN) - Number(bNaN) : a - b;
            } else {
                result = a > b ? 1 : a < b ? -1 : 0;
            }
            return sign * result;
        })
        .map((x) => x.el);
}

/**
 * @template T
 * @param {Iterable<T>} iter1
 * @param {Iterable<T>} iter2
 * @returns {T[]}
 */
export function symmetricalDifference(iter1, iter2) {
    const set1 = new Set(iter1);
    const set2 = new Set(iter2);
    return [...set1.symmetricDifference(set2)];
}

/**
 * @template T
 * @param {...T[]} args
 * @returns {(T | T[] | undefined)[]}
 */
export function cartesian(...args) {
    if (!args.length) {
        return [undefined];
    } else if (args.length === 1) {
        return [...args[0]];
    } else {
        return _cartesian(...args);
    }
}

/**
 * @template T
 * @param {Iterable<T>} iterable
 * @returns {T[][]}
 */
export function sections(iterable) {
    const array = [...iterable];
    const result = [];
    for (let i = 0; i < array.length + 1; i++) {
        result.push(array.slice(0, i));
    }
    return result;
}

/**
 * @template T
 * @param {Iterable<T>} iterable
 * @returns {T[]}
 */
export function unique(iterable) {
    return [...new Set(iterable)];
}

/**
 * @template T1, T2
 * @param {Iterable<T1>} iter1
 * @param {Iterable<T2>} iter2
 * @param {boolean} [fill=false]
 * @returns {[T1, T2][]}
 */
export function zip(iter1, iter2, fill = false) {
    const array1 = [...iter1];
    const array2 = [...iter2];
    /** @type {[T1, T2][]} */
    const result = [];
    const getLength = fill ? Math.max : Math.min;
    for (let i = 0; i < getLength(array1.length, array2.length); i++) {
        result.push([array1[i], array2[i]]);
    }
    return result;
}

/**
 * @template T1, T2, T
 * @param {Iterable<T1>} iter1
 * @param {Iterable<T2>} iter2
 * @param {(e1: T1, e2: T2) => T} mapFn
 * @returns {T[]}
 */
export function zipWith(iter1, iter2, mapFn) {
    return zip(iter1, iter2).map(([e1, e2]) => mapFn(e1, e2));
}
/**
 * @template T
 * @param {T[]} arr
 * @param {number} width
 * @returns {T[][]}
 */
export function slidingWindow(arr, width) {
    const res = [];
    for (let i = 0; i <= arr.length - width; i++) {
        res.push(arr.slice(i, i + width));
    }
    return res;
}

/**
 * @param {number} i
 * @param {any[]} arr
 * @param {number} [inc]
 * @returns {number}
 */
export function rotate(i, arr, inc = 1) {
    if (!arr.length) {
        throw new Error("Cannot rotate on an empty array");
    }
    return (((i + inc) % arr.length) + arr.length) % arr.length;
}
