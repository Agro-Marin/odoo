/** @odoo-module native */
import { CalendarCommonPopover } from "@web/views/calendar";

export class CalendarWithRecurrenceCommonPopover extends CalendarCommonPopover {
    onEditEvent() {
        this.props.record.id = this.props.record.rawRecord.id;
        super.onEditEvent();
    }
    onDeleteEvent() {
        this.props.record.id = this.props.record.rawRecord.id;
        super.onDeleteEvent();
    }
}
