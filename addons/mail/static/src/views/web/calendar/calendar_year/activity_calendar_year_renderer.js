/** @odoo-module native */
import { CalendarYearRenderer } from "@web/views/calendar";

import { ActivityCalendarYearPopover } from "./activity_calendar_year_popover.js";
export class ActivityCalendarYearRenderer extends CalendarYearRenderer {
    static components = {
        ...CalendarYearRenderer.components,
        Popover: ActivityCalendarYearPopover,
    };
}
