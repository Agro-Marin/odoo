/** @odoo-module native */
import { useState } from "@odoo/owl";
import { SearchPanel } from "@web/search/search_panel/search_panel";

export class StockReportSearchPanel extends SearchPanel {
    static template = "stock.StockReportSearchPanel";
    setup() {
        super.setup(...arguments);
        // Self-driven reactive highlight state (mirrors StockOrderpointSearchPanel)
        // instead of relying on a searchModel._notify() side-effect to re-render.
        // Initialized from the search model's persisted context so the highlight
        // survives remounts (e.g. coming back from a form view) instead of
        // desyncing from the still-applied warehouse filter.
        this.selectedWarehouse = useState({
            value: this.env.searchModel.globalContext.warehouse_id || false,
        });
    }

    //---------------------------------------------------------------------
    // Actions / Getters
    //---------------------------------------------------------------------

    get warehouses() {
        return this.env.searchModel.getWarehouses();
    }

    clearWarehouseContext() {
        this.env.searchModel.clearWarehouseContext();
        this.selectedWarehouse.value = null;
    }

    applyWarehouseContext(warehouse_id) {
        this.env.searchModel.applyWarehouseContext(warehouse_id);
        this.selectedWarehouse.value = warehouse_id;
    }
}
