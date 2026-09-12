// @ts-check

/** @type {(callback: () => void | Promise<void>) => void} */
let cleanupHook = () => {};

/** @param {(callback: () => void | Promise<void>) => void} hook */
export function bindCleanupHook(hook) {
    cleanupHook = hook;
}

/** @param {() => void | Promise<void>} callback */
export function registerCleanup(callback) {
    cleanupHook(callback);
}
