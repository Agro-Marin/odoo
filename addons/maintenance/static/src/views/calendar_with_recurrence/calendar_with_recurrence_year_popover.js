/** @odoo-module native */
import { CalendarYearPopover } from "@web/views/calendar";

export class CalendarWithRecurrenceYearPopover extends CalendarYearPopover {
    onRecordClick(record) {
        record.id = record.rawRecord.id;
        super.onRecordClick(record);
    }
}
