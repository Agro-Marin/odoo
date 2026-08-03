// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { formatFloat } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { clamp } from "@web/core/utils/format/numbers";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class PercentPieField extends Component {
    static template = "web.PercentPieField";
    static props = {
        ...standardFieldProps,
        string: { type: String, optional: true },
    };

    /** @returns {string} */
    get formattedValue() {
        return formatFloat(this.props.record.data[this.props.name], {
            trailingZeros: false,
        });
    }

    /**
     * @returns {number}
     */
    get pieValue() {
        return clamp(this.props.record.data[this.props.name] || 0, 0, 100);
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const percentPieField = {
    component: PercentPieField,
    displayName: _t("PercentPie"),
    supportedTypes: ["float", "integer"],
    additionalClasses: ["o_field_percent_pie"],
    extractProps: ({ string }) => ({ string }),
};

registerField("percentpie", percentPieField);
