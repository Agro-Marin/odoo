import { models } from "@web/../tests/web_test_helpers";

export class ApprovalApprover extends models.ServerModel {
    _name = "approval.approver";

    action_approve() {
        return undefined;
    }

    action_refuse() {
        const [approver] = this;
        return {
            name: "Refuse Request",
            type: "ir.actions.act_window",
            res_model: "approval.decision.wizard",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_approver_id: approver?.id,
                default_decision_type: "refuse",
            },
        };
    }
}
