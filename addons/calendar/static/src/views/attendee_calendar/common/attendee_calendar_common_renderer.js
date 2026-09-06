/** @odoo-module native */
import { AttendeeCalendarCommonPopover } from "@calendar/views/attendee_calendar/common/attendee_calendar_common_popover";
import { getAttendeeStatusClass } from "@calendar/views/attendee_calendar/attendee_calendar_utils";
import { CalendarCommonRenderer } from "@web/views/calendar";

export class AttendeeCalendarCommonRenderer extends CalendarCommonRenderer {
    static eventTemplate = "calendar.AttendeeCalendarCommonRenderer.event";
    static components = {
        ...CalendarCommonRenderer.components,
        Popover: AttendeeCalendarCommonPopover,
    };
    /**
     * @override
     *
     * Give a new key to our fc records to be able to iterate through in templates
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
    onEventDidMount({ el, event }) {
        super.onEventDidMount(...arguments);
        const record = this.props.model.records[event.id];
        if (record) {
            if (
                this.env.searchModel?.context?.default_calendar_event_id ===
                parseInt(event.id)
            ) {
                this.openPopover(el, record);
            }
        }
    }

    /**
     * @override
     *
     * Allow slots to be selected over multiple days
     */
    isSelectionAllowed(event) {
        return true;
    }
}
