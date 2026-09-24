/** @odoo-module native */
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { Message } from "@mail/core/common/message";

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

patch(Message.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.action = useService("action");
    },

    async onClickNotification(ev) {
        const hasAccountFailure = this.message.notification_ids.some(
            (notification) =>
                notification.isFailure && notification.failure_type === "sms_acc",
        );
        if (
            this.message.message_type === "sms" &&
            hasAccountFailure &&
            (await user.hasGroup("base.group_system"))
        ) {
            const [accountId] = await this.orm.call("iap.account", "get", [], {
                service_name: "sms",
                force_create: false,
            });
            if (accountId) {
                this.action.doAction({
                    type: "ir.actions.act_window",
                    name: _t("SMS Account"),
                    target: "current",
                    res_model: "iap.account",
                    res_id: accountId,
                    views: [[false, "form"]],
                });
                return;
            }
        }

        super.onClickNotification(ev);
    },
});
