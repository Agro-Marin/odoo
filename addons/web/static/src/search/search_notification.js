// @ts-check
/** @odoo-module native */

/**
 * @param {Promise<void> | void} notification
 */
export function fireAndForgetNotify(notification) {
    Promise.resolve(notification).catch((error) => {
        console.error(
            "[search] a search-model notification failed after a " +
                "synchronous creator; the model may be showing stale " +
                "facets or sections:",
            error,
        );
    });
}
