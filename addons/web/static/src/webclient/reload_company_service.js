// @ts-check
/** @odoo-module native */

/** @module @web/webclient/reload_company_service - Service that triggers a page reload when res.company records are modified */

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { onModelMutation } from "@web/services/orm_service";

export const reloadCompanyService = {
    dependencies: ["action"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ action: ReturnType<typeof import("@web/webclient/actions/action_service").actionService.start> }} services
     */
    start(env, { action }) {
        // ``successOnly``: unlike the cache-invalidation consumers, the reaction
        // here is a full page reload, which discards whatever the user was
        // editing. Reacting to a write whose response was merely LOST would
        // trade a possibly-stale context for possibly-destroyed input — so this
        // one deliberately fires on confirmed success only.
        onModelMutation(
            ["res.company"],
            () => {
                if (browser.localStorage.getItem("running_tour")) {
                    return;
                }
                // Fire-and-forget: a superseded or failing reload must not
                // surface as an unhandled rejection.
                Promise.resolve(action.doAction("reload_context")).catch(console.warn);
            },
            { successOnly: true },
        );
    },
};

registry.category("services").add("reloadCompany", reloadCompanyService);
