/** @odoo-module native */
import { _t } from "@web/core/translation";
import { CalendarController } from "@web/views/calendar";

export class ProjectProjectCalendarController extends CalendarController {
    get editRecordDefaultDisplayText() {
        return _t("New Project");
    }
}
