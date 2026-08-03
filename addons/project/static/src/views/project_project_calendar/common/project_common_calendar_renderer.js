/** @odoo-module native */
import { CalendarCommonRenderer } from "@web/views/calendar";

import { ProjectCalendarCommonPopover } from "./project_common_calendar_popover.js";

export class ProjectCalendarCommonRenderer extends CalendarCommonRenderer {
    static components = {
        ...CalendarCommonRenderer.components,
        Popover: ProjectCalendarCommonPopover,
    };
}
