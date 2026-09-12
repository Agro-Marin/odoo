/** @odoo-module native */
import { getAttendeeStatusClass } from "@calendar/views/attendee_calendar/attendee_calendar_utils";
import { AttendeeCalendarCommonPopover } from "@calendar/views/attendee_calendar/common/attendee_calendar_common_popover";
import { toRaw } from "@odoo/owl";
import { CalendarCommonRenderer } from "@web/views/calendar";

/** @type {WeakSet<object>} */
const defaultEventPopoverOpened = new WeakSet();

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
    onEventDidMount({ el, event }) {
        super.onEventDidMount(...arguments);
        const record = this.props.model.records[event.id];
        if (
            record &&
            this.env.searchModel?.context?.default_calendar_event_id ===
                parseInt(event.id) &&
            !defaultEventPopoverOpened.has(toRaw(this.props.model))
        ) {
            // the prop is a reactive proxy that differs per renderer instance
            defaultEventPopoverOpened.add(toRaw(this.props.model));
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
