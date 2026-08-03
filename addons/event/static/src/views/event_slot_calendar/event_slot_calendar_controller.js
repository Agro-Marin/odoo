/** @odoo-module native */
import { CalendarController } from "@web/views/calendar";
import { _t } from "@web/core/translation";

export class EventSlotCalendarController extends CalendarController {
    /**
     * Rename mobile quick create dialog.
     * Load model after save to show created record.
     */
    getQuickCreateFormViewProps(record) {
        return {
            ...super.getQuickCreateFormViewProps(record),
            onRecordSaved: () => this.model.load(),
            title: _t("New Slot"),
        };
    }
}
