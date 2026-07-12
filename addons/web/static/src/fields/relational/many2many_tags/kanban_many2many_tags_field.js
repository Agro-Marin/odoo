// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/many2many_tags/kanban_many2many_tags_field - Kanban-view variant of Many2many tags showing only colored tags */

import { registerField } from "@web/fields/_registry";

import { Many2ManyTagsField, many2ManyTagsField } from "./many2many_tags_field.js";
export class KanbanMany2ManyTagsField extends Many2ManyTagsField {
    static template = "web.KanbanMany2ManyTagsField";

    /** @returns {Array<Object>} Only tags with a non-zero color index */
    get tags() {
        return super.tags.reduce((kanbanTags, tag) => {
            if (tag.colorIndex !== 0) {
                kanbanTags.push(tag);
            }
            return kanbanTags;
        }, []);
    }
}

export const kanbanMany2ManyTagsField = {
    ...many2ManyTagsField,
    component: KanbanMany2ManyTagsField,
};

registerField({ name: "many2many_tags", view: "kanban" }, kanbanMany2ManyTagsField);
