// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/boolean_toggle/boolean_toggle_field - Toggle switch field widget for Boolean columns */

import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { BooleanField, booleanField } from "@web/fields/basic/boolean/boolean_field";
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

    /** @param {boolean} newValue @returns {Promise<void>} */
    async onChange(newValue) {
        this.state.value = newValue;
        const changes = { [this.props.name]: newValue };
        try {
            await this.props.record.update(changes, { save: this.props.autosave });
        } catch (error) {
            // Same rollback as BooleanField.onChange: a rejected update never
            // re-fires the observer, so resync the optimistic mirror.
            this.state.value = this.props.record.data[this.props.name];
            throw error;
        }
    }
}

export const booleanToggleField = {
    ...booleanField,
    component: BooleanToggleField,
    displayName: _t("Toggle"),
    supportedOptions: [
        {
            label: _t("Autosave"),
            name: "autosave",
            type: "boolean",
            default: true,
            help: _t(
                "If checked, the record will be saved immediately when the field is modified.",
            ),
        },
    ],
    extractProps({ options }, dynamicInfo) {
        return {
            autosave: extractAutosave(options),
            readonly: dynamicInfo.readonly,
        };
    },
};

registerField("boolean_toggle", booleanToggleField);
