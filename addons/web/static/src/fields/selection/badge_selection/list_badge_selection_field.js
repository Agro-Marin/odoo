// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/badge_selection/list_badge_selection_field */

import { badgeColorClass } from "@web/core/badge/badge_colors";
import { _t } from "@web/core/translation";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { registerField } from "@web/fields/_registry";

import { BadgeSelectionField, badgeSelectionField } from "./badge_selection_field.js";

export class ListBadgeSelectionField extends BadgeSelectionField {
    static template = "web.ListBadgeSelectionField";
    static props = {
        ...BadgeSelectionField.props,
        colorField: { type: String, optional: true },
    };
    /**
     * @param {[string, string] | false} option
     * @returns {string}
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

export const listBadgeSelectionField = {
    ...badgeSelectionField,
    component: ListBadgeSelectionField,
    supportedOptions: [
        ...badgeSelectionField.supportedOptions,
        {
            label: _t("Color field"),
            name: "color_field",
            type: "field",
            availableTypes: ["integer"],
            help: _t("Set an integer field to use colors with the badge."),
        },
    ],
    // `badgeColorClass` reads the colour out of `record.data`, so a view that
    // names the option but not the field fell back to the plain badge and the
    // option silently did nothing.
    fieldDependencies: ({ options }) =>
        options.color_field
            ? [{ name: options.color_field, optional: true, readonly: true }]
            : [],
    extractProps: (/** @type {any} */ fieldInfo, /** @type {any} */ dynamicInfo) => ({
        ...badgeSelectionField.extractProps(fieldInfo, dynamicInfo),
        colorField: fieldInfo.options.color_field,
    }),
};

registerField({ name: "selection_badge", view: "list" }, listBadgeSelectionField);
