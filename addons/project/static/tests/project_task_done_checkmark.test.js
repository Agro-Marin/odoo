import { describe, expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountView, onRpc } from "@web/../tests/web_test_helpers";

import { defineProjectModels, ProjectTask } from "./project_models.js";

defineProjectModels();
describe.current.tags("desktop");

test("task_done_checkmark toggles the value and saves", async () => {
    ProjectTask._records = [{ id: 1, name: "Task", is_closed: false }];
    onRpc("web_save", ({ args }) => expect.step(`save:${args[1].is_closed}`));
    await mountView({
        resModel: "project.task",
        type: "kanban",
        arch: `
            <kanban>
                <templates>
                    <t t-name="card">
                        <field name="is_closed" widget="task_done_checkmark"/>
                    </t>
                </templates>
            </kanban>
        `,
    });
    expect("button.o_todo_done_button").toHaveCount(1);
    expect("button.o_todo_done_button").not.toHaveClass("done_button_enabled");
    expect("button.o_todo_done_button").toHaveAttribute("aria-pressed", "false");

    await click("button.o_todo_done_button");
    await animationFrame();
    expect.verifySteps(["save:true"]);
    expect("button.o_todo_done_button").toHaveClass("done_button_enabled");
    expect("button.o_todo_done_button").toHaveAttribute("aria-pressed", "true");
});

test("task_done_checkmark is disabled when readonly", async () => {
    ProjectTask._records = [{ id: 1, name: "Task", is_closed: false }];
    await mountView({
        resModel: "project.task",
        type: "kanban",
        arch: `
            <kanban>
                <templates>
                    <t t-name="card">
                        <field name="is_closed" widget="task_done_checkmark" readonly="1"/>
                    </t>
                </templates>
            </kanban>
        `,
    });
    expect("button.o_todo_done_button").toHaveAttribute("disabled");
});
