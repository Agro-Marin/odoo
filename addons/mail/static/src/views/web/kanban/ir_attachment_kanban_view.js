/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban";

import { IrAttachmentKanbanController } from "./ir_attachment_kanban_controller.js";

export const irAttachmentKanbanView = {
    ...kanbanView,
    Controller: IrAttachmentKanbanController,
};

registry.category("views").add("ir_attachment_kanban", irAttachmentKanbanView);
