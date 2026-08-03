/** @odoo-module native */
import { CalendarRenderer } from "@web/views/calendar";
import { WorkEntryCalendarCommonRenderer } from "@hr_work_entry/views/work_entry_calendar/calendar_common/work_entry_calendar_common_renderer";

export class WorkEntryCalendarRenderer extends CalendarRenderer {
    static components = {
        ...CalendarRenderer.components,
        month: WorkEntryCalendarCommonRenderer,
    };
    static props = {
        ...CalendarRenderer.props,
        splitRecord: Function,
    };
}
