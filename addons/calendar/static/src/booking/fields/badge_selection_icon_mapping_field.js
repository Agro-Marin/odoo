/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import {
    BadgeSelectionField,
    badgeSelectionField,
} from "@web/fields/selection/badge_selection/badge_selection_field";

export class BadgeSelectionIconMappingField extends BadgeSelectionField {
    static template = "calendar.booking.BadgeSelectionIconMappingField";
    static props = {
        ...BadgeSelectionField.props,
        iconMapping: { type: Object, optional: true },
        allowedValues: { type: Array, optional: true },
    };

    get options() {
        return super.options.filter(
            ([value]) =>
                !this.props.allowedValues || this.props.allowedValues.includes(value),
        );
    }

    getIconMapping(selectionValue) {
        return this.props.iconMapping?.[selectionValue] || "fa-solid fa-check";
    }
}

export const badgeSelectionIconMappingField = {
    ...badgeSelectionField,
    component: BadgeSelectionIconMappingField,
    displayName: _t("Badges with Icon for Selection Field"),
    supportedTypes: ["selection"],
    extractProps({ options }) {
        return {
            ...badgeSelectionField.extractProps(...arguments),
            iconMapping: options.icon_mapping,
            allowedValues: options.allowed_values,
        };
    },
};

registry
    .category("fields")
    .add("selection_badge_icon_mapping", badgeSelectionIconMappingField);
