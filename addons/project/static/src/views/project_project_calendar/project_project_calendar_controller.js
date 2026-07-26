/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { CalendarController } from "@web/views/calendar/calendar_controller";

export class ProjectProjectCalendarController extends CalendarController {
    get editRecordDefaultDisplayText() {
        return _t("New Project");
    }
}
