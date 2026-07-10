// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/badge/badge_field - Read-only badge pill for Selection and Many2one columns */

import { Component } from "@odoo/owl";
import { getFieldCodec } from "@web/core/field_codec";
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class BadgeField extends Component {
    static template = "web.BadgeField";
    static props = {
        ...standardFieldProps,
        decorations: { type: Object, optional: true },
        colorField: { type: String, optional: true },
    };
    static defaultProps = {
        decorations: {},
    };

    /** @returns {string} Field value formatted for display (respects selection labels). */
    get formattedValue() {
        const { type, selection } = this.props.record.fields[this.props.name];
        return getFieldCodec(type).format(this.props.record.data[this.props.name], {
            selection,
        });
    }

    /** @returns {string} Bootstrap badge CSS class based on color field or decoration rules. */
    get badgeClass() {
        // Only emit a color class for a real integer color index. A null/false
        // color field otherwise produced the junk class `o_badge_color_false`
        // AND skipped the decoration/default fallback below. Mirrors the
        // Number.isInteger guard in list_badge_selection_field.
        if (
            this.props.colorField &&
            Number.isInteger(this.props.record.data[this.props.colorField])
        ) {
            return `o_badge_color_${this.props.record.data[this.props.colorField]}`;
        }
        const evalContext = this.props.record.evalContextWithVirtualIds;
        for (const decorationName of Object.keys(this.props.decorations)) {
            if (
                evaluateBooleanExpr(this.props.decorations[decorationName], evalContext)
            ) {
                // fallback case for text-bg-muted
                if (decorationName === "muted") {
                    return "text-bg-300";
                }
                return `text-bg-${decorationName}`;
            }
        }
        return "text-bg-300";
    }
}

export const badgeField = {
    component: BadgeField,
    displayName: _t("Badge"),
    supportedTypes: ["selection", "many2one", "char"],
    supportedOptions: [
        {
            label: _t("Color field"),
            name: "color_field",
            type: "field",
            availableTypes: ["integer"],
            help: _t("Set an integer field to use colors with the badge."),
        },
    ],
    extractProps: ({ decorations, options }) => ({
        decorations,
        colorField: options.color_field,
    }),
};

registerField("badge", badgeField);
