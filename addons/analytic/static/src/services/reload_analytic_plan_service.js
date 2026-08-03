// @ts-check
/** @odoo-module native */

/** @module @analytic/services/reload_analytic_plan_service - Service that triggers a page reload when account.analytic.plan records are modified */

import { browser } from "@web/core/browser/browser";
import { onModelMutation } from "@web/core/network";
import { registry } from "@web/core/registry";

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
        // ``successOnly``: the reaction is a full context reload, which is
        // disruptive rather than merely costly — the opt-out the shared helper
        // documents. Preserves the previous ``!error`` test exactly.
        const dispose = onModelMutation(
            ["account.analytic.plan"],
            () => {
                if (!browser.localStorage.getItem("running_tour")) {
                    action.doAction("reload_context");
                }
            },
            { successOnly: true },
        );
        return { destroy: dispose };
    },
};

registry.category("services").add("reloadAnalyticPlan", reloadAnalyticPlanService);
