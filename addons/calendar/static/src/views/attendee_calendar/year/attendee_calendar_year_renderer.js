/** @odoo-module native */
import { AttendeeCalendarYearPopover } from "@calendar/views/attendee_calendar/year/attendee_calendar_year_popover";
import { CalendarYearRenderer } from "@web/views/calendar";

export class AttendeeCalendarYearRenderer extends CalendarYearRenderer {
    static components = {
        ...CalendarYearRenderer.components,
        Popover: AttendeeCalendarYearPopover,
    };
}
