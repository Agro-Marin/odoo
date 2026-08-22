// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { BooleanField, booleanField } from "@web/fields/basic/boolean/boolean_field";
import { autosaveOption } from "@web/fields/field_options";
import { extractAutosave } from "@web/fields/field_utils";

export class BooleanToggleField extends BooleanField {
    static template = "web.BooleanToggleField";
    static props = {
        ...BooleanField.props,
        autosave: { type: Boolean, optional: true },
    };
    static defaultProps = {
        ...BooleanField.defaultProps,
        autosave: true,
    };

    /**
     * @param {boolean} newValue
     * @returns {Promise<void>}
     */
    async onChange(newValue) {
        this.state.value = newValue;
        const changes = { [this.props.name]: newValue };
        try {
            await this.props.record.update(changes, { save: this.props.autosave });
        } catch (error) {
            this.state.value = this.field.value;
            throw error;
        }
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const booleanToggleField = {
    ...booleanField,
    component: BooleanToggleField,
    displayName: _t("Toggle"),
    interactiveOutsideEdition: true,
    supportedOptions: [autosaveOption()],
    extractProps({ options }, dynamicInfo) {
        return {
            autosave: extractAutosave(options),
        };
    },
};

registerField("boolean_toggle", booleanToggleField);
