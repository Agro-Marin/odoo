/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { onModelMutation } from "@web/core/network";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";

registry.category("services").add("stock_warehouse", {
    dependencies: ["action"],
    start(env, { action }) {
        // Coalesce bursts of warehouse writes into a single context reload — a flow
        // that writes stock.warehouse several times in quick succession should not
        // trigger a full reload per response.
        const reloadContext = debounce(() => action.doAction("reload_context"), 300);
        // ``successOnly``: same reasoning as ``reload_analytic_plan`` — a context
        // reload is disruptive, so keep the previous ``!error`` semantics.
        const dispose = onModelMutation(
            ["stock.warehouse"],
            () => {
                if (!browser.localStorage.getItem("running_tour")) {
                    reloadContext();
                }
            },
            { successOnly: true },
        );
        return {
            destroy() {
                dispose();
                reloadContext.cancel();
            },
        };
    },
});
