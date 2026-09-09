// @ts-check
/** @odoo-module native */

import { registerField } from "@web/fields/_registry";

import { Many2ManyTagsField, many2ManyTagsField } from "./many2many_tags_field.js";
export class KanbanMany2ManyTagsField extends Many2ManyTagsField {
    static template = "web.KanbanMany2ManyTagsField";

    /** @type {{ source: Object[], tags: Object[] } | null} */
    _visibleTagsMemo = null;

    /** @returns {Array<Object>} */
    get tags() {
        const tags = super.tags;
        if (this._visibleTagsMemo?.source === tags) {
            return this._visibleTagsMemo.tags;
        }
        const visible = tags.filter((tag) => tag.colorIndex !== 0);
        this._visibleTagsMemo = { source: tags, tags: visible };
        return visible;
    }
}

const kanbanMany2ManyTagsField = {
    ...many2ManyTagsField,
    component: KanbanMany2ManyTagsField,
};

registerField({ name: "many2many_tags", view: "kanban" }, kanbanMany2ManyTagsField);
