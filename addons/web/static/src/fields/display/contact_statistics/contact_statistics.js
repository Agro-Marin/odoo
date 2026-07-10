// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/contact_statistics/contact_statistics - Read-only list display for contact statistics stored as JSON */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ContactStatisticsField extends Component {
    static template = "web.ContactStatisticsField";
    static props = {
        ...standardFieldProps,
    };

    /** @returns {Array<Object>} Contact statistics entries from the JSON field, or empty array. */
    get list() {
        return this.props.record.data[this.props.name] || [];
    }
}

export const contactStatisticsField = {
    component: ContactStatisticsField,
    displayName: _t("Contact Statistics"),
    supportedTypes: ["json"],
};

registerField("contact_statistics", contactStatisticsField);
