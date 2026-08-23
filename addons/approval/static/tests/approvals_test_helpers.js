import { defineModels } from "@web/../tests/web_test_helpers";
import { mailModels } from "@mail/../tests/mail_test_helpers";
import { ApprovalRequest } from "@approval/../tests/mock_server/mock_models/approval_request";
import { ApprovalApprover } from "@approval/../tests/mock_server/mock_models/approval_approver";
import { ApprovalCategory } from "@approval/../tests/mock_server/mock_models/approval_category";
import { ApprovalDecisionWizard } from "@approval/../tests/mock_server/mock_models/approval_decision_wizard";
import { MailActivity } from "@approval/../tests/mock_server/mock_models/mail_activity";

export function defineApprovalsModels() {
    return defineModels(approvalsModels);
}

export const approvalsModels = {
    ...mailModels,
    ApprovalRequest,
    ApprovalApprover,
    ApprovalCategory,
    ApprovalDecisionWizard,
    MailActivity,
};
