/** @odoo-module */
import { CalendarRenderer } from "@web/views/calendar/calendar_renderer";

import { ActivityCalendarCommonRender } from "./calendar_common/activity_calendar_common_renderer.js";
import { ActivityCalendarYearRenderer } from "./calendar_year/activity_calendar_year_renderer.js";
export class ActivityCalendarRender extends CalendarRenderer {
    static components = {
        ...CalendarRenderer.components,
        day: ActivityCalendarCommonRender,
        week: ActivityCalendarCommonRender,
        month: ActivityCalendarCommonRender,
        year: ActivityCalendarYearRenderer,
    };
}
