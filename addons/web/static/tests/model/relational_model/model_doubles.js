// @ts-check
/** @odoo-module native */

export const MODEL_LIFECYCLE_PROTO = {
    get lifecycleHooks() {
        return /** @type {any} */ (this).hooks.lifecycle;
    },
    get uiHooks() {
        return /** @type {any} */ (this).hooks.ui;
    },
    /**
     * @param {string} name
     * @param {...any} args
     * @returns {Promise<any>}
     */
    async notifyLifecycle(name, ...args) {
        return /** @type {any} */ (this).lifecycleHooks[name](...args);
    },
    /**
     * @param {string} name
     * @param {...any} args
     * @returns {any}
     */
    notifyLifecycleSync(name, ...args) {
        return /** @type {any} */ (this).lifecycleHooks[name](...args);
    },
};
