// @ts-check
/** @odoo-module native */

/**
 * @module @web/fields/selection/badge_selection_with_filter/badge_selection_field_with_filter
 */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import {
    BadgeSelectionField,
    badgeSelectionField,
} from "@web/fields/selection/badge_selection/badge_selection_field";

export class BadgeSelectionWithFilterField extends BadgeSelectionField {
    static props = {
        ...BadgeSelectionField.props,
        allowedSelectionField: { type: String },
    };

    /**
     * The value the record actually holds always stays offered, even once it
     * drops out of the allowed list -- otherwise the widget renders with no
     * badge selected at all while the record holds one, so the user can neither
     * read the current value nor tell the field apart from an empty one. The
     * sibling `filterable_selection` has always kept it for the same reason.
     *
     * @returns {Array<[string, string]>}
     */
    get options() {
        const allowedSelection =
            this.props.record.data[this.props.allowedSelectionField] || [];
        return super.options.filter(
            (/** @type {[any, any]} */ [value, _]) =>
                value === this.value || allowedSelection.includes(value),
        );
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const badgeSelectionFieldWithFilter = {
    ...badgeSelectionField,
    component: BadgeSelectionWithFilterField,
    displayName: _t("Badges for Selection With Filter"),
    supportedTypes: ["selection"],
    supportedOptions: [
        ...(badgeSelectionField.supportedOptions || []),
        {
            label: _t("Allowed values field"),
            name: "allowed_selection_field",
            type: "field",
            help: _t(
                "Field holding the list of selection values that stay selectable.",
            ),
        },
    ],
    // Read to decide which values stay selectable, so it has to be loaded even
    // when the view does not render it. Without this every consumer had to
    // remember an `<field name="..." invisible="1"/>` of its own, and forgetting
    // it filtered every option away rather than failing.
    fieldDependencies: ({ options }) =>
        options.allowed_selection_field
            ? [
                  {
                      name: options.allowed_selection_field,
                      optional: true,
                      readonly: true,
                  },
              ]
            : [],
    extractProps: (fieldInfo, dynamicInfo) => ({
        ...badgeSelectionField.extractProps(fieldInfo, dynamicInfo),
        allowedSelectionField: fieldInfo.options.allowed_selection_field,
    }),
};

registerField("selection_badge_with_filter", badgeSelectionFieldWithFilter);
