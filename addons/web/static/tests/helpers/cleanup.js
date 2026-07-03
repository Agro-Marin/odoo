// @ts-check

// -----------------------------------------------------------------------------
// Cleanup
// -----------------------------------------------------------------------------

const cleanups = [];

/**
 * Register a cleanup callback that will be executed whenever the current test
 * is done.
 *
 * - the cleanups will be executed in reverse order
 * - they will be executed even if the test fails/crashes
 *
 * @param {Function} callback
 */
export function registerCleanup(callback) {
    cleanups.push(callback);
}
