import { describe, expect, test } from "@odoo/hoot";
import {
    animationFrame,
    click,
    queryAllTexts,
    queryFirst,
    waitFor,
} from "@odoo/hoot-dom";
import { mountView, onRpc } from "@web/../tests/web_test_helpers";

import { defineProjectModels, ProjectTask, ProjectTaskType } from "./project_models.js";

defineProjectModels();
describe.current.tags("desktop");

const viewParams = {
    resModel: "project.task",
    type: "kanban",
    arch: `
        <kanban default_group_by="step_id" js_class="project_task_kanban">
            <templates>
                <t t-name="card">
                    <field name="name"/>
                </t>
            </templates>
        </kanban>`,
    context: {
        active_model: "project.project",
        default_project_id: 1,
    },
};

test("stages nocontent helper should be displayed in the project Kanban", async () => {
    ProjectTask._records = [];

    await mountView({
        resModel: "project.task",
        type: "kanban",
        arch: `
            <kanban default_group_by="step_id" js_class="project_task_kanban">
                <templates>
                    <t t-name="card">
                        <field name="name"/>
                    </t>
                </templates>
            </kanban>
        `,
        context: {
            active_model: "project.workflow.step.delete.wizard",
            default_project_id: 1,
        },
    });

    expect(".o_kanban_header").toHaveCount(1);
    expect(".o_kanban_stages_nocontent").toHaveCount(1);
});

test("quick create button is visible when the user has access rights.", async () => {
    onRpc("has_group", () => true);
    await mountView(viewParams);
    await animationFrame();
    expect(".o_column_quick_create").toHaveCount(1);
});

test("quick create button is not visible when the user not have access rights", async () => {
    onRpc("has_group", () => false);
    await mountView(viewParams);
    await animationFrame();
    expect(".o_column_quick_create").toHaveCount(0);
});

test("project.task (kanban): toggle sub-tasks", async () => {
    ProjectTask._records = [
        {
            id: 1,
            project_id: 1,
            name: "Task 1",
            step_id: 1,
            display_in_project: true,
        },
        {
            id: 2,
            project_id: 1,
            name: "Task 2",
            step_id: 1,
            display_in_project: false,
        },
    ];
    await mountView(viewParams);
    expect(".o_kanban_record").toHaveCount(1);
    expect(".o_control_panel_navigation button i.fa-sliders").toHaveCount(1);
    await click(".o_control_panel_navigation button i.fa-sliders");
    await waitFor("span.o-dropdown-item");
    expect("span.o-dropdown-item").toHaveText("Show Sub-Tasks");
    await click("span.o-dropdown-item");
    await animationFrame();
    expect(".o_kanban_record").toHaveCount(2);
});

test("column header shows the step's WIP limit and warns when it is exceeded", async () => {
    // The limit was configurable and documented but read by nothing, so a team
    // could set one and never learn they had passed it.
    ProjectTaskType._records = [
        { id: 1, name: "Todo", wip_limit: 1 },
        { id: 2, name: "In Progress", wip_limit: 5 },
        { id: 3, name: "Done", wip_limit: 0 },
    ];
    ProjectTask._records = [
        { id: 1, name: "Task 1", project_id: 1, step_id: 1 },
        { id: 2, name: "Task 2", project_id: 1, step_id: 1 },
        { id: 3, name: "Task 3", project_id: 1, step_id: 2 },
        { id: 4, name: "Task 4", project_id: 1, step_id: 3 },
    ];

    await mountView(viewParams);
    await animationFrame();

    const counts = queryAllTexts(".o_column_task_count");
    // Over its limit of 1, within its limit of 5, and no limit at all.
    expect(counts).toEqual(["(2 / 1)", "(1 / 5)", "(1)"]);
    expect(".o_column_task_count.text-danger").toHaveCount(1);
    expect(queryFirst(".o_column_task_count.text-danger")).toHaveText("(2 / 1)");
});

test("column header shows a bare count when no step sets a WIP limit", async () => {
    ProjectTask._records = [{ id: 1, name: "Task 1", project_id: 1, step_id: 1 }];

    await mountView(viewParams);
    await animationFrame();

    expect(queryAllTexts(".o_column_task_count")).toEqual(["(1)"]);
    expect(".o_column_task_count.text-danger").toHaveCount(0);
});
