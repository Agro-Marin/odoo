/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

const errorHandlerRegistry = registry.category("error_handlers");

const log = makeLogger("website.service.beforeunload_error_handler");

let isUnloadingPage = false;
window.addEventListener("beforeunload", () => {
    isUnloadingPage = true;
    log.lifecycle("beforeunload: unloading flag set for 10s");
    browser.setTimeout(() => (isUnloadingPage = false), 10000);
});

/**
 * @param {OdooEnv} env
 * @param {UncaughError} error
 * @returns {boolean}
 */
function beforeUnloadHandler(env, error) {
    if (isUnloadingPage) {
        log.logic("error swallowed while page unloads", () => ({
            error: error?.message,
        }));
        error.event.preventDefault();
        return true;
    }
    return false;
}

errorHandlerRegistry.add("beforeUnloadHandler", beforeUnloadHandler, { sequence: 1 });
