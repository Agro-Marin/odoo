/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { onModelMutation } from "@web/core/network";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";

registry.category("services").add("stock_warehouse", {
    dependencies: ["action"],
    start(env, { action }) {
        const reloadContext = debounce(() => action.doAction("reload_context"), 300);
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
