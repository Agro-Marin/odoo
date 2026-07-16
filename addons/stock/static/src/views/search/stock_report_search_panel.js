/** @odoo-module native */
import { useState } from "@odoo/owl";
import { SearchPanel } from "@web/search/search_panel/search_panel";

export class StockReportSearchPanel extends SearchPanel {
    static template = "stock.StockReportSearchPanel";
    setup() {
        super.setup(...arguments);
        // Self-driven reactive highlight state (mirrors StockOrderpointSearchPanel)
        // instead of relying on a searchModel._notify() side-effect to re-render.
        this.selectedWarehouse = useState({ value: false });
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
