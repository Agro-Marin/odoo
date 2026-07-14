import { luxon } from "@web/core/l10n/luxon";
import { expect, test, beforeEach, describe } from "@odoo/hoot";
import { mockDate, animationFrame, runAllTimers } from "@odoo/hoot-mock";
import { click, queryAllTexts, queryFirst, queryOne, waitFor } from "@odoo/hoot-dom";

import { contains, mountView, onRpc } from "@web/../tests/web_test_helpers";

import { defineProjectModels, ProjectTask } from "./project_models.js";
import { serializeDateTime } from "@web/core/l10n/dates";

describe.current.tags("desktop");
defineProjectModels();

beforeEach(() => {
    mockDate("2024-01-03 12:00:00", +0);

    ProjectTask._views["form"] = `
        <form>
            <field name="id"/>
            <field name="name"/>
            <field name="date_end"/>
            <field name="planned_date_begin"/>
        </form>
    `;

    ProjectTask._records = [
        {
            id: 1,
            name: "Task-1",
            date_end: "2024-01-09 07:00:00",
            create_date: "2024-01-03 12:00:00",
            project_id: 1,
            step_id: 1,
            state: "in_progress",
            user_ids: [],
            display_name: "Task-1",
        },
        {
            id: 10,
            name: "Task-10",
            project_id: 1,
            step_id: 1,
            state: "in_progress",
            user_ids: [],
            display_name: "Task-10",
        },
        {
            id: 11,
            name: "Task-11",
            project_id: 1,
            step_id: 1,
            state: "done",
            user_ids: [],
            display_name: "Task-11",
            is_closed: true,
        },
    ];

    onRpc("has_access", () => true);
});

const calendarMountParams = {
    resModel: "project.task",
    type: "calendar",
    arch: `
        <calendar date_start="date_end" mode="month"
                    js_class="project_task_calendar">
            <field name="project_id" widget="project" invisible="context.get('default_project_id', False)"/>
            <field name="step_id" invisible="not project_id or not step_id" widget="task_step_with_state_selection"/>
        </calendar>
    `,
};

test("test Project Task Calendar Popover with task_step_with_state_selection widget", async () => {
    await mountView(calendarMountParams);

    await click(".o_event[data-event-id='1']");

    // Skipping setTimeout while clicking event in calendar for calendar popover to appear.
    // There is a timeout set in the useCalendarPopover.
    await runAllTimers();

    expect(queryOne(".o_field_task_step_with_state_selection > div").childElementCount).toBe(2);
});

test("test task_step_with_state_selection widget with non-editable state", async () => {
    await mountView({
        ...calendarMountParams,
        arch: `
            <calendar date_start="date_end" mode="month"
                        js_class="project_task_calendar">
                <field name="project_id" widget="project" invisible="context.get('default_project_id', False)"/>
                <field name="step_id" invisible="not project_id or not step_id" widget="task_step_with_state_selection" options="{'state_readonly': True}"/>
            </calendar>
        `,
    });

    await click(".o_event[data-event-id='1']");

    // Skipping setTimeout while clicking event in calendar for calendar popover to appear.
    // There is a timeout set in the useCalendarPopover.
    await runAllTimers();

    await click("button[title='In Progress']");

    expect(".project_task_state_selection_menu").toHaveCount(0);
});

test("test task_step_with_state_selection widget with editable state", async () => {
    await mountView({
        ...calendarMountParams,
        arch: `
            <calendar date_start="date_end" mode="month"
                        js_class="project_task_calendar">
                <field name="project_id" widget="project" invisible="context.get('default_project_id', False)"/>
                <field name="step_id" invisible="not project_id or not step_id" widget="task_step_with_state_selection" options="{'state_readonly': False}"/>
            </calendar>
        `,
    });

    await click(".o_event[data-event-id='1']");

    // Skipping setTimeout while clicking event in calendar for calendar popover to appear.
    // There is a timeout set in the useCalendarPopover.
    await runAllTimers();

    await click(".o-dropdown div[title='In Progress']");
    await animationFrame();
    // Unlike the state_readonly variant, the state menu opens and offers the
    // task states. NB: persistence cannot be asserted here — calendar popover
    // fields are mounted on a readonly-mode standalone Record, whose update()
    // is a no-op by framework design (hence the shipped archs keep the
    // default state_readonly=True and mark e.g. priority readonly="1").
    expect(".project_task_state_selection_menu").toHaveCount(1);
    expect(".project_task_state_selection_menu .o_status_green").toHaveCount(1);
});

test("Display closed tasks as past event", async () => {
    ProjectTask._records.push({
        id: 2,
        name: "Task-2",
        date_end: "2024-01-09 07:00:00",
        create_date: "2024-01-03 12:00:00",
        project_id: 1,
        step_id: 1,
        state: "done",
        user_ids: [],
        display_name: "Task-2",
    });
    ProjectTask._records.push({
        id: 3,
        name: "Task-3",
        date_end: "2024-01-09 07:00:00",
        create_date: "2024-01-03 12:00:00",
        project_id: 1,
        step_id: 1,
        state: "canceled",
        user_ids: [],
        display_name: "Task-3",
    });
    ProjectTask._records.push({
        id: 4,
        name: "Task-4",
        date_end: "2024-01-09 07:00:00",
        create_date: "2024-01-03 12:00:00",
        project_id: 1,
        step_id: 1,
        state: "canceled",
        user_ids: [],
        display_name: "Task-4",
        is_closed: true,
    });
    await mountView(calendarMountParams);
    expect(".o_event").toHaveCount(4);
    expect(".o_event.o_past_event").toHaveCount(3);
});

test("tasks to schedule should not be visible in the sidebar if no default project set in the context", async () => {
    onRpc("project.task", "search_read", ({ method }) => {
        expect.step(method);
    });
    onRpc("project.task", "web_search_read", () => {
        expect.step("fetch tasks to schedule");
    });

    await mountView(calendarMountParams);
    expect(".o_calendar_view").toHaveCount(1);
    expect(".o_task_to_plan_draggable").toHaveCount(0);
    expect.verifySteps(["search_read"]);
});

test("tasks to plan should be visible in the sidebar when `default_project_id` is set in the context", async () => {
    onRpc("project.task", "search_read", ({ method }) => {
        expect.step(method);
    });
    onRpc("project.task", "web_search_read", () => {
        expect.step("fetch tasks to schedule");
    });

    await mountView({
        ...calendarMountParams,
        context: { default_project_id: 1 },
    });
    expect(".o_calendar_view").toHaveCount(1);
    expect(".o_task_to_plan_draggable").toHaveCount(2);
    expect(queryAllTexts(".o_task_to_plan_draggable")).toEqual(['Task-10', 'Task-11']);
    expect(".o_calendar_view .o_calendar_sidebar h5").toHaveText("Drag Tasks to Schedule");
    expect.verifySteps(["search_read", "fetch tasks to schedule"]);
});

test("search domain should be taken into account in Tasks to Schedule", async () => {
    onRpc("project.task", "search_read", ({ method }) => {
        expect.step(method);
    });
    onRpc("project.task", "web_search_read", () => {
        expect.step("fetch tasks to schedule");
    });

    await mountView({
        ...calendarMountParams,
        context: { default_project_id: 1 },
        domain: [['is_closed', '=', false]],
    });
    expect(".o_calendar_view").toHaveCount(1);
    expect(".o_task_to_plan_draggable").toHaveCount(1);
    expect(".o_task_to_plan_draggable").toHaveText('Task-10');
    expect(".o_calendar_view .o_calendar_sidebar h5").toHaveText("Drag Tasks to Schedule");
    expect.verifySteps(["search_read", "fetch tasks to schedule"]);
});

test("planned dates used in search domain should not be taken into account in Tasks to Schedule", async () => {
    onRpc("project.task", "search_read", ({ method }) => {
        expect.step(method);
    });
    onRpc("project.task", "web_search_read", () => {
        expect.step("fetch tasks to schedule");
    });

    await mountView({
        ...calendarMountParams,
        context: { default_project_id: 1 },
        domain: [['is_closed', '=', false], ['date_end', '!=', false], ['planned_date_begin', '!=', false]],
    });
    expect(".o_calendar_view").toHaveCount(1);
    expect(".o_task_to_plan_draggable").toHaveCount(1);
    expect(".o_task_to_plan_draggable").toHaveText('Task-10');
    expect(".o_calendar_view .o_calendar_sidebar h5").toHaveText("Drag Tasks to Schedule");
    expect.verifySteps(["search_read", "fetch tasks to schedule"]);
});

test("test drag and drop a task to schedule in calendar view in month scale", async () => {
    let expectedDate = null;

    onRpc("project.task", "search_read", ({ method }) => {
        expect.step(method);
    });
    onRpc("project.task", "web_search_read", () => {
        expect.step("fetch tasks to schedule");
    });
    onRpc("project.task", "plan_task_in_calendar", ({ args }) => {
        const [taskIds, vals] = args;
        expect(taskIds).toEqual([10]);
        const expectedDateDeadline = serializeDateTime(expectedDate.set({ hours: 19 }));
        expect(vals).toEqual({
            date_end: expectedDateDeadline,
        });
        expect.step("plan task");
    });

    await mountView({
        ...calendarMountParams,
        context: { default_project_id: 1 },
    });
    expect(".o_task_to_plan_draggable").toHaveCount(2);
    const { drop, moveTo } = await contains(".o_task_to_plan_draggable:first").drag();
    const dateCell = queryFirst(".fc-day.fc-day-today.fc-daygrid-day");
    expectedDate = luxon.DateTime.fromISO(dateCell.dataset.date);
    await moveTo(dateCell);
    expect(dateCell).toHaveClass("o-highlight");
    await drop();
    expect.verifySteps(["search_read", "fetch tasks to schedule", "plan task", "search_read"]);
    expect(".o_task_to_plan_draggable").toHaveCount(1);
    expect(".o_task_to_plan_draggable").toHaveText("Task-11");
});

test("project.task (calendar): toggle sub-tasks", async () => {
    ProjectTask._records = [
        {
            id: 1,
            project_id: 1,
            name: "Task 1",
            step_id:  1,
            display_in_project: true,
            date_end: "2024-01-09 07:00:00",
            create_date: "2024-01-03 12:00:00",
        },
        {
            id: 2,
            project_id: 1,
            name: "Task 2",
            step_id:  1,
            display_in_project: false,
            date_end: "2024-01-09 07:00:00",
            create_date: "2024-01-03 12:00:00",
        }
    ];
    await mountView(calendarMountParams);
    expect(".o_event").toHaveCount(1);
    expect(".o_control_panel_navigation button i.fa-sliders").toHaveCount(1);
    await click(".o_control_panel_navigation button i.fa-sliders");
    await waitFor("span.o-dropdown-item");
    expect("span.o-dropdown-item").toHaveText("Show Sub-Tasks");
    await click("span.o-dropdown-item");
    await animationFrame();
    expect(".o_event").toHaveCount(2);
});
