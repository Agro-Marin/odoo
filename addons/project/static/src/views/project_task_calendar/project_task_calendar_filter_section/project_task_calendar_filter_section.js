/** @odoo-module native */
import { CalendarFilterSection } from "@web/views/calendar";

export class ProjectTaskCalendarFilterSection extends CalendarFilterSection {
    static subTemplates = {
        ...CalendarFilterSection.subTemplates,
        filter: "project.ProjectTaskCalendarFilterSection.filter",
    };
}
