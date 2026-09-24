// @ts-check
/** @odoo-module native */
import { NotificationMessage } from "@mail/core/common/notification_message";
import { useMailContext } from "@mail/utils/common/mail_context";
import { patch } from "@web/core/utils/patch";
patch(NotificationMessage.prototype, {
    setup() {
        super.setup(...arguments);
        this.mailContext = useMailContext();
    },

    /** @param {MouseEvent} ev */
    async onClickNotificationMessage(ev) {
        const { oeType } = /** @type {HTMLElement} */ (ev.target).dataset;
        if (oeType === "pin-menu") {
            this.mailContext.pinMenu?.open();
        }
        await super.onClickNotificationMessage(...arguments);
    },
});
