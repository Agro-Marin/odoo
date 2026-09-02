/** @odoo-module native */
import { registry } from "@web/core/registry";
import {
    ListBooleanToggleField,
    listBooleanToggleField,
} from "@web/fields/basic/boolean_toggle";

export class ListBooleanToggleLoadField extends ListBooleanToggleField {
    async onChange(newValue) {
        this.state.value = newValue;
        const changes = {
            [this.props.name]: newValue,
            technical_is_new_default: newValue,
        };
        await this.props.record.update(changes, { save: this.props.autosave });
    }
}

export const listBooleanToggleLoadField = {
    ...listBooleanToggleField,
    component: ListBooleanToggleLoadField,
};

registry.category("fields").add("boolean_toggle_load", listBooleanToggleLoadField);
