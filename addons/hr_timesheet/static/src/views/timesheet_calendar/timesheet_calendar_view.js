/** @odoo-module native */
import { registry } from "@web/core/registry";
import { timesheetCalendarMyTimesheetsView } from "../timesheet_calendar_my_timesheets/timesheet_calendar_my_timesheets_view.js";
import { TimesheetCalendarModel } from "./timesheet_calendar_model.js";

export const timesheetCalendarView = {
    ...timesheetCalendarMyTimesheetsView,
    Model: TimesheetCalendarModel,
};

registry.category("views").add("timesheet_calendar", timesheetCalendarView);
