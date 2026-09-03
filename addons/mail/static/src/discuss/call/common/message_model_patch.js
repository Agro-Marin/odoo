/** @odoo-module native */
import { Message } from "@mail/core/common/message_model";
import { patch } from "@web/core/utils/patch";

/**
 * @type {Partial<import("models").Message> & ThisType<import("models").Message>}
 */
const MessagePatch = {
    get notificationHidden() {
        // The meeting view already shows the call itself, so repeating "X
        // started a call" in its chat panel says nothing and pushes the actual
        // conversation down. Only the session on screen is hidden: the same
        // notice stays in the channel history once the meeting is closed.
        if (
            this.notificationType === "call" &&
            this.store.meetingViewOpened &&
            this.store.rtc.channel?.eq(this.thread)
        ) {
            return true;
        }
        return super.notificationHidden;
    },
};
patch(Message.prototype, MessagePatch);
