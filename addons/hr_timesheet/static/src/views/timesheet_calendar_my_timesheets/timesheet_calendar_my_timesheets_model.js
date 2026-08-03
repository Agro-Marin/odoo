/** @odoo-module native */
import { CalendarModel } from "@web/views/calendar";

export class TimesheetCalendarMyTimesheetsModel extends CalendarModel {
    /**
     * @override
     */
    async multiCreateRecords(multiCreateData, dates) {
        this.meta.context = this.meta.context || {};
        this.meta.context.timesheet_calendar = true;
        return super.multiCreateRecords(multiCreateData, dates);
    }
}
