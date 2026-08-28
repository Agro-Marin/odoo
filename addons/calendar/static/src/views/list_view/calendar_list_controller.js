/** @odoo-module native */

import { useAskRecurrenceUpdatePolicy } from "@calendar/views/ask_recurrence_update_policy_hook";
import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list";

export class CalendarListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.askRecurrenceUpdatePolicy = useAskRecurrenceUpdatePolicy();
    }

    get modelOptions() {
        return {
            ...super.modelOptions,
            lazy: false,
        };
    }

    /**
     * Deletes selected records with handling for recurring events.
     */
    async onDeleteSelectedRecords() {
        const selectedRecords = this.model.root.selection;
        let recurrenceUpdate = false;
        if (selectedRecords.length == 1 && selectedRecords[0]?.data.recurrency) {
            recurrenceUpdate = await this.askRecurrenceUpdatePolicy();
            if (recurrenceUpdate) {
                await this.orm.call(this.model.root.resModel, "action_mass_archive", [[selectedRecords[0]?.resId], recurrenceUpdate]);
                this.model.load();
            }
        } else {
            super.onDeleteSelectedRecords(...arguments);
        }
    }
}
