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
     * @returns {{ save: boolean }}
     */
    get updateOptions() {
        return { save: this.props.autosave };
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
