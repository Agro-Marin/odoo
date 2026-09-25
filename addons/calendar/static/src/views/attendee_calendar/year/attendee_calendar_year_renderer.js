/** @odoo-module native */
import { AttendeeCalendarYearPopover } from "@calendar/views/attendee_calendar/year/attendee_calendar_year_popover";
import { CalendarYearRenderer } from "@web/views/calendar";

export const attendeeCalendarYearRendererProps = { ...CalendarYearRenderer.props };

export class AttendeeCalendarYearRenderer extends CalendarYearRenderer {
    static props = attendeeCalendarYearRendererProps;
    static components = {
        ...CalendarYearRenderer.components,
        Popover: AttendeeCalendarYearPopover,
    };
}
