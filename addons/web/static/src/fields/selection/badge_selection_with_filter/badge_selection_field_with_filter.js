// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import {
    BadgeSelectionField,
    badgeSelectionField,
} from "@web/fields/selection/badge_selection/badge_selection_field";

export class BadgeSelectionWithFilterField extends BadgeSelectionField {
    static props = {
        ...BadgeSelectionField.props,
        allowedSelectionField: { type: String, optional: true },
    };

    /**
     * @returns {Array<[string, string]>}
     */
    get options() {
        if (!this.props.allowedSelectionField) {
            return super.options;
        }
        const allowedSelection =
            this.props.record.data[this.props.allowedSelectionField] || [];
        return super.options.filter(
            (/** @type {[any, any]} */ [value, _]) =>
                value === this.value || allowedSelection.includes(value),
        );
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const badgeSelectionFieldWithFilter = {
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
