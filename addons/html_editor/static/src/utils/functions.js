/** @odoo-module native */
/**
 * @template T, U
 * @param {(arg: T) => U} func
 * @returns {(arg: T) => U}
 */
export function weakMemoize(func) {
    const cache = new WeakMap();
    const funcName = func.name ? func.name + " (memoized)" : "memoized";
    return {
        [funcName](firstArg, ...args) {
            if (!cache.has(firstArg)) {
                cache.set(firstArg, func(firstArg, ...args));
            }
            return cache.get(firstArg);
        },
    }[funcName];
}
