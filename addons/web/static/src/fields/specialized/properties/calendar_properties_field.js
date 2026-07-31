// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/calendar_properties_field */

import { registerField } from "@web/fields/_registry";

import { PropertiesField, propertiesField } from "./properties_field.js";
export class CalendarPropertiesField extends PropertiesField {
    static template = "web.CalendarPropertiesField";
    /** @returns {Promise<false>} */
    async checkDefinitionWriteAccess() {
        return false;
    }
}

export const calendarPropertiesField = {
    ...propertiesField,
    component: CalendarPropertiesField,
};

registerField({ name: "properties", view: "calendar" }, calendarPropertiesField);
