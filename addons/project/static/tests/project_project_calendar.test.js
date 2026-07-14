import { expect, test, describe } from "@odoo/hoot";
import { mockDate, runAllTimers } from "@odoo/hoot-mock";
import { click, queryAllTexts } from "@odoo/hoot-dom";

import { mountView, onRpc } from "@web/../tests/web_test_helpers";

import { defineProjectModels } from "./project_models.js";

describe.current.tags("desktop");
defineProjectModels();

test("check 'Edit' and 'View Tasks' buttons are in Project Calendar Popover", async () => {
    mockDate("2024-01-03 12:00:00", 0);
    onRpc(({ method, model }) => {
        if (model === "project.project" && method === "action_view_tasks") {
            expect.step("view tasks");
            return false;
        } else if (method === "has_access") {
            return true;
        }
    });

    await mountView({
        resModel: "project.project",
        type: "calendar",
        arch: `
            <calendar date_start="date_start" mode="week" js_class="project_project_calendar">
                <field name="name"/>
            </calendar>
        `,
    });

    expect(".o_event").toHaveCount(1);
    await click(".o_event");
    await runAllTimers();
    expect(".o_popover").toHaveCount(1);
    expect(".o_popover .card-footer .btn").toHaveCount(3);
    expect(queryAllTexts(".o_popover .card-footer .btn")).toEqual(["Edit", "View Tasks", ""]);
    expect(".o_popover .card-footer .btn.o_cw_popover_delete").toHaveCount(1);

    await click(".o_popover .card-footer a:contains(View Tasks)");
    await click(".o_popover .card-footer a:contains(Edit)");
    expect.verifySteps(["view tasks"]);
});
