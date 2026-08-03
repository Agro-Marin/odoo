/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban";

import { MailActivityMyKanbanController } from "./mail_activity_my_kanban_controller.js";

export const mailActivityMyKanbanView = {
    ...kanbanView,
    Controller: MailActivityMyKanbanController,
};

registry.category("views").add("mail_activity_my_kanban", mailActivityMyKanbanView);
