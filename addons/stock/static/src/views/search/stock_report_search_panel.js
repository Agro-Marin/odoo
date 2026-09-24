/** @odoo-module native */
import { useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useSearchModel } from "@web/search/search_model";
import { SearchPanel } from "@web/search/search_panel/search_panel";

export class StockReportSearchPanel extends SearchPanel {
    static template = "stock.StockReportSearchPanel";
    setup() {
        super.setup(...arguments);
        this.searchModel = useSearchModel();
        this.ui = useService("ui");
        this.selectedWarehouse = useState({
            value: this.searchModel.globalContext.warehouse_id || false,
        });
    }

    get warehouses() {
        return this.searchModel.getWarehouses();
    }

    clearWarehouseContext() {
        this.searchModel.clearWarehouseContext();
        this.selectedWarehouse.value = null;
    }

    applyWarehouseContext(warehouse_id) {
        this.searchModel.applyWarehouseContext(warehouse_id);
        this.selectedWarehouse.value = warehouse_id;
    }
}
