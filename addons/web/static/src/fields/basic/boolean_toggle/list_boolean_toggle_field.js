// @ts-check
/** @odoo-module native */

import { registerField } from "@web/fields/_registry";

import { BooleanToggleField, booleanToggleField } from "./boolean_toggle_field.js";
export class ListBooleanToggleField extends BooleanToggleField {
    static template = "web.ListBooleanToggleField";

    async onClick() {
        if (!this.props.readonly && this.props.record.isInEdition) {
            await this.onChange(!this.field.value);
        }
    }
}

export const listBooleanToggleField = {
    ...booleanToggleField,
    component: ListBooleanToggleField,
};

registerField({ name: "boolean_toggle", view: "list" }, listBooleanToggleField);
