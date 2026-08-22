/** @odoo-module native */
import { registerField } from "@web/fields/_registry";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
    KanbanMany2ManyTagsField,
} from "@web/fields/relational/many2many_tags";

export class DocumentsKanbanMany2ManyTagsField extends Many2ManyTagsField {
    static template = KanbanMany2ManyTagsField.template;
}

export const documentsKanbanMany2ManyTagsField = {
    ...many2ManyTagsField,
    component: DocumentsKanbanMany2ManyTagsField,
};

registerField({ name: "documents_many2many_tags" }, documentsKanbanMany2ManyTagsField);
