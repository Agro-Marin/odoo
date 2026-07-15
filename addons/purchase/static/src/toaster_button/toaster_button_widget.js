/** @odoo-module native */
import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

class ButtonWithNotification extends Component {
    static template = "purchase.ButtonWithNotification";
    static props = {
        ...standardWidgetProps,
        method: String,
        title: String,
    };
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    async onClick() {
        const result = await this.orm.call(
            this.props.record.resModel,
            this.props.method,
            [this.props.record.resId],
        );
        // The backend method may legitimately return nothing (e.g. the action
        // could not be performed); never assume a payload is present.
        if (result?.toast_message) {
            this.notification.add(result.toast_message, {
                type: result.toast_type || "success",
            });
        } else {
            this.notification.add(_t("The action could not be completed."), {
                type: "warning",
            });
        }
    }
}

export const buttonWithNotification = {
    component: ButtonWithNotification,
    extractProps: ({ attrs }) => ({
        method: attrs.button_name,
        title: attrs.title,
    }),
};
registry.category("view_widgets").add("toaster_button", buttonWithNotification);
