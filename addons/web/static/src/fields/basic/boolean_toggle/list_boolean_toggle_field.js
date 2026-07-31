// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/boolean_toggle/list_boolean_toggle_field */

import { registerField } from "@web/fields/_registry";

import { BooleanToggleField, booleanToggleField } from "./boolean_toggle_field.js";
export class ListBooleanToggleField extends BooleanToggleField {
    static template = "web.ListBooleanToggleField";

    async onClick() {
        if (!this.props.readonly && this.props.record.isInEdition) {
            const changes = {
                [this.props.name]: !this.props.record.data[this.props.name],
            };
            await this.props.record.update(changes, {
                save: this.props.autosave,
            });
        }
    }
}

export const listBooleanToggleField = {
    ...booleanToggleField,
    component: ListBooleanToggleField,
};

registerField({ name: "boolean_toggle", view: "list" }, listBooleanToggleField);
