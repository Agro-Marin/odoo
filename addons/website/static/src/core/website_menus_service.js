/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

const log = makeLogger("website.service.menus");

export const websiteMenusService = {
    start() {
        const updateCallbacks = new Set();
        return {
            updateCallbacks,
            registerCallback(fn) {
                updateCallbacks.add(fn);
                log.lifecycle("registerCallback", () => ({
                    callbacks: updateCallbacks.size,
                }));
                return () => {
                    log.lifecycle("unregisterCallback", () => ({
                        callbacks: updateCallbacks.size,
                    }));
                    return updateCallbacks.delete(fn);
                };
            },
            triggerCallbacks() {
                log.pipeline("triggerCallbacks", () => ({
                    callbacks: updateCallbacks.size,
                }));
                for (const callback of updateCallbacks) {
                    callback();
                }
            },
        };
    },
};

registry.category("services").add("website_menus", websiteMenusService);
