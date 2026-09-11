import { mailModels } from "@mail/../tests/mail_test_helpers";
import { fields } from "@web/../tests/web_test_helpers";

export class MailActivity extends mailModels.MailActivity {
    name = fields.Char();
    calendar_event_id = fields.Many2one({ relation: "calendar.event" });

    action_create_calendar_event(idOrIds) {
        const activities = this.browse(idOrIds);
        const [activity] = activities;
        const [user] = this.env["res.users"].browse(activity.user_id);
        return {
            type: "ir.actions.act_window",
            name: "Meetings",
            res_model: "calendar.event",
            view_mode: "calendar",
            views: [[false, "calendar"]],
            target: "current",
            context: {
                default_activity_type_id: activity.activity_type_id,
                default_res_id: activity.res_id,
                default_res_model: activity.res_model,
                default_name: activity.res_name,
                default_description: activity.note,
                default_activity_ids: [[6, 0, activities.map((a) => a.id)]],
                default_partner_ids: user ? [user.partner_id] : [],
                default_user_id: activity.user_id,
                initial_date: activity.date_deadline,
                default_calendar_event_id: activity.calendar_event_id,
                orig_activity_ids: activities.map((a) => a.id),
                return_to_parent_breadcrumb: true,
            },
        };
    }

    /** @param {number | number[]} idOrIds */
    unlink_w_meeting(idOrIds) {
        const activities = this.browse(idOrIds);
        const ids = activities.map((a) => a.id);
        const events = activities.map((a) => a.calendar_event_id).filter(Boolean);
        // Mirror the real model: only unlink an event no OTHER activity
        // (outside the ones being unlinked) still references.
        const eventsToUnlink = events.filter(
            (eventId) =>
                this.search([
                    ["calendar_event_id", "=", eventId],
                    ["id", "not in", ids],
                ]).length === 0,
        );
        const res = this.unlink(ids);
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
