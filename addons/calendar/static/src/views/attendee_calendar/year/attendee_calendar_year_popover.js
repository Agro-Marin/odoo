/** @odoo-module native */
import { getAttendeeStatusClass } from "@calendar/views/attendee_calendar/attendee_calendar_utils";
import { CalendarYearPopover } from "@web/views/calendar";

export class AttendeeCalendarYearPopover extends CalendarYearPopover {
    static subTemplates = {
        ...CalendarYearPopover.subTemplates,
        body: "calendar.AttendeeCalendarYearPopover.body",
    };
    getRecordClass(record) {
        const classes = [super.getRecordClass(record), getAttendeeStatusClass(record)];
        return classes.join(" ");
    }
}
