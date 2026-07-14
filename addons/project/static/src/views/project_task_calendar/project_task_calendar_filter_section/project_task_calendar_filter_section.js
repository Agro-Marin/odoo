/** @odoo-module native */
import { CalendarFilterSection } from "@web/views/calendar/calendar_filter_section/calendar_filter_section";

export class ProjectTaskCalendarFilterSection extends CalendarFilterSection {
    static subTemplates = {
        ...CalendarFilterSection.subTemplates,
        filter: "project.ProjectTaskCalendarFilterSection.filter",
    };
}
