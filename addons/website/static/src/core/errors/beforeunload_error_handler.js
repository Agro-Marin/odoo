/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

const errorHandlerRegistry = registry.category("error_handlers");

let isUnloadingPage = false;
window.addEventListener("beforeunload", () => {
    isUnloadingPage = true;
    browser.setTimeout(() => (isUnloadingPage = false), 10000);
});

/**
 * @param {OdooEnv} env
 * @param {UncaughError} error
 * @returns {boolean}
 */
function beforeUnloadHandler(env, error) {
    if (isUnloadingPage) {
        error.event.preventDefault();
        return true;
    }
    return false;
}

errorHandlerRegistry.add("beforeUnloadHandler", beforeUnloadHandler, { sequence: 1 });
