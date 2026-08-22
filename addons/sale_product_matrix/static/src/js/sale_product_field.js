/** @odoo-module native */
import { useMatrixConfigurator } from "@product_matrix/js/matrix_configurator_hook";
import {
    SaleOrderLineProductField,
    saleOrderLineProductField,
} from "@sale/js/sale_product_field";
import { patch } from "@web/core/utils/patch";

patch(SaleOrderLineProductField.prototype, {
    setup() {
        super.setup(...arguments);
        this.matrixConfigurator = useMatrixConfigurator();
    },

    async _openGridConfigurator(edit = false) {
        return this.matrixConfigurator.open(this.props.record, edit);
    },

    async _openProductConfigurator(edit = false, selectedComboItems = []) {
        if (edit && this.props.record.data.product_add_mode === "matrix") {
            // Awaited, like every other branch of the product cascade: `_selectProduct`
            // runs the cascade inside `trackCompoundUpdate` so the model cannot settle
            // on a half-applied line, and a branch that is only started escapes it.
            return this._openGridConfigurator(true);
        }
        return super._openProductConfigurator(edit, selectedComboItems);
    },
});

Object.assign(saleOrderLineProductField, {
    fieldDependencies: [
        ...saleOrderLineProductField.fieldDependencies,
        { name: "product_add_mode", type: "selection" },
    ],
});
