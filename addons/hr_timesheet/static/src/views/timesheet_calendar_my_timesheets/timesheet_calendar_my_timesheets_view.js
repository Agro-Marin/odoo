/** @odoo-module native */
import { registry } from "@web/core/registry";
import { calendarView } from "@web/views/calendar";
import { TimesheetCalendarMyTimesheetsModel } from "./timesheet_calendar_my_timesheets_model.js";

export const timesheetCalendarMyTimesheetsView = {
    ...calendarView,
    Model: TimesheetCalendarMyTimesheetsModel,
};

registry
    .category("views")
    .add("timesheet_calendar_my_timesheets", timesheetCalendarMyTimesheetsView);
