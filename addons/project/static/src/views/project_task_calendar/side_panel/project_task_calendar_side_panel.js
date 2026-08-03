/** @odoo-module native */
import { CalendarSidePanel } from "@web/views/calendar";

import { ProjectTaskCalendarFilterSection } from "../project_task_calendar_filter_section/project_task_calendar_filter_section.js";
import { ProjectTaskCalendarListToPlan } from "../project_task_calendar_list_to_plan/project_task_calendar_list_to_plan.js";

export class ProjectTaskCalendarSidePanel extends CalendarSidePanel {
    static components = {
        ...CalendarSidePanel.components,
        FilterSection: ProjectTaskCalendarFilterSection,
        ProjectTaskCalendarListToPlan,
    };
    static props = [...CalendarSidePanel.props, "editRecord"];
    static template = "project.ProjectTaskCalendarSidePanel";
}
