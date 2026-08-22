// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ContactStatisticsField extends FieldComponent {
    static template = "web.ContactStatisticsField";
    static props = {
        ...standardFieldProps,
    };

    /** @returns {Array<Object>} */
    get list() {
        return this.field.value || [];
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const contactStatisticsField = {
    component: ContactStatisticsField,
    displayName: _t("Contact Statistics"),
    supportedTypes: ["json"],
};

registerField("contact_statistics", contactStatisticsField);
