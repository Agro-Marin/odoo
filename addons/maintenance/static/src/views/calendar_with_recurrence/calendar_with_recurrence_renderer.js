/** @odoo-module native */
import { CalendarRenderer } from "@web/views/calendar";
import { CalendarWithRecurrenceCommonRenderer } from './calendar_with_recurrence_common_renderer.js';
import { CalendarWithRecurrenceYearRenderer } from './calendar_with_recurrence_year_renderer.js';

export class CalendarWithRecurrenceRenderer extends CalendarRenderer {
    static components = {
        ...CalendarRenderer.components,
        day: CalendarWithRecurrenceCommonRenderer,
        week: CalendarWithRecurrenceCommonRenderer,
        month: CalendarWithRecurrenceCommonRenderer,
        year: CalendarWithRecurrenceYearRenderer,
    };
}
