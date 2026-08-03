/** @odoo-module native */
import { Dialog } from "@web/ui/dialog";
import { CalendarYearPopover } from "@web/views/calendar";

export class TimeOffCalendarYearPopover extends CalendarYearPopover {
    static components = { Dialog };
    static template = "web.CalendarYearPopover";
    static subTemplates = {
        ...CalendarYearPopover.subTemplates,
        body: "hr_holidays.MandatoryDayCalendarYearPopover.body",
    };
}
