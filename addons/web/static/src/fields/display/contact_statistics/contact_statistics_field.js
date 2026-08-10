// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/contact_statistics/contact_statistics_field */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ContactStatisticsField extends Component {
    static template = "web.ContactStatisticsField";
    static props = {
        ...standardFieldProps,
    };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    /** @returns {Array<Object>} */
    get list() {
        return this.field.value || [];
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const contactStatisticsField = {
    component: ContactStatisticsField,
    displayName: _t("Contact Statistics"),
    supportedTypes: ["json"],
};

registerField("contact_statistics", contactStatisticsField);
