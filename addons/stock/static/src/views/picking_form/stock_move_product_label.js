/** @odoo-module native */
import { ProductNameAndDescriptionField } from "@product/product_name_and_description/product_name_and_description";
import { isTerminalState } from "@stock/utils/stock_state";
import { registry } from "@web/core/registry";
import { many2OneField } from "@web/fields/relational/many2one";

export class MoveProductLabelField extends ProductNameAndDescriptionField {
    static template = "stock.MoveProductLabelField";
    static descriptionColumn = "description_picking";

    get label() {
        const record = this.props.record.data;
        let label = record[this.descriptionColumn];
        if (label === this.productName) {
            label = "";
        }
        return (label || "").trim();
    }
    get isDescriptionReadonly() {
        return (
            this.props.readonly &&
            isTerminalState(this.props.record.evalContext.parent?.state)
        );
    }
    get showLabelVisibilityToggler() {
        return (
            !this.isDescriptionReadonly && this.columnIsProductAndLabel && !this.label
        );
    }
    parseLabel(value) {
        return value;
    }
}

export const moveProductLabelField = {
    ...many2OneField,
    component: MoveProductLabelField,
};
registry.category("fields").add("move_product_label_field", moveProductLabelField);
