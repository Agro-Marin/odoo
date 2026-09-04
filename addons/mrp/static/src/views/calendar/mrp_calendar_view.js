/** @odoo-module native */
import { calendarView } from "@web/views/calendar";
import { MrpCalendarRenderer } from "@mrp/views/calendar/mrp_calendar_renderer";
import { registry } from "@web/core/registry";

export const MrpCalendarView = {
    ...calendarView,
    Renderer: MrpCalendarRenderer,
};

registry.category("views").add("mrp_calendar", MrpCalendarView);
