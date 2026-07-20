// @ts-check
/** @odoo-module native */

/** @module @web/webclient/reload_company_service - Service that triggers a page reload when res.company records are modified */

import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { UPDATE_METHODS } from "@web/services/orm_service";

export const reloadCompanyService = {
    dependencies: ["action"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ action: ReturnType<typeof import("@web/webclient/actions/action_service").actionService.start> }} services
     */
    start(env, { action }) {
        rpcBus.addEventListener(RpcEvent.RESPONSE, (ev) => {
            // Defensive: malformed payloads (null detail, missing data) can
            // be dispatched to the global rpcBus by tests or synthetic fires;
            // destructuring ``ev.detail`` directly would throw, so optional-chain
            // first.
            if (!ev.detail?.data?.params) {
                return;
            }
            const { data, error } = ev.detail;
            const { model, method } = data.params;
            if (!error && model === "res.company" && UPDATE_METHODS.includes(method)) {
                if (!browser.localStorage.getItem("running_tour")) {
                    action.doAction("reload_context");
                }
            }
        });
    },
};

registry.category("services").add("reloadCompany", reloadCompanyService);
