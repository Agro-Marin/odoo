// @ts-check
/** @odoo-module native */

import { formatJson } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class JsonField extends FieldComponent {
    static template = "web.JsonField";
    static props = {
        ...standardFieldProps,
    };

    /** @returns {string} */
    get formattedValue() {
        return formatJson(this.field.value);
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const jsonField = {
    component: JsonField,
    displayName: _t("Json"),
    supportedTypes: ["json"],
};

registerField("json", jsonField);
