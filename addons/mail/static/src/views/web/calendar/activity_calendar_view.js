/** @odoo-module native */
import { registry } from "@web/core/registry";
import { calendarView } from "@web/views/calendar";

import { ActivityCalendarRender } from "./activity_calendar_renderer.js";

const activityCalendarView = {
    ...calendarView,
    Renderer: ActivityCalendarRender,
};

registry.category("views").add("activity_calendar", activityCalendarView);
