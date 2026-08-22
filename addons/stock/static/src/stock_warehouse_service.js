/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { onModelMutation } from "@web/core/network";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";

export class StockWarehouseService {
    constructor(action) {
        this.reloadContext = debounce(() => action.doAction("reload_context"), 300);
        this._dispose = onModelMutation(
            ["stock.warehouse"],
            () => {
                if (!browser.localStorage.getItem("running_tour")) {
                    this.reloadContext();
                }
            },
            { successOnly: true },
        );
    }

    destroy() {
        this._dispose();
        this.reloadContext.cancel();
    }
}

export const stockWarehouseService = {
    dependencies: ["action"],
    start(env, { action }) {
        return new StockWarehouseService(action);
    },
};

registry.category("services").add("stock_warehouse", stockWarehouseService);
