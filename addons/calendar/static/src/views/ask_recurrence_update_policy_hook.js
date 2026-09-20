/** @odoo-module native */
import { askRecurrenceUpdate } from "@resource/recurrence/ask_recurrence_update_dialog";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

function calendarRecurrenceUpdateProps() {
    return {
        title: _t("Edit Recurrent event"),
        choices: {
            this: _t("This event"),
            subsequent: _t("This and following events"),
            all: _t("All events"),
        },
    };
}

export function askRecurrenceUpdatePolicy(dialogService) {
    return askRecurrenceUpdate(dialogService, calendarRecurrenceUpdateProps());
}

export function useAskRecurrenceUpdatePolicy() {
    const dialogService = useService("dialog");
    return askRecurrenceUpdatePolicy.bind(null, dialogService);
}
