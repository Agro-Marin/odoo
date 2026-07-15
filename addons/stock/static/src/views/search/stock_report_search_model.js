/** @odoo-module native */
import { SearchModel } from "@web/search/search_model";

export class StockReportSearchModel extends SearchModel {

    setup() {
        super.setup(...arguments);
        // Ensure getWarehouses() never returns undefined if load() fails/hasn't run.
        this.warehouses = [];
    }

    async load() {
        await super.load(...arguments);
        await this._loadWarehouses();
      }


    //---------------------------------------------------------------------
    // Actions / Getters
    //---------------------------------------------------------------------

    getWarehouses() {
        return this.warehouses;
    }

    async _loadWarehouses() {
        this.warehouses = await this.orm.call(
            'stock.warehouse',
            'get_current_warehouses',
            [[]],
            { context: this.context },
        );
    }

    /**
     * Clears the warehouse context so values compute across all warehouses.
     */
    clearWarehouseContext() {
        delete this.globalContext.warehouse_id;
        this._notify();
    }

    /**
     * Sets the context to the selected warehouse so dependent values recalculate for
     * it, without filtering out any records.
     * @param {number} warehouse_id
     */
    applyWarehouseContext(warehouse_id) {
        this.globalContext['warehouse_id'] = warehouse_id;
        this._notify();
    }
}
