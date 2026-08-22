// @ts-check
/** @odoo-module native */

import { registerField } from "@web/fields/_registry";

import { PropertiesField, propertiesField } from "./properties_field.js";
export class CardPropertiesField extends PropertiesField {
    static template = "web.CardPropertiesField";

    /** @returns {Promise<false>} */
    async checkDefinitionWriteAccess() {
        return false;
    }
}

const cardPropertiesField = {
    ...propertiesField,
    component: CardPropertiesField,
};

registerField({ name: "properties", view: "kanban" }, cardPropertiesField);
registerField({ name: "properties", view: "hierarchy" }, cardPropertiesField);
