/** @odoo-module native */
import { CalendarYearRenderer } from "@web/views/calendar/calendar_year/calendar_year_renderer";
import { patchCommonRenderer } from "../project_task_calendar_common/project_task_calendar_common_renderer.js";

export class ProjectTaskCalendarYearRenderer extends CalendarYearRenderer {}
// Patch the project subclass (the one the project calendar view actually uses,
// see project_task_calendar_renderer.js), NOT the shared base class — patching
// the base grafts the task-specific "o_past_event" styling onto every year
// calendar in the app.
patchCommonRenderer(ProjectTaskCalendarYearRenderer);
