import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    mockService,
    mountView,
    onRpc,
    toggleKanbanColumnActions,
} from "@web/../tests/web_test_helpers";

import { defineProjectModels } from "./project_models.js";

defineProjectModels();
describe.current.tags("desktop");

const taskKanbanParams = {
    resModel: "project.task",
    type: "kanban",
    arch: `
        <kanban js_class="project_task_kanban">
            <field name="step_id"/>
            <templates>
                <t t-name="card">
                    <field name="name"/>
                </t>
            </templates>
        </kanban>
    `,
    groupBy: ["step_id"],
};

const taskListParams = {
    resModel: "project.task",
    type: "list",
    arch: `
        <list js_class="project_task_list" expand="1">
            <field name="name"/>
        </list>
    `,
    groupBy: ["step_id"],
};

function mockWizardAction() {
    const captured = {};
    mockService("action", {
        doAction(action, options) {
            captured.action = action;
            captured.options = options;
            expect.step("doAction");
        },
    });
    return captured;
}

test("task kanban: deleting a step column routes through the unlink wizard", async () => {
    onRpc("has_group", ({ args }) => args[1] === "project.group_project_manager");
    onRpc("unlink_wizard", ({ model, args }) => {
        expect(model).toBe("project.workflow.step");
        expect(args).toEqual([[1]]);
        expect.step("unlink_wizard");
        return { type: "ir.actions.act_window", target: "new" };
    });
    onRpc("unlink", () => expect.step("unlink"));
    onRpc("web_read_group", () => expect.step("web_read_group"));
    const captured = mockWizardAction();

    await mountView(taskKanbanParams);
    expect.verifySteps(["web_read_group"]);

    const clickColumnAction = await toggleKanbanColumnActions(0);
    await clickColumnAction("Delete");
    // The wizard IS the confirmation: no generic "delete this column?" dialog,
    // and no raw unlink.
    expect(".modal").toHaveCount(0);
    expect.verifySteps(["unlink_wizard", "doAction"]);

    // Dismissing the wizard (Escape / Discard) closes with no payload: nothing
    // must happen, in particular no crash and no reload.
    captured.options.onClose(undefined);
    await animationFrame();
    expect.verifySteps([]);

    // Confirming the wizard reloads the view.
    captured.options.onClose({ success: true });
    await animationFrame();
    expect.verifySteps(["web_read_group"]);
});

test("task kanban: non-managers can neither edit nor delete step columns", async () => {
    onRpc("has_group", ({ args }) => args[1] === "project.group_project_user");
    await mountView(taskKanbanParams);
    await toggleKanbanColumnActions(0);
    await animationFrame();
    expect(".o_group_edit").toHaveCount(0);
    expect(".o_group_delete").toHaveCount(0);
});

test("task kanban: managers can edit and delete step columns", async () => {
    onRpc("has_group", ({ args }) => args[1] === "project.group_project_manager");
    await mountView(taskKanbanParams);
    await toggleKanbanColumnActions(0);
    await animationFrame();
    expect(".o_group_edit").toHaveCount(1);
    expect(".o_group_delete").toHaveCount(1);
});

test("task kanban: non-stage columns keep the generic confirm + raw unlink", async () => {
    onRpc("has_group", ({ args }) => args[1] === "project.group_project_manager");
    onRpc("unlink_wizard", () => expect.step("unlink_wizard"));
    onRpc("unlink", ({ model }) => {
        expect.step(`unlink ${model}`);
        return true;
    });

    await mountView({ ...taskKanbanParams, groupBy: ["milestone_id"] });
    // Column 1 is "Milestone 1" (column 0 is the falsy "None" group, which
    // renders no config menu).
    const clickColumnAction = await toggleKanbanColumnActions(1);
    await clickColumnAction("Delete");
    await animationFrame();
    expect(".modal").toHaveCount(1);
    await contains(".modal .btn-primary").click();
    expect.verifySteps(["unlink project.milestone"]);
});

test("task grouped list: step column delete routes through the unlink wizard", async () => {
    onRpc("has_group", ({ args }) => args[1] === "project.group_project_manager");
    onRpc("unlink_wizard", ({ model, args }) => {
        expect(model).toBe("project.workflow.step");
        expect(args).toEqual([[1]]);
        expect.step("unlink_wizard");
        return { type: "ir.actions.act_window", target: "new" };
    });
    onRpc("unlink", () => expect.step("unlink"));
    mockWizardAction();

    await mountView(taskListParams);
    await contains(".o_group_header .o_group_config .dropdown-toggle", {
        visible: false,
    }).click();
    await contains(".o-dropdown--group-config-menu .o_group_delete").click();
    expect(".modal").toHaveCount(0);
    expect.verifySteps(["unlink_wizard", "doAction"]);
});

test("task grouped list: non-managers can neither edit nor delete step columns", async () => {
    onRpc("has_group", ({ args }) => args[1] === "project.group_project_user");
    await mountView(taskListParams);
    await contains(".o_group_header .o_group_config .dropdown-toggle", {
        visible: false,
    }).click();
    await animationFrame();
    expect(".o_group_edit").toHaveCount(0);
    expect(".o_group_delete").toHaveCount(0);
});

test("project grouped list: phase column delete routes through the phase unlink wizard", async () => {
    onRpc("has_group", ({ args }) => args[1] === "project.group_project_manager");
    onRpc("unlink_wizard", ({ model, args }) => {
        expect(model).toBe("project.phase");
        expect(args).toEqual([[1]]);
        expect.step("unlink_wizard");
        return { type: "ir.actions.act_window", target: "new" };
    });
    onRpc("unlink", () => expect.step("unlink"));
    mockWizardAction();

    await mountView({
        resModel: "project.project",
        type: "list",
        arch: `
            <list js_class="project_project_list" expand="1">
                <field name="name"/>
            </list>
        `,
        groupBy: ["phase_id"],
    });
    await contains(".o_group_header .o_group_config .dropdown-toggle", {
        visible: false,
    }).click();
    await contains(".o-dropdown--group-config-menu .o_group_delete").click();
    expect(".modal").toHaveCount(0);
    expect.verifySteps(["unlink_wizard", "doAction"]);
});
