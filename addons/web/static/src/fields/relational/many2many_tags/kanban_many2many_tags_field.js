// @ts-check
/** @odoo-module native */

import { registerField } from "@web/fields/_registry";

import { Many2ManyTagsField, many2ManyTagsField } from "./many2many_tags_field.js";
export class KanbanMany2ManyTagsField extends Many2ManyTagsField {
    static template = "web.KanbanMany2ManyTagsField";

    /** @returns {Array<Object>} */
    get tags() {
        return super.tags.reduce((kanbanTags, tag) => {
            if (tag.colorIndex !== 0) {
                kanbanTags.push(tag);
            }
            return kanbanTags;
        }, []);
    }
}

const kanbanMany2ManyTagsField = {
    ...many2ManyTagsField,
    component: KanbanMany2ManyTagsField,
};

registerField({ name: "many2many_tags", view: "kanban" }, kanbanMany2ManyTagsField);
