import { mailModels, openView } from "@mail/../tests/mail_test_helpers";
import { fields } from "@web/../tests/web_test_helpers";

export class MailActivity extends mailModels.MailActivity {
    name = fields.Char();

    async action_create_calendar_event() {
        await openView({
            res_model: "calendar.event",
            views: [[false, "calendar"]],
        });
        return {
            type: "ir.actions.act_window",
            name: "Meetings",
            res_model: "calendar.event",
            view_mode: "calendar",
            views: [[false, "calendar"]],
            target: "current",
            context: {
                default_activity_type_id: this.activity_type_id,
                default_res_id: this.res_id,
                default_res_model: this.res_model,
                default_name: this.res_name,
                default_description: this.note,
                default_activity_ids: [(6, 0, this.ids)],
                default_partner_ids: this.user_id.partner_id,
                default_user_id: this.user_id,
                initial_date: this.date_deadline,
                default_calendar_event_id: this.calendar_event_id,
                orig_activity_ids: this.ids,
                return_to_parent_breadcrumb: true,
            },
        };
    }
    unlink_w_meeting() {
        const events = this.map((act) => act.calendar_event_id).filter(Boolean);
        // Mirror the real model: only unlink an event no OTHER activity
        // (outside self) still references.
        const eventsToUnlink = events.filter((eventId) => {
            const otherActivities = this.env["mail.activity"].search([
                ["calendar_event_id", "=", eventId],
                ["id", "not in", this.ids],
            ]);
            return otherActivities.length === 0;
        });
        const res = this.unlink(arguments[0]);
        this.env["calendar.event"].unlink(eventsToUnlink);
        return res;
    }

    /** @param {number[]} ids */
    _to_store(store) {
        super._to_store(...arguments);
        for (const activity of this) {
            store._add_record_fields(this.browse(activity.id), {
                calendar_event_id: activity.calendar_event_id || false,
            });
        }
    }
}
