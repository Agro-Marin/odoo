// @ts-check

const cleanups = [];

/**
 * @param {Function} callback
 */
export function registerCleanup(callback) {
    cleanups.push(callback);
}
