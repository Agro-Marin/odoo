// @ts-check
/** @odoo-module native */

import { formatFieldFloat } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { clamp } from "@web/core/utils/format/numbers";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { isFalseEmpty } from "@web/fields/field_utils";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class PercentPieField extends FieldComponent {
    static template = "web.PercentPieField";
    static props = {
        ...standardFieldProps,
        string: { type: String, optional: true },
    };

    /** @returns {string} */
    get formattedValue() {
        return formatFieldFloat(this.field.value, {
            trailingZeros: false,
        });
    }

    /**
     * @returns {number}
     */
    get pieValue() {
        return clamp(this.field.value || 0, 0, 100);
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const percentPieField = {
    component: PercentPieField,
    displayName: _t("PercentPie"),
    supportedTypes: ["float", "integer"],
    isEmpty: isFalseEmpty,
    additionalClasses: ["o_field_percent_pie"],
    extractProps: ({ string }) => ({ string }),
};

registerField("percentpie", percentPieField);
