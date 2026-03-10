/** @odoo-module native */
import { CalendarRenderer } from "@web/views/calendar/calendar_renderer";
import { ProjectCalendarCommonRenderer } from "./common/project_common_calendar_renderer.js";

export class ProjectCalendarRenderer extends CalendarRenderer {
    static components = {
        ...CalendarRenderer.components,
        day: ProjectCalendarCommonRenderer,
        week: ProjectCalendarCommonRenderer,
        month: ProjectCalendarCommonRenderer,
    };
}
