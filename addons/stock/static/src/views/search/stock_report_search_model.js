/** @odoo-module native */
import { SearchModel } from "@web/search/search_model";

export class StockReportSearchModel extends SearchModel {
    setup() {
        super.setup(...arguments);
        this.warehouses = [];
    }

    async load() {
        await super.load(...arguments);
        await this._loadWarehouses();
    }

    getWarehouses() {
        return this.warehouses;
    }

    async _loadWarehouses() {
        try {
            this.warehouses = await this.orm.call(
                "stock.warehouse",
                "get_current_warehouses",
                [],
                { context: this.context },
            );
        } catch (error) {
            console.warn("[stock] could not load the warehouse filter:", error);
            this.warehouses = [];
        }
    }

    clearWarehouseContext() {
        delete this.globalContext.warehouse_id;
        this._notify();
    }

    applyWarehouseContext(warehouse_id) {
        this.globalContext["warehouse_id"] = warehouse_id;
        this._notify();
    }
}
