/** @odoo-module native */
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban";

import { ApprovalCategoryKanbanController } from "./approvals_category_kanban_controller.js";

export const approvalsCategoryKanbanView = {
    ...kanbanView,
    Controller: ApprovalCategoryKanbanController,
    buttonTemplate: "approval.ApprovalsCategoryKanbanView.Buttons",
};

registry
    .category("views")
    .add("approvals_category_kanban", approvalsCategoryKanbanView);
