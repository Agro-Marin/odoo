/** @odoo-module native */
import { MessagingMenu } from "@mail/core/public_web/messaging_menu";
import { patch } from "@web/core/utils/patch";
patch(MessagingMenu.prototype, {
    /** @param {import("models").Thread} thread */
    markAsRead(thread) {
        super.markAsRead(...arguments);
        if (thread.model === "discuss.channel") {
            thread.markAsRead();
        }
    },
});
