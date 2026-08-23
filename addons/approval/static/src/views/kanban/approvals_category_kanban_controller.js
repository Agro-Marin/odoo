/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";

import { KanbanController } from "@web/views/kanban";

export class ApprovalCategoryKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.action = useService("action");
    }

    openNewApprovalRequest() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "approval.request",
            views: [[false, "form"]],
            target: "current",
        });
    }
}
