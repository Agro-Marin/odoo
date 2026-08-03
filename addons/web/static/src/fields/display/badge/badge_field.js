// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/badge/badge_field */

import { Component } from "@odoo/owl";
import { badgeColorClass } from "@web/core/badge/badge_colors";
import { getFieldCodec } from "@web/core/field_codec";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
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

    /** @returns {string} */
    get formattedValue() {
        const { type, selection } = this.props.record.fields[this.props.name];
        return getFieldCodec(type).format(this.props.record.data[this.props.name], {
            selection,
        });
    }

    /** @returns {string} */
    get badgeClass() {
        const colorClass = badgeColorClass(this.props.record, this.props.colorField);
        if (colorClass) {
            return colorClass;
        }
        const evalContext = this.props.record.evalContextWithVirtualIds;
        for (const decorationName of Object.keys(this.props.decorations)) {
            if (
                evaluateBooleanExpr(this.props.decorations[decorationName], evalContext)
            ) {
                if (decorationName === "muted") {
                    return "text-bg-300";
                }
                return `text-bg-${decorationName}`;
            }
        }
        return "text-bg-300";
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
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
    fieldDependencies: ({ options }) =>
        options.color_field
            ? [{ name: options.color_field, optional: true, readonly: true }]
            : [],
    extractProps: ({ decorations, options }) => ({
        decorations,
        colorField: options.color_field,
    }),
};

registerField("badge", badgeField);
