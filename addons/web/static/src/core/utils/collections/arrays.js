// @ts-check
/** @odoo-module native */

/**
 * @template T
 * @template K
 * @typedef {string | ((item: T) => K) | null} Criterion
 */

/**
 * @template T
 * @param {ReadonlyArray<T>[]} args
 * @returns {(T[] | undefined)[]}
 */
function _cartesian(...args) {
    if (!args.length) {
        return [undefined];
    }
    const firstArray = /** @type {ReadonlyArray<T>} */ (args.shift()).map((elem) => [
        elem,
    ]);
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
 * @template K
 * @param {Criterion<T, K>} [criterion]
 * @returns {(element: T) => any}
 */
function _getExtractorFrom(criterion) {
    if (criterion === undefined || criterion === null) {
        return (element) => element;
    }
    switch (typeof criterion) {
        case "string":
            return (element) =>
                /** @type {Record<string, unknown>} */ (element)[criterion];
        case "function":
            return criterion;
        default:
            throw new Error(
                `Expected criterion of type 'string' or 'function' and got '${typeof criterion}'`,
            );
    }
}

/**
 * @overload
 * @returns {undefined[]}
 */
/**
 * @template T
 * @overload
 * @param {T} value
 * @returns {(T extends string ? T : T extends Iterable<infer U> ? U : T)[]}
 */
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
 * @template T, U
 * @param {Iterable<T>} iter1
 * @param {Iterable<U>} iter2
 * @returns {(T & U)[]}
 */
export function intersection(iter1, iter2) {
    /** @type {Set<unknown>} */
    const s2 = new Set(iter2);
    return /** @type {(T & U)[]} */ ([...new Set(iter1)].filter((x) => s2.has(x)));
}

/**
 * @param {unknown} value
 * @returns {boolean}
 */
export function isIterable(value) {
    return Boolean(value && typeof value === "object" && Symbol.iterator in value);
}

/**
 * @template K
 * @typedef {K extends string | number | bigint | boolean | null | undefined ? `${K}` : string} GroupKey
 */

/**
 * Keys are stringified, including symbols, and groups absent from the input are absent from the result.
 * @template T, K
 * @param {Iterable<T>} iterable
 * @param {Criterion<T, K>} [criterion]
 * @returns {Partial<Record<GroupKey<K>, T[]>>}
 */
export function groupBy(iterable, criterion) {
    const extract = _getExtractorFrom(criterion);
    return /** @type {Partial<Record<GroupKey<K>, T[]>>} */ (
        Object.groupBy(iterable, (element) => String(extract(element)))
    );
}

/**
 * @template T, K
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
 * @template T, U
 * @param {Iterable<T>} iter1
 * @param {Iterable<U>} iter2
 * @returns {(T | U)[]}
 */
export function symmetricalDifference(iter1, iter2) {
    const set1 = new Set(iter1);
    const set2 = new Set(iter2);
    return [...set1.symmetricDifference(set2)];
}

/**
 * Known input counts preserve the zero-input sentinel, flat single input, or
 * tuple positions. A dynamic input list can take any of those runtime branches.
 * @template {readonly (readonly unknown[])[]} A
 * @typedef {number extends A["length"]
 *  ? (A[number][number] | A[number][number][] | undefined)[]
 *  : A extends readonly [] ? undefined[]
 *  : A extends readonly [readonly (infer T)[]] ? T[]
 *  : { -readonly [K in keyof A]: A[K][number] }[]} CartesianResult
 */

/**
 * @template {readonly (readonly unknown[])[]} A
 * @overload
 * @param {...A} args
 * @returns {CartesianResult<A>}
 */
/**
 * @param {ReadonlyArray<unknown>[]} args
 * @returns {unknown[]}
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
 * With padding, either side may be absent when the iterables differ in length.
 * @template T1, T2
 * @overload
 * @param {Iterable<T1>} iter1
 * @param {Iterable<T2>} iter2
 * @param {false} [fill]
 * @returns {[T1, T2][]}
 */
/**
 * @template T1, T2
 * @overload
 * @param {Iterable<T1>} iter1
 * @param {Iterable<T2>} iter2
 * @param {boolean} fill
 * @returns {[T1 | undefined, T2 | undefined][]}
 */
/**
 * @template T1, T2
 * @param {Iterable<T1>} iter1
 * @param {Iterable<T2>} iter2
 * @param {boolean} [fill=false]
 * @returns {[T1 | undefined, T2 | undefined][]}
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
 * @param {ReadonlyArray<T>} arr
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
 * @param {ReadonlyArray<unknown>} arr
 * @param {number} [inc]
 * @returns {number}
 */
export function rotate(i, arr, inc = 1) {
    if (!arr.length) {
        throw new Error("Cannot rotate on an empty array");
    }
    return (((i + inc) % arr.length) + arr.length) % arr.length;
}
