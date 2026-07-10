// @ts-check

// Cleanup

const cleanups = [];

/**
 * Register a cleanup callback for when the current test ends.
 *
 * - executed in reverse order
 * - executed even if the test fails/crashes
 *
 * @param {Function} callback
 */
export function registerCleanup(callback) {
    cleanups.push(callback);
}
