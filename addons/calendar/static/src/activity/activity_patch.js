/** @odoo-module native */
import { Activity } from "@mail/core/web/activity";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

patch(Activity.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
    },
    async onClickReschedule() {
        await this.props.activity.rescheduleMeeting();
    },
    /**
     * @override
     */
    async unlink() {
        if (this.props.activity.calendar_event_id) {
            const thread = this.thread;
            // Await the RPC before removing the local record, matching base's
            // own ordering (activity.js) -- removing it first left the store
            // showing the activity gone with no rollback if the RPC rejected,
            // while the server-side record still existed.
            await this.orm.call("mail.activity", "unlink_w_meeting", [
                [this.props.activity.id],
            ]);
            this.props.activity.remove();
            this.props.onActivityChanged(thread);
        } else {
            super.unlink();
        }
    },
});
