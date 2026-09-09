/** @odoo-module native */
import { registry } from "@web/core/registry";

import { kanbanView } from "@web/views/kanban";
import { AccountReturnKanbanRenderer } from "./account_return_kanban_renderer.js";

export const accountReturnKanbanView = {
    ...kanbanView,
    Renderer: AccountReturnKanbanRenderer,
};

registry.category("views").add("account_return_kanban", accountReturnKanbanView);
