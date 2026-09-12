/** @odoo-module native */
import { getAttendeeStatusClass } from "@calendar/views/attendee_calendar/attendee_calendar_utils";
import { AttendeeCalendarCommonPopover } from "@calendar/views/attendee_calendar/common/attendee_calendar_common_popover";
import { CalendarCommonRenderer } from "@web/views/calendar";

export class AttendeeCalendarCommonRenderer extends CalendarCommonRenderer {
    static eventTemplate = "calendar.AttendeeCalendarCommonRenderer.event";
    static components = {
        ...CalendarCommonRenderer.components,
        Popover: AttendeeCalendarCommonPopover,
    };
    /**
     * @override
     */
    convertRecordToEvent(record) {
        let editable = false;
        if (record && record.rawRecord) {
            editable = record.rawRecord.user_can_edit;
        }
        return {
            ...super.convertRecordToEvent(record),
            id: record._recordId || record.id,
            editable: editable,
        };
    }

    /**
     * @override
     */
    eventClassNames({ el, event }) {
        const classesToAdd = super.eventClassNames(...arguments);
        const record = this.props.model.records[event.id];
        if (record) {
            if (record.rawRecord.is_highlighted) {
                classesToAdd.push("o_event_highlight");
            }
            classesToAdd.push(getAttendeeStatusClass(record));
        }
        return classesToAdd;
    }

    /**
     * @override
     */
    onEventDidMount(info) {
        super.onEventDidMount(...arguments);
        const { el, event, isDragging, isMirror } = info;
        const record = this.props.model.records[event.id];
        if (
            record &&
            this.env.searchModel?.context?.default_calendar_event_id ===
                parseInt(event.id) &&
            !this.popover.isOpen &&
            !isDragging &&
            !isMirror
        ) {
            this.openPopover(el, record);
        }
    }

    /**
     * @override
     */
    isSelectionAllowed(event) {
        return true;
    }
}
