/** @odoo-module native */
import { Component } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets";

export class AppointmentInviteCopyClose extends Component {
    static props = {
        ...standardWidgetProps,
    };
    static template = "calendar.booking.AppointmentInviteCopyClose";
    /**
     * We want to disable the "Save & Copy" button if there is a warning that could
     * result to have an incorrect/empty link.
     */
    setup() {
        this.notification = useService("notification");
        this.action = useService("action");
    }
    /**
     * Save the invitation and copy the url in the clipboard
     * @param ev
     */
    async onSaveAndCopy() {
        if (this.props.readonly) {
            return;
        }

        if (!this.props.record.data.identical_config_id) {
            const recordSaved = await this.props.record.save();
            if (!recordSaved) {
                return;
            }
        }

        const bookUrl = this.props.record.data.book_url;
        setTimeout(async () => {
            await browser.navigator.clipboard.writeText(bookUrl);
            this.notification.add(_t("Link copied to clipboard!"), { type: "success" });
            this.env.dialogData.close();
            if (
                this.action.currentController?.props?.resModel === "appointment.invite"
            ) {
                // coming from an appointment.invite action, refresh the model state to show the changes
                this.action.loadState();
            }
        });
    }
}

export const appointmentInviteCopyClose = {
    component: AppointmentInviteCopyClose,
    fieldDependencies: [{ name: "disable_save_button", type: "boolean" }],
};
registry
    .category("view_widgets")
    .add("appointment_invite_copy_close", appointmentInviteCopyClose);
