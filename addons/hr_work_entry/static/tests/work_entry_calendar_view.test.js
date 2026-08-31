import { luxon } from "@web/core/l10n/luxon";
import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { animationFrame, mockDate } from "@odoo/hoot-mock";
import {
    findComponent,
    makeMockServer,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { defineHrWorkEntryModels } from "@hr_work_entry/../tests/hr_work_entry_test_helpers";
import { WorkEntryCalendarController } from "@hr_work_entry/views/work_entry_calendar/work_entry_calendar_controller";
import { WorkEntryCalendarMultiSelectionButtons } from "@hr_work_entry/views/work_entry_calendar/work_entry_multi_selection_buttons";
const { DateTime } = luxon;

describe.current.tags("desktop");
defineHrWorkEntryModels();

beforeEach(() => {
    mockDate("2025-01-01 12:00:00", +0);
});

function getCalendarController(view) {
    return findComponent(view, (c) => c instanceof WorkEntryCalendarController);
}

test("Test work entry calendar without work entry type", async () => {
    const { env } = await makeMockServer();
    env["hr.work.entry"].create([
        {
            name: "Test Work Entry 0",
            employee_id: 100,
            work_entry_type_id: false,
            date: "2025-01-01",
            duration: 120,
        },
    ]);
    const calendar = await mountView({
        type: "calendar",
        resModel: "hr.work.entry",
    });
    expect(".o_calendar_renderer").toBeDisplayed({
        message:
            "Calendar view should be displayed even with work entries with false work entry type",
    });
    const controller = getCalendarController(calendar);
    const data = {
        name: "Test New Work Entry",
        employee_id: 100,
        work_entry_type_id: false,
    };
    await controller.model.multiCreateRecords(
        {
            record: {
                getChanges: () => data,
            },
        },
        [DateTime.fromISO("2025-01-02")],
    );
    await animationFrame();
    expect(".fc-event").toHaveCount(2, {
        message: "2 work entries should be displayed in the calendar view",
    });
});

test("should use default_employee_id from context in work entry", async () => {
    const defaultEmployeeId = 100;
    const view = await mountView({
        type: "calendar",
        resModel: "hr.work.entry",
        context: { default_employee_id: defaultEmployeeId },
    });

    const controller = findComponent(
        view,
        (component) => component instanceof WorkEntryCalendarMultiSelectionButtons,
    );
    const workEntryTypeId = 1;
    const values = controller.makeValues(workEntryTypeId);

    expect(values).toEqual({
        employee_id: defaultEmployeeId,
        duration: -1,
        work_entry_type_id: workEntryTypeId,
    });
});

test("the Reset buttons are hidden for a user who cannot regenerate", async () => {
    onRpc("has_group", () => false);
    await mountView({
        type: "calendar",
        resModel: "hr.work.entry",
        context: { default_employee_id: 100 },
    });
    await animationFrame();
    expect("button:contains(Reset)").toHaveCount(0, {
        message:
            "Regenerating work entries needs hr.group_hr_manager: the wizard's ACL " +
            "is manager-only and hr.version.contract_date_start is manager-gated, so " +
            "offering the button to an HR officer only produces an AccessError.",
    });
});

test("the Reset button is shown to a work entry manager", async () => {
    onRpc("has_group", () => true);
    await mountView({
        type: "calendar",
        resModel: "hr.work.entry",
        context: { default_employee_id: 100 },
    });
    await animationFrame();
    expect("button:contains(Reset)").toHaveCount(1, {
        message: "A manager must still get the regenerate action.",
    });
});
