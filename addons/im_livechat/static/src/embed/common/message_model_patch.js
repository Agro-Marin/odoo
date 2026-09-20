/** @odoo-module native */
import { Message } from "@mail/core/common/message_model";
import { patch } from "@web/core/utils/patch";

/** @type {import("models").Message} */
const messagePatch = {
    setup() {
        super.setup(...arguments);
        this.disableChatbotAnswers = false;
    },

    get notificationHidden() {
        if (!this.thread.isLivechat || !this.notificationType) {
            return super.notificationHidden;
        }
        return ["channel-joined", "channel-left"].includes(this.notificationType);
    },
};
patch(Message.prototype, messagePatch);
