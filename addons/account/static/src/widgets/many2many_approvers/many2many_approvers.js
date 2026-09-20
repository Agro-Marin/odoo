/** @odoo-module native */
import {
    KanbanMany2ManyAvatarUserTagsList,
    KanbanMany2ManyTagsAvatarUserField,
    kanbanMany2ManyTagsAvatarUserField,
} from "@mail/views/web/fields/many2many_avatar_user_field/many2many_avatar_user_field";
import { registry } from "@web/core/registry";

export class Many2ManyAvatarUserApproverTagsList extends KanbanMany2ManyAvatarUserTagsList {
    static template = "account.KanbanMany2ManyAvatarUserTagsList";
}

export class Many2ManyAvatarUserApprover extends KanbanMany2ManyTagsAvatarUserField {
    static components = {
        ...KanbanMany2ManyTagsAvatarUserField.components,
        TagsList: Many2ManyAvatarUserApproverTagsList,
    };
}

export const many2ManyAvatarUserApprover = {
    ...kanbanMany2ManyTagsAvatarUserField,
    component: Many2ManyAvatarUserApprover,
};

registry
    .category("fields")
    .add("kanban.many2many_avatar_user_approver", many2ManyAvatarUserApprover);
