// @ts-check
/** @odoo-module native */

import { badgeColorClass } from "@web/core/badge/badge_colors";
import { getFieldCodec } from "@web/core/field_codec";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { colorFieldOption } from "@web/fields/field_options";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class BadgeField extends FieldComponent {
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
        const { type, selection } = this.field.definition;
        return getFieldCodec(type).format(this.field.value, {
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
        colorFieldOption(_t("Set an integer field to use colors with the badge.")),
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
