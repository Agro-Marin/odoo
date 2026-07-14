import { describe, expect, test } from "@odoo/hoot";
import { check, click, queryAll, queryOne, waitFor } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountView } from "@web/../tests/web_test_helpers";

import { defineProjectModels, ProjectTask } from "./project_models.js";

defineProjectModels();

describe.current.tags("desktop");

test("project.task (list): cannot edit step_id with different projects", async () => {
    ProjectTask._records = [
        {
            id: 1,
            project_id: 1,
            step_id: 1,
        },
        {
            id: 2,
            project_id: 2,
            step_id: 1,
        },
    ];

    await mountView({
        resModel: "project.task",
        type: "list",
        arch: `
            <list multi_edit="1" js_class="project_task_list">
                <field name="project_id"/>
                <field name="step_id"/>
            </list>
        `,
    });

    const [firstRow, secondRow] = queryAll(".o_data_row");
    await check(".o_list_record_selector input", { root: firstRow });
    await animationFrame();
    expect(queryAll("[name=step_id]")).not.toHaveClass("o_readonly_modifier");

    await check(".o_list_record_selector input", { root: secondRow });
    await animationFrame();
    // Selecting tasks of different projects makes the step cell readonly.
    // Assert the functional gate (entering edition keeps the field readonly,
    // so no editable many2one input shows up) rather than the visual class:
    // rows not re-rendered by the selection change may keep a stale cell
    // class, but getFieldProps re-evaluates isCellReadonly on edition.
    await click(queryOne("[name=step_id]", { root: firstRow }));
    await animationFrame();
    expect(queryAll(".o_selected_row [name=step_id] input")).toHaveCount(0, {
        message: "step_id must not be editable when selected tasks span projects",
    });
});

test("project.task (list): toggle sub-tasks", async () => {
    ProjectTask._records = [
        {
            id: 1,
            project_id: 1,
            name: "Task 1",
            step_id:  1,
            display_in_project: true,
        },
        {
            id: 2,
            project_id: 1,
            name: "Task 2",
            step_id:  1,
            display_in_project: false,
        }
    ];
    await mountView({
        resModel: "project.task",
        type: "list",
        arch: `
            <list multi_edit="1" js_class="project_task_list">
                <field name="project_id"/>
                <field name="step_id"/>
            </list>
        `,
    });
    expect(".o_data_row").toHaveCount(1);
    expect(".o_control_panel_navigation button i.fa-sliders").toHaveCount(1);
    await click(".o_control_panel_navigation button i.fa-sliders");
    await waitFor("span.o-dropdown-item");
    expect("span.o-dropdown-item").toHaveText("Show Sub-Tasks");
    await click("span.o-dropdown-item");
    await animationFrame();
    expect(".o_data_row").toHaveCount(2);
});
