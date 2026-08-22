// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { onModelMutation } from "@web/core/network/model_mutation";
import { registry } from "@web/core/registry";

class ReloadCompanyService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ action: any }} services
     */
    constructor(env, { action }) {
        this.env = env;
        this.action = action;
        this.stopWatching = onModelMutation(
            ["res.company"],
            () => this.onCompanyMutation(),
            { successOnly: true },
        );
    }

    onCompanyMutation() {
        if (browser.localStorage.getItem("running_tour")) {
            return;
        }
        Promise.resolve(this.action.doAction("reload_context")).catch(console.warn);
    }

    destroy() {
        this.stopWatching();
        this.stopWatching = () => {};
    }
}

const reloadCompanyService = {
    dependencies: ["action"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ action: any }} services
     * @returns {ReloadCompanyService}
     */
    start(env, services) {
        return new ReloadCompanyService(env, services);
    },
};

registry.category("services").add("reloadCompany", reloadCompanyService);
