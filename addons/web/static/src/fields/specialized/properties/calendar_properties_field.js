// @ts-check
/** @odoo-module native */

import { registerField } from "@web/fields/_registry";

import { PropertiesField, propertiesField } from "./properties_field.js";
export class CalendarPropertiesField extends PropertiesField {
    static template = "web.CalendarPropertiesField";
    /** @returns {Promise<false>} */
    async checkDefinitionWriteAccess() {
        return false;
    }
}

const calendarPropertiesField = {
    ...propertiesField,
    component: CalendarPropertiesField,
};

registerField({ name: "properties", view: "calendar" }, calendarPropertiesField);
