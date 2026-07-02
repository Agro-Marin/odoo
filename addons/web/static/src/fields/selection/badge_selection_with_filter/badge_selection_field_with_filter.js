// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/badge_selection_with_filter/badge_selection_field_with_filter - Badge selection field filtered by an allowed-values field */

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

    /** @returns {Array<[string, string]>} Selection options filtered by the allowed selection field */
    get options() {
        // The allowed-selection field is a fields.Json that reads ``false``
        // when unset (new record / conditional compute), so guard against
        // ``false.includes`` crashing the render. Unlike filterable_selection,
        // this widget deliberately filters strictly by the allowed list — the
        // currently-selected value is hidden too when it is not allowed.
        const allowedSelection =
            this.props.record.data[this.props.allowedSelectionField] || [];
        return super.options.filter(([value, _]) => allowedSelection.includes(value));
    }
}

export const badgeSelectionFieldWithFilter = {
    ...badgeSelectionField,
    component: BadgeSelectionWithFilterField,
    displayName: _t("Badges for Selection With Filter"),
    supportedTypes: ["selection"],
    extractProps({ options }) {
        return {
            ...badgeSelectionField.extractProps(...arguments),
            allowedSelectionField: options.allowed_selection_field,
        };
    },
};

registerField("selection_badge_with_filter", badgeSelectionFieldWithFilter);
