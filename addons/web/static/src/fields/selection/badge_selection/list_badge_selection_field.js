// @ts-check
/** @odoo-module native */

import { badgeColorClass } from "@web/core/badge/badge_colors";
import { _t } from "@web/core/translation";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { registerField } from "@web/fields/_registry";
import { colorFieldOption } from "@web/fields/field_options";

import { BadgeSelectionField, badgeSelectionField } from "./badge_selection_field.js";

export class ListBadgeSelectionField extends BadgeSelectionField {
    static template = "web.ListBadgeSelectionField";
    static props = {
        ...BadgeSelectionField.props,
        colorField: { type: String, optional: true },
    };
    /**
     * @param {[string, string] | false} option
     * @returns {string | object}
     */
    getBadgeClassNames(option = false) {
        if (this.props.readonly) {
            const colorClass = badgeColorClass(
                this.props.record,
                this.props.colorField,
            );
            if (colorClass) {
                return colorClass;
            }
            return mergeClasses({ "btn btn-secondary": this.value });
        }
        return mergeClasses({
            "active o_badge_border": this.value === option[0],
            "btn-sm": this.props.size === "sm",
            "btn-lg": this.props.size === "lg",
        });
    }
}

const listBadgeSelectionField = {
    ...badgeSelectionField,
    component: ListBadgeSelectionField,
    supportedOptions: [
        ...badgeSelectionField.supportedOptions,
        colorFieldOption(_t("Set an integer field to use colors with the badge.")),
    ],
    fieldDependencies: ({ /** @type {any} */ options }) =>
        options.color_field
            ? [{ name: options.color_field, optional: true, readonly: true }]
            : [],
    extractProps: (/** @type {any} */ fieldInfo, /** @type {any} */ dynamicInfo) => ({
        ...badgeSelectionField.extractProps(fieldInfo, dynamicInfo),
        colorField: fieldInfo.options.color_field,
    }),
};

registerField({ name: "selection_badge", view: "list" }, listBadgeSelectionField);
