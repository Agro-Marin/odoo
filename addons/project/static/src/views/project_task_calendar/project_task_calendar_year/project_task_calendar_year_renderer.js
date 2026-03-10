/** @odoo-module */
import { CalendarYearRenderer } from "@web/views/calendar/calendar_year/calendar_year_renderer";
import { patchCommonRenderer } from "../project_task_calendar_common/project_task_calendar_common_renderer.js";

export class ProjectTaskCalendarYearRenderer extends CalendarYearRenderer {}
patchCommonRenderer(CalendarYearRenderer);
