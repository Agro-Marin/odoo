// @ts-check
/** @odoo-module native */

/**
 * @module @web/fields/selection/badge_selection_with_filter/badge_selection_field_with_filter
 */

import { _t } from "@web/core/l10n/translation";
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

    /** @returns {Array<[string, string]>} */
    get options() {
        const allowedSelection =
            this.props.record.data[this.props.allowedSelectionField] || [];
        return super.options.filter((/** @type {[any, any]} */ [value, _]) =>
            allowedSelection.includes(value),
        );
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const badgeSelectionFieldWithFilter = {
    ...badgeSelectionField,
    component: BadgeSelectionWithFilterField,
    displayName: _t("Badges for Selection With Filter"),
    supportedTypes: ["selection"],
    extractProps: (fieldInfo, dynamicInfo) => ({
        ...badgeSelectionField.extractProps(fieldInfo, dynamicInfo),
        allowedSelectionField: fieldInfo.options.allowed_selection_field,
    }),
};

registerField("selection_badge_with_filter", badgeSelectionFieldWithFilter);
