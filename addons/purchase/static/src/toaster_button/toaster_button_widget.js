/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets";

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
        this.state = useState({ pending: false });
    }

    /** @returns {boolean} */
    get isDisabled() {
        return this.state.pending || Boolean(this.props.readonly);
    }

    async onClick() {
        if (this.isDisabled) {
            return;
        }
        this.state.pending = true;
        let result;
        try {
            result = await this.orm.call(
                this.props.record.resModel,
                this.props.method,
                [this.props.record.resId],
            );
        } finally {
            this.state.pending = false;
        }
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
