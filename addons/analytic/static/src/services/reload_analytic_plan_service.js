// @ts-check
/** @odoo-module native */

/** @module @analytic/services/reload_analytic_plan_service - Service that triggers a page reload when account.analytic.plan records are modified */

import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { UPDATE_METHODS } from "@web/services/orm_service";

// reload the page if changes are being done to `account.analytic.plan`
//
// The views need to include the newly created field on `account.analytic.line`
// and other models inheriting `analytic.plan.fields.mixin`.
// This is based on the same service for `res.company`: `reloadCompany`.

export const reloadAnalyticPlanService = {
    dependencies: ["action"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ action: ReturnType<typeof import("@web/webclient/actions/action_service").actionService.start> }} services
     */
    start(env, { action }) {
        rpcBus.addEventListener(RpcEvent.RESPONSE, (ev) => {
            // Defensive: malformed payloads (null detail, missing data) can be
            // dispatched to the global rpcBus by tests or by synthetic fires.
            // Destructuring ``ev.detail`` directly throws when detail is null.
            if (!ev.detail?.data?.params) {
                return;
            }
            const { data, error } = ev.detail;
            const { model, method } = data.params;
            if (
                !error &&
                model === "account.analytic.plan" &&
                UPDATE_METHODS.includes(method)
            ) {
                if (!browser.localStorage.getItem("running_tour")) {
                    action.doAction("reload_context");
                }
            }
        });
    },
};

registry.category("services").add("reloadAnalyticPlan", reloadAnalyticPlanService);
