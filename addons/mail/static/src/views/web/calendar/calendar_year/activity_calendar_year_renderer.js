/** @odoo-module */
import { CalendarYearRenderer } from "@web/views/calendar/calendar_year/calendar_year_renderer";

import { ActivityCalendarYearPopover } from "./activity_calendar_year_popover.js";
export class ActivityCalendarYearRenderer extends CalendarYearRenderer {
    static components = {
        ...CalendarYearRenderer.components,
        Popover: ActivityCalendarYearPopover,
    };
}
