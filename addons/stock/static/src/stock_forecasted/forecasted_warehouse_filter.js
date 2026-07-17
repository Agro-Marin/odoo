/** @odoo-module native */
import { Component } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";

export class ForecastedWarehouseFilter extends Component {
    static template = "stock.ForecastedWarehouseFilter";
    static components = { Dropdown, DropdownItem };
    static props = {
        action: Object,
        setWarehouseInContext: Function,
        warehouses: Array,
    };

    setup() {
        this.context = this.props.action.context;
    }

    get warehouses() {
        return this.props.warehouses;
    }

    get displayWarehouseFilter() {
        return this.warehouses.length > 1;
    }

    _onSelected(id) {
        this.props.setWarehouseInContext(Number(id));
    }

    get activeWarehouse() {
        // Fall back to the first warehouse when the context id is stale (e.g.
        // deleted warehouse or leftover context from another company).
        const active =
            this.context.warehouse_id &&
            this.warehouses.find((w) => w.id === this.context.warehouse_id);
        return active || this.warehouses[0];
    }

    get warehousesItems() {
        return this.warehouses.map((warehouse) => ({
            id: warehouse.id,
            label: warehouse.name,
            onSelected: () => this._onSelected(warehouse.id),
        }));
    }
}
