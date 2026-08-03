/** @odoo-module native */
import { registerField } from "@web/fields/_registry";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
    KanbanMany2ManyTagsField,
} from "@web/fields/relational/many2many_tags";

/**
 * Tags on a documents kanban card: the kanban look, but every tag.
 *
 * `KanbanMany2ManyTagsField` drops tags whose colour index is 0, which in
 * Documents hides tags the user deliberately left colourless. That exception used
 * to be obtained by patching the shared component's `tags` getter and switching on
 * `record._config.resModel === "documents.document"`, reaching the grandparent
 * implementation through `Object.getOwnPropertyDescriptor(...).get.call(this)` --
 * so every kanban in the database ran a test for a rule belonging to one view,
 * and the patch was marked "todo: replace with cleaner solution in master".
 * Extending the unfiltered field and borrowing the kanban template says the same
 * thing without reaching into anyone else's component.
 */
export class DocumentsKanbanMany2ManyTagsField extends Many2ManyTagsField {
    static template = KanbanMany2ManyTagsField.template;
}

export const documentsKanbanMany2ManyTagsField = {
    ...many2ManyTagsField,
    component: DocumentsKanbanMany2ManyTagsField,
};

registerField({ name: "documents_many2many_tags" }, documentsKanbanMany2ManyTagsField);
