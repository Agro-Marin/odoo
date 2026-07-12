// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/badge_selection/badge_selection_field - Clickable badge group field for Selection and Many2one columns */

import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
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
            validate: (s) => ["sm", "md", "lg"].includes(s),
        },
    };
    static defaultProps = {
        size: "md",
    };

    get options() {
        switch (this.type) {
            case "many2one":
                return this.specialData.data;
            case "selection":
                return this.props.record.fields[this.props.name].selection;
            default:
                return [];
        }
    }

    /**
     * Keyboard activation for the badge "radios" (they are spans, not native
     * buttons, so Enter/Space must be wired manually).
     *
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
                if (value === false) {
                    this.props.record.update({ [this.props.name]: false });
                } else {
                    const option = this.options.find((option) => option[0] === value);
                    this.props.record.update({
                        [this.props.name]: {
                            id: option[0],
                            display_name: option[1],
                        },
                    });
                }
                break;
            case "selection":
                if (value === this.value) {
                    // Deselect-on-reclick must respect BOTH model-level required
                    // and the arch/dynamic `required="..."` modifier — otherwise
                    // clicking the active badge clears a field the view marks
                    // required, surfacing the violation late.
                    const { required } = this.props.record.fields[this.props.name];
                    if (!required && !this.props.required) {
                        this.props.record.update({ [this.props.name]: false });
                    }
                } else {
                    this.props.record.update({ [this.props.name]: value });
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
            label: "Size",
            name: "size",
            type: "selection",
            choices: [
                { label: "Small", value: "sm" },
                { label: "Medium", value: "md" },
                { label: "Large", value: "lg" },
            ],
            default: "md",
        },
    ],
    isEmpty: isFalseEmpty,
    extractProps: (fieldInfo, dynamicInfo) => ({
        domain: dynamicInfo.domain,
        context: dynamicInfo.context,
        required: dynamicInfo.required,
        size: fieldInfo.options.size,
    }),
};

registerField("selection_badge", badgeSelectionField);
