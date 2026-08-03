/** @odoo-module native */
import { CalendarWithRecurrenceYearPopover } from "./calendar_with_recurrence_year_popover.js";
import { CalendarYearRenderer } from "@web/views/calendar";

export class CalendarWithRecurrenceYearRenderer extends CalendarYearRenderer {
    static components = {
        ...CalendarYearRenderer.components,
        Popover: CalendarWithRecurrenceYearPopover,
    };
}
