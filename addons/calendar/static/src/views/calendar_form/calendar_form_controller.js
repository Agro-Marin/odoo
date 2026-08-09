/** @odoo-module native */
import { useAskRecurrenceUpdatePolicy } from "@calendar/views/ask_recurrence_update_policy_hook";
import { useService } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form";

export class CalendarFormController extends FormController {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.askRecurrenceUpdatePolicy = useAskRecurrenceUpdatePolicy();
    }

    /**
     * @override
     */
    async beforeExecuteActionButton(clickParams) {
        const action = clickParams.name;
        if (action === "clear_videocall_location") {
            this.model.root.clearLocation();
            return false;
        } else if (action === "set_discuss_videocall_location") {
            this.model.root.setLocation();
            return false;
        }
        return super.beforeExecuteActionButton(...arguments);
    }

    /**
     * Custom delete function for calendar events, which can call the unlink action or not.
     * When there is only one attendee, who is also the organizer, and the organizer is not listed in the current attendees, it performs the default delete.
     * Otherwise, it calls the unlink action on the server.
     */
    async deleteRecord() {
        const record = this.model.root;
        const rootValues = record._values;
        let recurrenceUpdate = false;
        if (record.data.recurrency) {
            recurrenceUpdate = await this.askRecurrenceUpdatePolicy();
        }
        if (rootValues.attendees_count == 1 && rootValues.user_id.id !== rootValues.partner_ids._currentIds[0]) {
            await this._archiveRecord(record.resId, recurrenceUpdate);
        } else {
            // Send the answer the user just gave in the dialog. This branch used
            // to send `data.recurrence_update` -- the inline radio at the top of
            // the form -- so answering "All events" in the dialog while the radio
            // still read "This event" deleted a single occurrence. Fall back to
            // the field only when there was no dialog (a non-recurrent event).
            await this.orm.call("calendar.event", "action_unlink_event", [
                this.model.root.resId,
                recurrenceUpdate || this.model.root.data.recurrence_update,
            ])
            .then((action) => {
                if (action && action.context) {
                    this.actionService.doAction(action);
                } else {
                    this.actionService.doAction({
                        type: "ir.actions.act_window",
                        name: "Meetings",
                        res_model: "calendar.event",
                        view_mode: "calendar",
                        views: [[false, "calendar"]],
                        target: "current",
                    });
                }
            });
        }
    }

    /**
     * Archives a calendar event record.
     *
     * @param {number} id - The ID of the record to archive.
     * @param {boolean} recurrenceUpdate - Indicates how the archive of a recurring event will be updated.
     */
    async _archiveRecord(id, recurrenceUpdate) {
        await this.orm.call(this.model.root.resModel, "action_mass_archive", [
            [id], recurrenceUpdate
        ]);
        this.env.config.historyBack();
    }
}
