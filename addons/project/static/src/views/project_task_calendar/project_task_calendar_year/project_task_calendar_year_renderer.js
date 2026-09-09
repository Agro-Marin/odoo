/** @odoo-module native */
import { CalendarYearRenderer } from "@web/views/calendar";

import { patchCommonRenderer } from "../project_task_calendar_common/project_task_calendar_common_renderer.js";

export class ProjectTaskCalendarYearRenderer extends CalendarYearRenderer {}
patchCommonRenderer(ProjectTaskCalendarYearRenderer);
