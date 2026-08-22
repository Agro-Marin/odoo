// @ts-check
/** @odoo-module native */

import { registerField } from "@web/fields/_registry";

import { BooleanToggleField, booleanToggleField } from "./boolean_toggle_field.js";
export class ListBooleanToggleField extends BooleanToggleField {
    static template = "web.ListBooleanToggleField";

    async onClick() {
        if (!this.props.readonly && this.props.record.isInEdition) {
            const changes = {
                [this.props.name]: !this.field.value,
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
