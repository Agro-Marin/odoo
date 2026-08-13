/** @odoo-module native */
import { Component } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";

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
