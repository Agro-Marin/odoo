/** @odoo-module native */
import { AppointmentTypeActionHelper } from "@calendar/booking/components/appointment_type_action_helper/appointment_type_action_helper";
import { onWillStart } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { ListRenderer } from "@web/views/list";

export class AppointmentBookingListRenderer extends ListRenderer {
    static template = "calendar.booking.AppointmentBookingListRenderer";

    setup() {
        super.setup();

        onWillStart(async () => {
            this.isAppointmentManager = await user.hasGroup(
                "calendar.group_appointment_manager",
            );
            // Using this context key is a stable workaround, to be improved in master
            this.isResourceView =
                this.props.list.context.appointment_default_assign_user_attendees ===
                false;
        });
    }

    async onClickAddLeave() {
        this.env.services.action.doAction({
            name: _t("Add Closing Day(s)"),
            type: "ir.actions.act_window",
            res_model: "appointment.manage.leaves",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
            context: {},
        });
    }
}

export class AppointmentTypeListRenderer extends ListRenderer {
    static template = "calendar.booking.AppointmentTypeListRenderer";
    static components = {
        ...ListRenderer.components,
        AppointmentTypeActionHelper,
    };
}
