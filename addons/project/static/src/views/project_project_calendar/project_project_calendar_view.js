/** @odoo-module native */
import { registry } from "@web/core/registry";
import { calendarView } from "@web/views/calendar";

import { ProjectProjectCalendarController } from "./project_project_calendar_controller.js";
import { ProjectCalendarModel } from "./project_project_calendar_model.js";
import { ProjectCalendarRenderer } from "./project_project_calendar_renderer.js";

const viewRegistry = registry.category("views");

const projectProjectCalendarView = {
    ...calendarView,
    Controller: ProjectProjectCalendarController,
    Renderer: ProjectCalendarRenderer,
    Model: ProjectCalendarModel,
};

viewRegistry.add("project_project_calendar", projectProjectCalendarView);
