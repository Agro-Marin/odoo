/** @odoo-module native */
import { CalendarCommonRenderer } from "@web/views/calendar";

import { ActivityCalendarCommonPopover } from "./activity_calendar_common_popover.js";
export class ActivityCalendarCommonRender extends CalendarCommonRenderer {
    static components = {
        ...CalendarCommonRenderer.components,
        Popover: ActivityCalendarCommonPopover,
    };
}
