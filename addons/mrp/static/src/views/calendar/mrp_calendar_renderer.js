/** @odoo-module native */
import { CalendarCommonRenderer, CalendarRenderer } from "@web/views/calendar";

export class MrpCalendarCommonRenderer extends CalendarCommonRenderer {
    // Say what is being manufactured, not only when.
    static eventTemplate = "mrp.MrpCalendarCommonRenderer.event";
}

export class MrpCalendarRenderer extends CalendarRenderer {
    // Only the day and week cards have the room for it; the month cards and
    // the year view keep the plain title.
    static components = {
        ...CalendarRenderer.components,
        day: MrpCalendarCommonRenderer,
        week: MrpCalendarCommonRenderer,
    };
}
