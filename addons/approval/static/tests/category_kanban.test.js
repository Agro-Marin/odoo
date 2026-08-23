import { describe, expect, test } from "@odoo/hoot";

import { defineApprovalsModels } from "@approval/../tests/approvals_test_helpers";
import { click, contains, start, startServer } from "@mail/../tests/mail_test_helpers";
import { getService, mockService } from "@web/../tests/web_test_helpers";
import { kanbanView } from "@web/views/kanban";

import { approvalsCategoryKanbanView } from "@approval/views/kanban/approvals_category_kanban_view";
import { ApprovalCategoryKanbanController } from "@approval/views/kanban/approvals_category_kanban_controller";

describe.current.tags("desktop");
defineApprovalsModels();

async function openCategoryKanban() {
    await start();
    await getService("action").doAction({
        type: "ir.actions.act_window",
        res_model: "approval.category",
        views: [[false, "kanban"]],
    });
}

test("the category kanban shows the custom New Request button", async () => {
    const pyEnv = await startServer();
    pyEnv["approval.category"].create({ name: "Business Trip" });
    await openCategoryKanban();
    await contains(".o_kanban_view");
    await contains("button", { text: "New Request" });
});

test("New Request opens an approval.request form", async () => {
    const pyEnv = await startServer();
    pyEnv["approval.category"].create({ name: "Business Trip" });
    const actions = [];
    await openCategoryKanban();
    mockService("action", {
        doAction(action) {
            actions.push(action);
        },
    });
    await click("button", { text: "New Request" });
    expect(actions.length).toBe(1);
    expect(actions[0].res_model).toBe("approval.request");
    expect(actions[0].target).toBe("current");
});

test("the category kanban uses the stock renderer", async () => {
    expect(approvalsCategoryKanbanView.Renderer).toBe(kanbanView.Renderer);
    expect(approvalsCategoryKanbanView.Controller).toBe(
        ApprovalCategoryKanbanController,
    );
    expect(approvalsCategoryKanbanView.buttonTemplate).toBe(
        "approval.ApprovalsCategoryKanbanView.Buttons",
    );
});
