/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { onModelMutation } from "@web/core/network";
import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";

/**
 * Reloads the web client's context after a warehouse changes.
 *
 * Warehouse records drive menus, action domains and the multi-warehouse group,
 * none of which the client recomputes on its own -- so a change has to be
 * followed by a context reload. Debounced because a settings save writes several
 * warehouses in one transaction.
 */
export class StockWarehouseService {
    constructor(action) {
        this.reloadContext = debounce(() => action.doAction("reload_context"), 300);
        this._dispose = onModelMutation(
            ["stock.warehouse"],
            () => {
                // A tour drives its own navigation; reloading under it would
                // discard the step it is in the middle of.
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
