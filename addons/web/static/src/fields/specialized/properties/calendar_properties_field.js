// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/calendar_properties_field - Calendar-view read-only variant of the properties field */

import { registerField } from "@web/fields/_registry";

import { PropertiesField, propertiesField } from "./properties_field.js";
export class CalendarPropertiesField extends PropertiesField {
    static template = "web.CalendarPropertiesField";
    /** @returns {Promise<false>} Always denies definition write access in calendar view */
    async checkDefinitionWriteAccess() {
        return false;
    }
}

export const calendarPropertiesField = {
    ...propertiesField,
    component: CalendarPropertiesField,
};

registerField({ name: "properties", view: "calendar" }, calendarPropertiesField);
