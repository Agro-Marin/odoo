/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";

import { KanbanController } from "@web/views/kanban";

import { trace } from "../../common/approval_trace.js";

export class ApprovalCategoryKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.action = useService("action");
    }

    openNewApprovalRequest() {
        trace.note("button", "new_request_from_kanban", {});
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "approval.request",
            views: [[false, "form"]],
            target: "current",
        });
    }
}
