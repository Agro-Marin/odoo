// @ts-check
/** @odoo-module native */

/** @module @web/webclient/reload_company_service */

import { browser } from "@web/core/browser/browser";
import { onModelMutation } from "@web/core/network/model_mutation";
import { registry } from "@web/core/registry";

export const reloadCompanyService = {
    dependencies: ["action"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ action: ReturnType<typeof import("@web/webclient/actions/action_service").actionService.start> }} services
     */
    start(env, { action }) {
        onModelMutation(
            ["res.company"],
            () => {
                if (browser.localStorage.getItem("running_tour")) {
                    return;
                }
                Promise.resolve(action.doAction("reload_context")).catch(console.warn);
            },
            { successOnly: true },
        );
    },
};

registry.category("services").add("reloadCompany", reloadCompanyService);
