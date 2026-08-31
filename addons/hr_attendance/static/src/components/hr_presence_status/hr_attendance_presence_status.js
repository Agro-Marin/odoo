/** @odoo-module native */
import { onMounted, onWillUnmount } from "@odoo/owl";
import { HrPresenceStatus } from "@hr/components/hr_presence_status/hr_presence_status";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

export const PRESENCE_NOTIFICATION = "hr.employee/presence";

patch(HrPresenceStatus.prototype, {
    setup() {
        super.setup();
        this.busService = useService("bus_service");
        this.onPresenceNotification = this.onPresenceNotification.bind(this);
        onMounted(() => {
            if (!this.presenceChannel) {
                return;
            }
            this.busService.addChannel(this.presenceChannel);
            this.busService.subscribe(PRESENCE_NOTIFICATION, this.onPresenceNotification);
        });
        onWillUnmount(() => {
            if (!this.presenceChannel) {
                return;
            }
            this.busService.unsubscribe(PRESENCE_NOTIFICATION, this.onPresenceNotification);
            this.busService.deleteChannel(this.presenceChannel);
        });
    },

    /**
     * hr.employee.public shares its ids with hr.employee, so a render of either
     * listens on the same channel. An unsaved record has no id to
     * listen on at all.
     */
    get presenceChannel() {
        const resId = this.props.record.resId;
        return resId ? `hr.employee_${resId}` : false;
    },

    onPresenceNotification(payload) {
        if (payload?.employee_id !== this.props.record.resId) {
            return;
        }
        this.props.record._applyValues({
            hr_presence_state: payload.hr_presence_state,
            hr_icon_display: payload.hr_icon_display,
        });
    },
});
