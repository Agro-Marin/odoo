/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban";

import { AccountReturnBaseKanbanRenderer } from "./account_return_base_kanban_renderer.js";

export const accountReturnAuditKanbanView = {
    ...kanbanView,
    Renderer: AccountReturnBaseKanbanRenderer,
};

registry
    .category("views")
    .add("account_return_audit_kanban", accountReturnAuditKanbanView);
