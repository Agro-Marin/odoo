// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/properties/card_properties_field - Kanban/hierarchy card read-only variant of the properties field */

import { registerField } from "@web/fields/_registry";

import { PropertiesField, propertiesField } from "./properties_field.js";
export class CardPropertiesField extends PropertiesField {
    static template = "web.CardPropertiesField";

    /** @returns {Promise<false>} Always denies definition write access in card views */
    async checkDefinitionWriteAccess() {
        return false;
    }
}

export const cardPropertiesField = {
    ...propertiesField,
    component: CardPropertiesField,
};

registerField({ name: "properties", view: "kanban" }, cardPropertiesField);
registerField({ name: "properties", view: "hierarchy" }, cardPropertiesField);
