// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class ResetPasswordLinkButton extends Component {
    static props = standardWidgetProps;
    static template = "auth_signup.ResetPasswordLinkButton";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    async copyResetPasswordLink() {
        const link = await this.orm.call("res.users", "get_reset_password_link", [
            this.props.record.resId,
        ]);
        try {
            await browser.navigator.clipboard.writeText(link);
        } catch {
            this.notification.add(_t("Could not copy the link to the clipboard."), {
                type: "danger",
            });
            return;
        }
        this.notification.add(_t("Link copied to clipboard!"), { type: "success" });
    }
}

/** @type {import("registries").ViewWidgetsRegistryItemShape} */
const resetPasswordLinkButton = {
    component: ResetPasswordLinkButton,
    additionalClasses: ["h-100", "ms-2", "my-auto"],
};

registry
    .category("view_widgets")
    .add("auth_signup.button_reset_password_link", resetPasswordLinkButton);
