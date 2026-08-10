// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/badge_selection/badge_selection_field */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
import { isFalseEmpty } from "@web/fields/field_utils";
import { SelectionLikeField } from "@web/fields/selection/selection_like_field";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class BadgeSelectionField extends SelectionLikeField {
    static template = "web.BadgeSelectionField";
    static props = {
        ...standardFieldProps,
        domain: { type: [Array, Function], optional: true },
        context: { type: Object, optional: true },
        required: { type: Boolean, optional: true },
        size: {
            type: String,
            optional: true,
            validate: (/** @type {string} */ s) => ["sm", "md", "lg"].includes(s),
        },
    };
    static defaultProps = {
        size: "md",
    };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    get options() {
        switch (this.type) {
            case "many2one":
                return this.specialData.data;
            case "selection":
                return this.field.definition.selection;
            default:
                return [];
        }
    }

    /**
     * @param {KeyboardEvent} ev
     * @param {string | number | false} value
     */
    onKeydown(ev, value) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.onChange(value);
        }
    }

    /**
     * @param {string | number | false} value
     */
    onChange(value) {
        switch (this.type) {
            case "many2one":
                if (value === this.value) {
                    return;
                }
                if (value === false) {
                    this.field.update(false);
                } else {
                    const option = this.options.find(
                        (/** @type {any[]} */ option) => option[0] === value,
                    );
                    if (!option) {
                        // see SelectionField.onChange
                        return;
                    }
                    this.field.update({
                        id: option[0],
                        display_name: option[1],
                    });
                }
                break;
            case "selection":
                if (value === this.value) {
                    const { required } = this.field.definition;
                    if (!required && !this.props.required) {
                        this.field.update(false);
                    }
                } else {
                    this.field.update(value);
                }
                break;
        }
    }
}

export const badgeSelectionField = {
    component: BadgeSelectionField,
    displayName: _t("Badges"),
    supportedTypes: ["many2one", "selection"],
    supportedOptions: [
        {
            label: _t("Size"),
            name: "size",
            type: "selection",
            choices: [
                { label: _t("Small"), value: "sm" },
                { label: _t("Medium"), value: "md" },
                { label: _t("Large"), value: "lg" },
            ],
            default: "md",
        },
    ],
    isEmpty: isFalseEmpty,
    extractProps: (/** @type {any} */ fieldInfo, /** @type {any} */ dynamicInfo) => ({
        domain: dynamicInfo.domain,
        context: dynamicInfo.context,
        required: dynamicInfo.required,
        size: fieldInfo.options.size,
    }),
};

registerField("selection_badge", badgeSelectionField);
