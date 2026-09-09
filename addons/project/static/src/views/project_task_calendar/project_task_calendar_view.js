/** @odoo-module native */
import { registry } from "@web/core/registry";
import { calendarView } from "@web/views/calendar";

import { HighlightProjectTaskSearchModel } from "../highlight_project_task_search_model.js";
import { ProjectTaskControlPanel } from "../project_task_control_panel/project_task_control_panel.js";
import { ProjectTaskCalendarController } from "./project_task_calendar_controller.js";
import { ProjectTaskCalendarModel } from "./project_task_calendar_model.js";
import { ProjectTaskCalendarRenderer } from "./project_task_calendar_renderer.js";

export const projectTaskCalendarView = {
    SearchModel: HighlightProjectTaskSearchModel,
    ...calendarView,
    ControlPanel: ProjectTaskControlPanel,
    Controller: ProjectTaskCalendarController,
    Model: ProjectTaskCalendarModel,
    Renderer: ProjectTaskCalendarRenderer,
};
registry.category("views").add("project_task_calendar", projectTaskCalendarView);
