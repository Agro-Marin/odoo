// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { clamp } from "@web/core/utils/format/numbers";
import { registerField } from "@web/fields/_registry";
import { formatFloat } from "@web/fields/formatters";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class PercentPieField extends Component {
    static template = "web.PercentPieField";
    static props = {
        ...standardFieldProps,
        string: { type: String, optional: true },
    };

    /** @returns {string} Value formatted to 2 decimals without trailing zeros. */
    get formattedValue() {
        return formatFloat(this.props.record.data[this.props.name], {
            trailingZeros: false,
        });
    }

    /**
     * @returns {number} value clamped to [0, 100] for the conic-gradient —
     *     an unset value (`false`) or an out-of-range one would otherwise
     *     produce an invalid `background` declaration (no pie at all).
     */
    get pieValue() {
        return clamp(this.props.record.data[this.props.name] || 0, 0, 100);
    }
}

export const percentPieField = {
    component: PercentPieField,
    displayName: _t("PercentPie"),
    supportedTypes: ["float", "integer"],
    additionalClasses: ["o_field_percent_pie"],
    extractProps: ({ string }) => ({ string }),
};

registerField("percentpie", percentPieField);
